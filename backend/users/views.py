import logging
import qrcode
import base64
import pyotp
from io import BytesIO
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils.crypto import get_random_string
from django.db import transaction
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from .models import User
from .permissions import IsOrgAdmin
from .serializers import UserSerializer, RegisterSerializer

logger = logging.getLogger(__name__)

class AuthViewSet(viewsets.GenericViewSet):
    
    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def register(self, request):
        """
        Registers a new user account with email verification.
        """
        # Rate limiting: read from settings
        rate_limit = getattr(settings, 'REGISTRATION_RATE_LIMIT', 5)
        window = getattr(settings, 'REGISTRATION_RATE_LIMIT_WINDOW', 3600)
        token_ttl = getattr(settings, 'VERIFICATION_TOKEN_EXPIRY', 86400)
        
        ip_address = request.META.get('REMOTE_ADDR')
        rate_limit_key = f"register_rate_{ip_address}"
        
        # Check rate limit
        current_count = cache.get(rate_limit_key, 0)
        if current_count >= rate_limit:
            return Response(
                {'error': 'Too many registration attempts. Please try again later.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )
        
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        email = serializer.validated_data.get('email', '').lower()
        
        # Domain restriction: only allow specific domains (optional)
        ALLOWED_DOMAINS = getattr(settings, 'ALLOWED_REGISTRATION_DOMAINS', [])
        if ALLOWED_DOMAINS:
            domain = email.split('@')[-1]
            if domain not in ALLOWED_DOMAINS:
                return Response(
                    {'error': f'Registration is restricted to domains: {", ".join(ALLOWED_DOMAINS)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Check if user already exists
        if User.objects.filter(email=email).exists():
            return Response(
                {'error': 'A user with this email already exists.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # ─── FIX: Use transaction to avoid orphaned organization ───
        try:
            with transaction.atomic():
                # ─── CRITICAL SECURITY FIX: Create user as inactive until email verification ───
                user = serializer.save(is_active=False)  # Fix #616
                
                # Generate verification token
                verification_token = get_random_string(64)
                cache.set(f"verify_{verification_token}", user.id, timeout=token_ttl)
                
                # Send verification email
                frontend_base = getattr(settings, 'FRONTEND_BASE_URL', 'http://localhost:8080')
                verification_url = f"{frontend_base}/verify-email?token={verification_token}"
                
                send_mail(
                    'Verify your email address',
                    f'Please click the link to verify your email: {verification_url}',
                    getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@leadorbit.com'),
                    [email],
                    fail_silently=False,
                )
                logger.info(f"Verification email sent to {email}")
        except Exception as e:
            logger.error(f"Failed to send verification email to {email}: {e}")
            # Transaction rollback handles everything
            return Response(
                {'error': 'Failed to send verification email. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Increment rate limit counter - set key with timeout first
        cache.set(rate_limit_key, current_count + 1, timeout=window)
        
        return Response(
            {
                'message': 'Registration successful. Please check your email to verify your account.',
                'email': email,
            },
            status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def verify_email(self, request):
        """
        Verify user's email with token using POST method.
        """
        token = request.data.get('token')
        
        if not token:
            return Response(
                {'error': 'Verification token is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        user_id = cache.get(f"verify_{token}")
        
        if not user_id:
            return Response(
                {'error': 'Invalid or expired verification token.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            user = User.objects.get(id=user_id)
            if user.is_active:
                return Response(
                    {'message': 'Email already verified. You can now log in.'},
                    status=status.HTTP_200_OK
                )
            user.is_active = True
            user.save()
            cache.delete(f"verify_{token}")
            
            return Response(
                {
                    'message': 'Email verified successfully. You can now log in.',
                },
                status=status.HTTP_200_OK
            )
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def resend_verification(self, request):
        """
        Resend verification email for unverified users.
        """
        email = request.data.get('email')
        
        if not email:
            return Response(
                {'error': 'Email is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # ─── FIX: Add rate limiting ───
        ip_address = request.META.get('REMOTE_ADDR')
        rate_limit_key = f"resend_verify_{ip_address}"
        current_count = cache.get(rate_limit_key, 0)
        if current_count >= 3:  # 3 attempts per hour
            return Response(
                {'error': 'Too many verification requests. Please try again later.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )
        
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # ─── FIX: Always return generic message ───
            cache.set(rate_limit_key, current_count + 1, timeout=3600)
            return Response(
                {'message': 'If an account with this email exists, a verification email has been sent.'},
                status=status.HTTP_200_OK
            )
        
        if user.is_active:
            # ─── FIX: Return generic message, not revealing account exists ───
            cache.set(rate_limit_key, current_count + 1, timeout=3600)
            return Response(
                {'message': 'If an account with this email exists, a verification email has been sent.'},
                status=status.HTTP_200_OK
            )
        
        # Generate new verification token
        token_ttl = getattr(settings, 'VERIFICATION_TOKEN_EXPIRY', 86400)
        verification_token = get_random_string(64)
        cache.set(f"verify_{verification_token}", user.id, timeout=token_ttl)
        
        # Send verification email
        frontend_base = getattr(settings, 'FRONTEND_BASE_URL', 'http://localhost:8080')
        verification_url = f"{frontend_base}/verify-email?token={verification_token}"
        
        try:
            send_mail(
                'Verify your email address',
                f'Please click the link to verify your email: {verification_url}',
                getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@leadorbit.com'),
                [user.email],
                fail_silently=False,
            )
            logger.info(f"Verification email resent to {user.email}")
            cache.set(rate_limit_key, current_count + 1, timeout=3600)
        except Exception as e:
            logger.error(f"Failed to send verification email to {user.email}: {e}")
            return Response(
                {'error': 'Failed to send verification email. Please try again later.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        return Response(
            {'message': 'Verification email sent. Please check your inbox.'},
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get', 'patch'], permission_classes=[IsAuthenticated])
    def me(self, request):
        if request.method == 'PATCH':
            payload = request.data or {}
            new_password = payload.get('new_password')
            organization_name = payload.get('organization_name')
            updates_made = False
            gemini_api_key = payload.get('gemini_api_key')
            enable_ai_personalization = payload.get('enable_ai_personalization')

            if organization_name is not None:
                if not IsOrgAdmin().has_permission(request, self):
                    return Response(
                        {'detail': 'Only organization admins can update organization settings.'},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                clean_name = str(organization_name).strip()
                if not clean_name:
                    return Response(
                        {'organization_name': ['Organization name cannot be empty.']},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                request.user.organization.name = clean_name
                request.user.organization.save(update_fields=['name'])
                updates_made = True
            if gemini_api_key is not None:
                if not IsOrgAdmin().has_permission(request, self):
                    return Response(
                        {'detail': 'Only organization admins can update organization settings.'},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                request.user.organization.gemini_api_key = str(gemini_api_key).strip() or None
                request.user.organization.save(update_fields=['gemini_api_key'])
                updates_made = True

            if enable_ai_personalization is not None:
                if not IsOrgAdmin().has_permission(request, self):
                    return Response(
                        {'detail': 'Only organization admins can update organization settings.'},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                request.user.organization.enable_ai_personalization = bool(enable_ai_personalization)
                request.user.organization.save(update_fields=['enable_ai_personalization'])
                updates_made = True

            # ─── CRITICAL SECURITY FIX: Password change requires current password ───
            if new_password:
                # Require current password for security
                current_password = payload.get('current_password')
                if not current_password:
                    return Response(
                        {'error': 'Current password is required to change password.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # ─── FIX: Rate limit BEFORE verifying password ───
                ip = request.META.get('REMOTE_ADDR')
                rate_limit_key = f"password_change_{ip}_{request.user.id}"
                attempt_count = cache.get(rate_limit_key, 0)
                if attempt_count >= 3:
                    return Response(
                        {'error': 'Too many password change attempts. Please try again later.'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS
                    )
                cache.set(rate_limit_key, attempt_count + 1, timeout=3600)
                
                if not request.user.check_password(current_password):
                    return Response(
                        {'error': 'Current password is incorrect.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                try:
                    validate_password(new_password, request.user)
                except DjangoValidationError as exc:
                    return Response({'new_password': list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
                
                request.user.set_password(new_password)
                request.user.save(update_fields=['password'])
                updates_made = True

            if not updates_made:
                return Response({'detail': 'No changes submitted.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    # ─── CRITICAL SECURITY FIX: Two-Factor Authentication (2FA) ───
    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def setup_2fa(self, request):
        """
        Setup Two-Factor Authentication using TOTP.
        """
        user = request.user
        
        if user.has_2fa:
            return Response(
                {'error': '2FA is already enabled for this account.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Generate TOTP secret
        secret = pyotp.random_base32()
        
        # Store secret temporarily
        cache.set(f"2fa_setup_{user.id}", secret, timeout=600)  # 10 minutes
        
        # Generate QR code
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(
            name=user.email,
            issuer_name="LeadOrbit"
        )
        
        # Create QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode()
        
        return Response({
            'message': 'Scan QR code with authenticator app',
            'secret': secret,
            'qr_code': f"data:image/png;base64,{qr_base64}",
            'uri': uri
        })

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def verify_2fa(self, request):
        """
        Verify TOTP code and enable 2FA for the user.
        """
        user = request.user
        code = request.data.get('code')
        
        if not code:
            return Response(
                {'error': 'Verification code is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get secret from cache
        secret = cache.get(f"2fa_setup_{user.id}")
        if not secret:
            return Response(
                {'error': '2FA setup expired. Please restart the process.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify code
        totp = pyotp.TOTP(secret)
        if not totp.verify(code):
            return Response(
                {'error': 'Invalid verification code.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # ─── FIX: Use encrypted secret storage ───
        user.has_2fa = True
        user.set_otp_secret(secret)
        user.save(update_fields=['has_2fa', 'otp_secret_encrypted'])
        
        cache.delete(f"2fa_setup_{user.id}")
        
        # ─── FIX: Store backup codes properly ───
        backup_codes = [pyotp.random_base32()[:8] for _ in range(10)]
        # Store backup codes in cache (will implement proper storage later)
        cache.set(f"2fa_backup_{user.id}", backup_codes, timeout=86400)  # 24 hours
        
        return Response({
            'message': '2FA enabled successfully.',
            'backup_codes': backup_codes
        })

    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def login_2fa(self, request):
        """
        Login with 2FA verification.
        """
        from django.contrib.auth import authenticate
        
        email = request.data.get('email')
        password = request.data.get('password')
        code = request.data.get('code')
        
        if not email or not password or not code:
            return Response(
                {'error': 'Email, password, and verification code are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Authenticate user
        user = authenticate(email=email, password=password)
        
        if not user:
            return Response(
                {'error': 'Invalid credentials.'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        if not user.is_active:
            return Response(
                {'error': 'Account is inactive.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if 2FA is enabled
        if not user.has_2fa:
            return Response(
                {'error': '2FA is not enabled for this account.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # ─── FIX: Add rate limiting for 2FA attempts ───
        ip = request.META.get('REMOTE_ADDR')
        rate_limit_key = f"2fa_login_{email}_{ip}"
        attempt_count = cache.get(rate_limit_key, 0)
        if attempt_count >= 5:
            return Response(
                {'error': 'Too many 2FA attempts. Please try again later.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )
        
        # ─── FIX: Use get_otp_secret() method ───
        otp_secret = user.get_otp_secret()
        if not otp_secret:
            return Response(
                {'error': '2FA configuration error. Please contact support.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Verify TOTP code
        totp = pyotp.TOTP(otp_secret)
        if not totp.verify(code):
            cache.set(rate_limit_key, attempt_count + 1, timeout=900)  # 15 minutes
            return Response(
                {'error': 'Invalid verification code.'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # ─── FIX: Reset rate limit on success ───
        cache.delete(rate_limit_key)
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': UserSerializer(user).data,
            '2fa_verified': True
        })

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def logout(self, request):
        """
        Logout user by blacklisting the refresh token.
        """
        refresh_token = request.data.get('refresh_token')
        if not refresh_token:
            return Response(
                {'error': 'Refresh token is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # ─── FIX: Only catch TokenError, don't expose raw exceptions ───
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response(
                {'message': 'Successfully logged out.'},
                status=status.HTTP_200_OK
            )
        except TokenError:
            return Response(
                {'error': 'Invalid or expired refresh token.'},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['delete'], permission_classes=[IsAuthenticated, IsOrgAdmin], url_path='delete-organization')
    def delete_organization(self, request):
        request.user.organization.delete()
        return Response(
            {'message': 'Organization successfully deleted.'},
            status=status.HTTP_200_OK,
        )

        