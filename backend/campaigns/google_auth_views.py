"""
Google OAuth2 views for connecting Gmail accounts.

Architecture notes:
- The login view passes the logged-in user's ID via the `state` param so the
  anonymous callback can link the account to the correct user + org.
- We bypass TenantManager's auto-scoping by using _default_manager on the
  base model and explicit org assignment, since the callback request is
  unauthenticated (Google redirect).
"""
import logging
import requests
from urllib.parse import urlencode, urlparse
from datetime import timedelta

from django.core import signing
from django.conf import settings
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone
from django.db.models import Q

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated

from .models import ConnectedEmailAccount

logger = logging.getLogger(__name__)

GOOGLE_OAUTH_STATE_SALT = 'leadorbit-google-oauth-state'
GOOGLE_OAUTH_STATE_MAX_AGE_SECONDS = 10 * 60


def _is_local_host(hostname: str) -> bool:
    return (hostname or '').lower() in {'localhost', '127.0.0.1'}


def _sanitize_frontend_base(request, candidate: str) -> str:
    """Return a safe absolute frontend origin or empty string."""
    raw = (candidate or '').strip().rstrip('/')
    if not raw:
        return ''

    try:
        parsed = urlparse(raw)
    except Exception:
        return ''

    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return ''

    candidate_host = (parsed.hostname or '').lower()
    request_host = (request.get_host() or '').split(':', 1)[0].lower()
    if _is_local_host(candidate_host) and not _is_local_host(request_host):
        return ''

    return f"{parsed.scheme}://{parsed.netloc}"


def _frontend_settings_redirect(request, preferred_frontend_base: str = '', **params):
    frontend_base = _sanitize_frontend_base(request, preferred_frontend_base)
    if not frontend_base:
        frontend_base = _sanitize_frontend_base(request, getattr(settings, 'FRONTEND_BASE_URL', ''))
    if not frontend_base:
        frontend_base = f"{request.scheme}://{request.get_host()}"
    query_string = urlencode(params)
    return redirect(f"{frontend_base}/settings.html?{query_string}")


def _serialize_connected_account(account):
    return {
        'id': str(account.id),
        'email': account.email_address,
        'provider': account.provider,
        'provider_display': account.get_provider_display(),
        'connected': True,
        'supports_smtp': bool(account.smtp_host and account.smtp_port),
        'supports_imap': bool(account.imap_host and account.imap_port),
    }


class CustomMailboxAccountSerializer(serializers.Serializer):
    email_address = serializers.EmailField()
    smtp_host = serializers.CharField(max_length=255)
    smtp_port = serializers.IntegerField(min_value=1, max_value=65535)
    smtp_username = serializers.CharField(max_length=255, required=False, allow_blank=True)
    smtp_password = serializers.CharField(required=False, allow_blank=True, write_only=True)
    smtp_use_tls = serializers.BooleanField(required=False, default=True)
    smtp_use_ssl = serializers.BooleanField(required=False, default=False)
    imap_host = serializers.CharField(max_length=255)
    imap_port = serializers.IntegerField(min_value=1, max_value=65535)
    imap_username = serializers.CharField(max_length=255, required=False, allow_blank=True)
    imap_password = serializers.CharField(required=False, allow_blank=True, write_only=True)
    imap_use_ssl = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        if attrs.get('smtp_use_ssl') and attrs.get('smtp_use_tls'):
            raise serializers.ValidationError(
                {'smtp_use_tls': 'Choose either SMTP SSL or STARTTLS, not both.'}
            )
        if not attrs.get('smtp_use_ssl') and not attrs.get('smtp_use_tls'):
            raise serializers.ValidationError(
                {'smtp_use_tls': 'Enable SMTP SSL or STARTTLS to protect credentials in transit.'}
            )

        email_address = attrs.get('email_address')
        attrs['smtp_username'] = (attrs.get('smtp_username') or email_address).strip()
        attrs['imap_username'] = (attrs.get('imap_username') or email_address).strip()

        smtp_password = (attrs.get('smtp_password') or '').strip()
        imap_password = (attrs.get('imap_password') or '').strip()
        if not smtp_password:
            raise serializers.ValidationError({'smtp_password': 'SMTP password is required.'})
        if not imap_password:
            raise serializers.ValidationError({'imap_password': 'IMAP password is required.'})

        attrs['smtp_password'] = smtp_password
        attrs['imap_password'] = imap_password
        attrs['email_address'] = email_address.strip().lower()
        return attrs


