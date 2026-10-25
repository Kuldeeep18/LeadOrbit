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

class AuthViewSet(viewsets.GenericViewSet):
    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def register(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)
            return Response({
                'user': UserSerializer(user).data,
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get', 'patch'], permission_classes=[IsAuthenticated])
    def me(self, request):
        if request.method == 'PATCH':
            payload = request.data or {}
            new_password = payload.get('new_password')
            organization_name = payload.get('organization_name')
            updates_made = False
            gemini_api_key = payload.get('gemini_api_key')
            enable_ai_personalization = payload.get('enable_ai_personalization')
            organization = request.user.organization
            org_fields = []

            # Validate everything before saving anything, so a rejected request changes nothing.
            if any(value is not None for value in (organization_name, gemini_api_key, enable_ai_personalization)):
                if not IsOrgAdmin().has_permission(request, self):
                    return Response(
                        {'detail': 'Only organization admins can update organization settings.'},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            if organization_name is not None:
                clean_name = str(organization_name).strip()
                if not clean_name:
                    return Response(
                        {'organization_name': ['Organization name cannot be empty.']},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                organization.name = clean_name
                org_fields.append('name')
            if gemini_api_key is not None:
                # An empty string removes the saved key.
                organization.gemini_api_key = str(gemini_api_key).strip() or None
                org_fields.append('gemini_api_key')
            if enable_ai_personalization is not None:
                organization.enable_ai_personalization = bool(enable_ai_personalization)
                org_fields.append('enable_ai_personalization')

            if new_password:
                # A stolen access token alone must not be enough to take over the account.
                if not request.user.check_password(payload.get('current_password') or ''):
                    return Response(
                        {'current_password': ['Current password is incorrect.']},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                try:
                    validate_password(new_password, request.user)
                except DjangoValidationError as exc:
                    return Response({'new_password': list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

            if org_fields:
                organization.save(update_fields=org_fields)
                updates_made = True
            if new_password:
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
