import logging
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils.crypto import get_random_string
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import User
from .permissions import IsOrgAdmin
from .serializers import UserSerializer, RegisterSerializer
from rest_framework_simplejwt.tokens import RefreshToken

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
        
        # Create user as inactive until email verification
        user = serializer.save(is_active=False)
        
        # Generate verification token
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
                [email],
                fail_silently=False,
            )
            logger.info(f"Verification email sent to {email}")
        except Exception as e:
            logger.error(f"Failed to send verification email to {email}: {e}")
            # Delete the created user since verification email failed
            user.delete()
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
        
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Don't reveal if user exists for security
            return Response(
                {'message': 'If an account with this email exists, a verification email has been sent.'},
                status=status.HTTP_200_OK
            )
        
        if user.is_active:
            return Response(
                {'message': 'Email already verified. You can log in.'},
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

            if new_password:
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

    @action(detail=False, methods=['delete'], permission_classes=[IsAuthenticated, IsOrgAdmin], url_path='delete-organization')
    def delete_organization(self, request):
        request.user.organization.delete()
        return Response(
            {'message': 'Organization successfully deleted.'},
            status=status.HTTP_200_OK,
        )

        