class GoogleOAuthLoginView(APIView):
    """
    GET /api/v1/auth/google/login?token=<jwt>
    Redirects the user to Google's OAuth2 consent screen.

    The user's JWT is passed as a query parameter since this is a
    browser navigation (not an XHR), so Authorization headers can't be sent.
    The JWT is decoded to extract user/org identity for the state parameter.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        from users.models import User
        from rest_framework_simplejwt.tokens import AccessToken

        user = None

        # Try authenticated user first (for API calls with Authorization header)
        if request.user and request.user.is_authenticated:
            user = request.user
        else:
            # Fall back to token in query param (browser navigation)
            token_str = request.GET.get('token')
            if token_str:
                try:
                    decoded = AccessToken(token_str)
                    user_id = decoded.get('user_id')
                    user = User.objects.get(id=user_id)
                    logger.info(f"[OAuth Login] Resolved user {user.email} from query token")
                except Exception as e:
                    logger.error(f"[OAuth Login] Failed to decode token from query: {e}")

        if not user:
            logger.error("[OAuth Login] No valid user found — cannot initiate OAuth")
            return _frontend_settings_redirect(request, google_auth='error', reason='not_logged_in')

        # Check organization for ALL users (authenticated or token)
        if not user.organization_id:
            logger.error(f"[OAuth Login] User {user.email} has no organization")
            return _frontend_settings_redirect(
                request,
                google_auth='error',
                reason='no_organization'
            )

        # Encode user identity in state so callback can link to correct user
        frontend_origin = _sanitize_frontend_base(request, request.GET.get('frontend_origin', ''))
        state_data = signing.dumps({
            'user_id': str(user.id),
            'org_id': str(user.organization_id),
            'frontend_origin': frontend_origin,
        }, salt=GOOGLE_OAUTH_STATE_SALT)

        params = {
            'client_id': settings.GOOGLE_CLIENT_ID,
            'redirect_uri': settings.GOOGLE_REDIRECT_URI,
            'response_type': 'code',
            'scope': ' '.join(settings.GOOGLE_SCOPES),
            'access_type': 'offline',   # gets us a refresh_token
            'prompt': 'consent',        # always show consent to get refresh_token
            'state': state_data,
        }
        url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        logger.info(f"[OAuth Login] Redirecting user {user.email} to Google consent screen")
        return redirect(url)


class GoogleOAuthCallbackView(APIView):
    """
    GET /api/v1/auth/google/callback
    Receives the authorization code from Google and exchanges it for tokens.
    Stores the credentials in ConnectedEmailAccount.

    This endpoint is AllowAny because Google redirects the browser here.
    User identity is recovered from the `state` parameter.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        state_raw = request.GET.get('state')
        frontend_origin = ''
        if state_raw:
            try:
                state_data = signing.loads(
                    state_raw,
                    salt=GOOGLE_OAUTH_STATE_SALT,
                    max_age=GOOGLE_OAUTH_STATE_MAX_AGE_SECONDS,
                )
                frontend_origin = _sanitize_frontend_base(request, state_data.get('frontend_origin', ''))
            except (signing.BadSignature, signing.SignatureExpired, TypeError):
                frontend_origin = ''

        oauth_error = request.GET.get('error')
        if oauth_error:
            # Example: error=access_denied when user is not in OAuth test users.
            logger.warning(f"[OAuth Callback] Google returned error={oauth_error}")
            return _frontend_settings_redirect(
                request,
                preferred_frontend_base=frontend_origin,
                google_auth='error',
                reason=f'google_{oauth_error}',
            )

        code = request.GET.get('code')

        if not code:
            logger.error("[OAuth Callback] No authorization code received")
            return _frontend_settings_redirect(
                request,
                preferred_frontend_base=frontend_origin,
                google_auth='error',
                reason='no_code',
            )

        # ── 1. Recover user identity from state ──────────────────────
        from users.models import User
        from tenants.models import Organization

        user = None
        org = None

        if state_raw:
            try:
                state_data = signing.loads(
                    state_raw,
                    salt=GOOGLE_OAUTH_STATE_SALT,
                    max_age=GOOGLE_OAUTH_STATE_MAX_AGE_SECONDS,
                )
                user_id = state_data.get('user_id')
                org_id = state_data.get('org_id')
                frontend_origin = _sanitize_frontend_base(request, state_data.get('frontend_origin', ''))
                logger.info(f"[OAuth Callback] State decoded: user_id={user_id}, org_id={org_id}")

                # Explicit tenant-scoped query for security
                try:
                    # Check Organization first so org_not_found works properly
                    org = Organization.objects.get(id=org_id)
                    user = User.objects.get(id=user_id, organization_id=org_id)
                    logger.info(f"[OAuth Callback] Resolved user={user.email}, org={org.name}")
                except Organization.DoesNotExist:
                    logger.warning(f"[OAuth Callback] Organization {org_id} not found")
                    return _frontend_settings_redirect(
                        request,
                        preferred_frontend_base=frontend_origin,
                        google_auth='error',
                        reason='org_not_found',
                    )
                except User.DoesNotExist:
                    logger.warning(f"[OAuth Callback] User {user_id} not found in org {org_id}")
                    return _frontend_settings_redirect(
                        request,
                        preferred_frontend_base=frontend_origin,
                        google_auth='error',
                        reason='user_not_in_org',
                    )
            except (signing.BadSignature, signing.SignatureExpired, KeyError, TypeError) as e:
                logger.warning(f"[OAuth Callback] Failed to parse state parameter: {e}")

        if not user or not org:
            logger.error("[OAuth Callback] No valid user/org from state — cannot link account")
            return _frontend_settings_redirect(
                request,
                preferred_frontend_base=frontend_origin,
                google_auth='error',
                reason='no_user',
            )

        # ── 2. Exchange authorization code for tokens ─────────────────
        try:
            token_response = requests.post('https://oauth2.googleapis.com/token', data={
                'code': code,
                'client_id': settings.GOOGLE_CLIENT_ID,
                'client_secret': settings.GOOGLE_CLIENT_SECRET,
                'redirect_uri': settings.GOOGLE_REDIRECT_URI,
                'grant_type': 'authorization_code',
            }, timeout=10)
        except requests.RequestException as e:
            logger.error(f"[OAuth Callback] Token exchange network error: {e}")
            return _frontend_settings_redirect(
                request,
                preferred_frontend_base=frontend_origin,
                google_auth='error',
                reason='network_error',
            )

        if token_response.status_code != 200:
            logger.error(f"[OAuth Callback] Token exchange failed: {token_response.text}")
            return _frontend_settings_redirect(
                request,
                preferred_frontend_base=frontend_origin,
                google_auth='error',
                reason='token_exchange_failed',
            )

        tokens = token_response.json()
        access_token = tokens.get('access_token')
        refresh_token = tokens.get('refresh_token')

        logger.info(f"[OAuth Callback] Token exchange successful. refresh_token present: {bool(refresh_token)}")

        # ── 3. Get Gmail email address from Google ────────────────────
        try:
            userinfo_response = requests.get(
                'https://www.googleapis.com/oauth2/v2/userinfo',
                headers={'Authorization': f'Bearer {access_token}'},
                timeout=10,
            )
            google_email = userinfo_response.json().get('email')
        except requests.RequestException as e:
            logger.error(f"[OAuth Callback] Userinfo request failed: {e}")
            return _frontend_settings_redirect(
                request,
                preferred_frontend_base=frontend_origin,
                google_auth='error',
                reason='userinfo_failed',
            )

        if not google_email:
            logger.error("[OAuth Callback] Could not retrieve email from Google userinfo")
            return _frontend_settings_redirect(
                request,
                preferred_frontend_base=frontend_origin,
                google_auth='error',
                reason='no_email',
            )

        logger.info(f"[OAuth Callback] Google email resolved: {google_email}")

        # ── 4. Compute token expiry ───────────────────────────────────
        expires_in = tokens.get('expires_in', 3600)
        token_expiry = timezone.now() + timedelta(seconds=expires_in)

        # ── 5. Upsert ConnectedEmailAccount ───────────────────────────
        # CRITICAL: We must bypass TenantManager's auto-scoping since
        # the callback is unauthenticated (no tenant in thread-local).
        # Use the unscoped queryset via ._default_manager or explicit all().
        try:
            unscoped_qs = ConnectedEmailAccount._default_manager.all()

            # Primary ownership key: current user + organization.
            existing = unscoped_qs.filter(
                organization=org,
                connected_by=user,
                provider='GOOGLE',
                email_address__iexact=google_email,
            ).first()

            # Legacy fallback: account existed before per-user ownership was tracked.
            if not existing:
                existing = unscoped_qs.filter(
                    organization=org,
                    connected_by__isnull=True,
                    provider='GOOGLE',
                    email_address__iexact=google_email,
                ).first()

            if existing:
                # Update existing — preserve refresh_token if new one is empty
                existing.access_token = access_token
                if refresh_token:
                    existing.refresh_token = refresh_token
                existing.token_expiry = token_expiry
                existing.provider = 'GOOGLE'
                existing.connected_by = user
                existing.save()
                action = 'updated'
                logger.info(
                    f"[OAuth Callback] Updated sender account: {google_email} "
                    f"for user={user.email} org={org.name}"
                )
            else:
                # Create new
                account = ConnectedEmailAccount(
                    email_address=google_email,
                    organization=org,
                    connected_by=user,
                    access_token=access_token,
                    refresh_token=refresh_token or '',
                    token_expiry=token_expiry,
                    provider='GOOGLE',
                )
                account.save()
                action = 'connected'
                logger.info(
                    f"[OAuth Callback] Created sender account: {google_email} "
                    f"for user={user.email} org={org.name} (id={account.id})"
                )

        except Exception as e:
            logger.exception(f"[OAuth Callback] Failed to save ConnectedEmailAccount: {e}")
            return _frontend_settings_redirect(
                request,
                preferred_frontend_base=frontend_origin,
                google_auth='error',
                reason='db_error',
            )

        # ── 6. Redirect back to frontend ──────────────────────────────
        return _frontend_settings_redirect(
            request,
            preferred_frontend_base=frontend_origin,
            google_auth=action,
            email=google_email,
        )


