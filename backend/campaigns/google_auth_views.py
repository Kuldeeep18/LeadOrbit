"""
Google OAuth2 views for connecting Gmail accounts.

Architecture notes:
- The login view passes the logged-in user's ID via the `state` param so the
  anonymous callback can link the account to the correct user + org.
- We bypass TenantManager's auto-scoping by using _default_manager on the
  base model and explicit org assignment, since the callback request is
  unauthenticated (Google redirect).
"""
import json
import logging
import requests
from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect
from django.utils import timezone
from django.db.models import Q
from datetime import timedelta

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated

from .models import ConnectedEmailAccount

logger = logging.getLogger(__name__)


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
                    user = User.objects.all().get(id=user_id)
                    logger.info(f"[OAuth Login] Resolved user {user.email} from query token")
                except Exception as e:
                    logger.error(f"[OAuth Login] Failed to decode token from query: {e}")

        if not user:
            logger.error("[OAuth Login] No valid user found — cannot initiate OAuth")
            return redirect('http://localhost:3000/settings.html?google_auth=error&reason=not_logged_in')

        # Encode user identity in state so callback can link to correct user
        state_data = json.dumps({
            'user_id': str(user.id),
            'org_id': str(user.organization_id),
        })

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
        oauth_error = request.GET.get('error')
        if oauth_error:
            # Example: error=access_denied when user is not in OAuth test users.
            logger.warning(f"[OAuth Callback] Google returned error={oauth_error}")
            return redirect(f'http://localhost:3000/settings.html?google_auth=error&reason=google_{oauth_error}')

        code = request.GET.get('code')
        state_raw = request.GET.get('state')

        if not code:
            logger.error("[OAuth Callback] No authorization code received")
            return redirect('http://localhost:3000/settings.html?google_auth=error&reason=no_code')

        # ── 1. Recover user identity from state ──────────────────────
        from users.models import User
        from tenants.models import Organization

        user = None
        org = None

        if state_raw:
            try:
                state_data = json.loads(state_raw)
                user_id = state_data.get('user_id')
                org_id = state_data.get('org_id')
                logger.info(f"[OAuth Callback] State decoded: user_id={user_id}, org_id={org_id}")

                # Use .objects.all() on base manager to bypass tenant scoping
                try:
                    user = User.objects.all().get(id=user_id)
                    org = Organization.objects.get(id=org_id)
                    logger.info(f"[OAuth Callback] Resolved user={user.email}, org={org.name}")
                except (User.DoesNotExist, Organization.DoesNotExist) as e:
                    logger.warning(f"[OAuth Callback] Could not find user/org from state: {e}")
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(f"[OAuth Callback] Failed to parse state parameter: {e}")

        if not user or not org:
            logger.error("[OAuth Callback] No valid user/org from state — cannot link account")
            return redirect('http://localhost:3000/settings.html?google_auth=error&reason=no_user')

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
            return redirect('http://localhost:3000/settings.html?google_auth=error&reason=network_error')

        if token_response.status_code != 200:
            logger.error(f"[OAuth Callback] Token exchange failed: {token_response.text}")
            return redirect('http://localhost:3000/settings.html?google_auth=error&reason=token_exchange_failed')

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
            return redirect('http://localhost:3000/settings.html?google_auth=error&reason=userinfo_failed')

        if not google_email:
            logger.error("[OAuth Callback] Could not retrieve email from Google userinfo")
            return redirect('http://localhost:3000/settings.html?google_auth=error&reason=no_email')

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
            return redirect(f'http://localhost:3000/settings.html?google_auth=error&reason=db_error')

        # ── 6. Redirect back to frontend ──────────────────────────────
        return redirect(f'http://localhost:3000/settings.html?google_auth={action}&email={google_email}')


class ConnectedAccountsListView(APIView):
    """
    GET /api/v1/connected-accounts/
    Returns the list of connected email accounts for the current user's org.
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

        data = [
            {
                'id': str(a.id),
                'email': a.email_address,
                'provider': a.provider,
                'connected': True,
            }
            for a in deduped
        ]
        return Response(data)
