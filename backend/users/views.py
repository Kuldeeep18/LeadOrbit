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

from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.core.mail import send_mail
from django.conf import settings
from users.throttling import LoginRateThrottle
import pyotp
import jwt

class AuthViewSet(viewsets.GenericViewSet):
    @action(detail=False, methods=['post'], permission_classes=[AllowAny], throttle_classes=[LoginRateThrottle])
    def register(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            
            # Generate email verification token and UID
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            
            # Build verification link
            frontend_url = getattr(settings, 'FRONTEND_BASE_URL', '') or 'http://localhost:3000'
            verification_link = f"{frontend_url}/verify-email?uid={uid}&token={token}"
            
            # Send verification email
            send_mail(
                'Verify Your LeadOrbit Email',
                f'Please verify your email by clicking the following link: {verification_link}',
                'noreply@leadorbit.com',
                [user.email],
                fail_silently=False,
            )
            
            return Response({
                'user': UserSerializer(user).data,
                'message': 'Registration successful. Please check your email to verify your account.'
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], permission_classes=[AllowAny], url_path='verify-email', throttle_classes=[LoginRateThrottle])
    def verify_email(self, request):
        uidb64 = request.data.get('uid')
        token = request.data.get('token')
        if not uidb64 or not token:
            return Response({'error': 'Missing uid or token.'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            from django.utils.http import urlsafe_base64_decode
            from django.utils.encoding import force_str
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None
            
        if user is not None and default_token_generator.check_token(user, token):
            user.is_email_verified = True
            user.save(update_fields=['is_email_verified'])
            return Response({'message': 'Email successfully verified.'}, status=status.HTTP_200_OK)
        return Response({'error': 'Invalid or expired verification token.'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated], url_path='enable-mfa')
    def enable_mfa(self, request):
        user = request.user
        if user.mfa_enabled:
            return Response({'detail': 'MFA is already enabled.'}, status=status.HTTP_400_BAD_REQUEST)
        
        secret = pyotp.random_base32()
        user.mfa_secret = secret
        user.save(update_fields=['mfa_secret'])
        
        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name="LeadOrbit")
        return Response({
            'secret': secret,
            'provisioning_uri': provisioning_uri
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated], url_path='confirm-mfa')
    def confirm_mfa(self, request):
        user = request.user
        code = request.data.get('code')
        if not code:
            return Response({'error': 'Verification code is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not user.mfa_secret:
            return Response({'error': 'MFA setup has not been initiated.'}, status=status.HTTP_400_BAD_REQUEST)
            
        totp = pyotp.TOTP(user.mfa_secret)
        if totp.verify(code):
            user.mfa_enabled = True
            user.save(update_fields=['mfa_enabled'])
            return Response({'message': 'MFA enabled successfully.'}, status=status.HTTP_200_OK)
        return Response({'error': 'Invalid verification code.'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], permission_classes=[AllowAny], url_path='verify-mfa', throttle_classes=[LoginRateThrottle])
    def verify_mfa(self, request):
        mfa_token = request.data.get('mfa_token')
        code = request.data.get('code')
        if not mfa_token or not code:
            return Response({'error': 'mfa_token and verification code are required.'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            payload = jwt.decode(mfa_token, settings.SECRET_KEY, algorithms=['HS256'])
            if not payload.get('mfa_pending'):
                raise jwt.InvalidTokenError()
            user_id = payload.get('user_id')
            user = User.objects.get(pk=user_id)
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, User.DoesNotExist):
            return Response({'error': 'Invalid or expired MFA token.'}, status=status.HTTP_400_BAD_REQUEST)
            
        totp = pyotp.TOTP(user.mfa_secret)
        if totp.verify(code):
            refresh = RefreshToken.for_user(user)
            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }, status=status.HTTP_200_OK)
        return Response({'error': 'Invalid verification code.'}, status=status.HTTP_400_BAD_REQUEST)

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
