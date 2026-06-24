import logging

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import User
from .permissions import IsOrgAdmin
from .serializers import UserSerializer, RegisterSerializer

logger = logging.getLogger(__name__)

EMAIL_VERIFICATION_SALT = 'users.email-verification'


def generate_email_verification_token(user):
    return signing.dumps(str(user.pk), salt=EMAIL_VERIFICATION_SALT)


def build_email_verification_url(token):
    frontend_base = (getattr(settings, 'FRONTEND_BASE_URL', '') or settings.BACKEND_BASE_URL).rstrip('/')
    return f'{frontend_base}/email-verification.html?token={token}'


def send_verification_email(user):
    token = generate_email_verification_token(user)
    verification_url = build_email_verification_url(token)
    subject = 'Verify your LeadOrbit email'
    message = (
        f'Hi {user.email},\n\n'
        'Please verify your email address to finish setting up your LeadOrbit account.\n'
        f'Open this link to verify your account: {verification_url}\n\n'
        'If you did not create this account, you can ignore this email.'
    )
    try:
        send_mail(subject, message, getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@leadorbit.local'), [user.email], fail_silently=False)
    except Exception:
        logger.exception('Failed to send verification email for user %s', user.email)
    return verification_url

class AuthViewSet(viewsets.GenericViewSet):
    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def register(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            verification_url = send_verification_email(user)
            return Response({
                'user': UserSerializer(user).data,
                'message': 'Verification email sent. Please check your inbox to activate your account.',
                'verification_url': verification_url,
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'], permission_classes=[AllowAny], url_path=r'verify-email/(?P<token>[^/]+)')
    def verify_email(self, request, token=None):
        try:
            user_id = signing.loads(token, salt=EMAIL_VERIFICATION_SALT, max_age=60 * 60 * 24 * 7)
        except signing.BadSignature:
            return Response({'detail': 'Verification link is invalid or has expired.'}, status=status.HTTP_400_BAD_REQUEST)

        user = get_object_or_404(User, pk=user_id)
        if not user.is_email_verified:
            user.is_email_verified = True
            user.save(update_fields=['is_email_verified'])

        return Response({
            'detail': 'Email verified successfully.',
            'user': UserSerializer(user).data,
        })

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