class ConnectedAccountsListView(APIView):
    """
    GET /api/v1/connected-accounts/
    Returns the list of connected email accounts for the current user's org.

    POST /api/v1/connected-accounts/
    Creates or updates a custom SMTP/IMAP mailbox for the current user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = request.user.organization
        if not org:
            logger.warning(f"[ConnectedAccounts] User {request.user.email} has no organization")
            return Response([], status=status.HTTP_200_OK)

        # Show only sender accounts owned by the current user.
        # Legacy fallback: include pre-ownership records that match current user's email.
        accounts = (
            ConnectedEmailAccount._default_manager
            .filter(organization=org)
            .filter(
                Q(connected_by=request.user)
                | Q(connected_by__isnull=True, email_address__iexact=request.user.email)
            )
            .order_by('-updated_at', '-created_at')
        )
        deduped = []
        seen = set()
        for account in accounts:
            key = (account.email_address.lower(), account.provider)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(account)

        logger.info(f"[ConnectedAccounts] Found {len(deduped)} unique accounts for org {org.name}")

        data = [_serialize_connected_account(a) for a in deduped]
        return Response(data)

    def post(self, request):
        org = request.user.organization
        if not org:
            return Response(
                {'detail': 'Organization context is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CustomMailboxAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        with transaction.atomic():
            account, created = ConnectedEmailAccount._default_manager.update_or_create(
                organization=org,
                connected_by=request.user,
                provider='CUSTOM',
                email_address=payload['email_address'],
                defaults={
                    'access_token': '',
                    'refresh_token': None,
                    'token_expiry': None,
                    'smtp_host': payload['smtp_host'].strip(),
                    'smtp_port': payload['smtp_port'],
                    'smtp_username': payload['smtp_username'],
                    'smtp_password': payload['smtp_password'],
                    'smtp_use_tls': payload.get('smtp_use_tls', True),
                    'smtp_use_ssl': payload.get('smtp_use_ssl', False),
                    'imap_host': payload['imap_host'].strip(),
                    'imap_port': payload['imap_port'],
                    'imap_username': payload['imap_username'],
                    'imap_password': payload['imap_password'],
                    'imap_use_ssl': payload.get('imap_use_ssl', True),
                },
            )

        return Response(
            _serialize_connected_account(account),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ConnectedAccountDetailView(APIView):
    """
    DELETE /api/v1/connected-accounts/<uuid:account_id>/
    Removes a connected email account owned by the current user.
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, account_id):
        account = (
            ConnectedEmailAccount._default_manager
            .filter(
                id=account_id,
                organization=request.user.organization,
            )
            .filter(
                Q(connected_by=request.user)
                | Q(connected_by__isnull=True, email_address__iexact=request.user.email)
            )
            .first()
        )
        if not account:
            return Response({'detail': 'Connected account not found.'}, status=status.HTTP_404_NOT_FOUND)

        account.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

        