from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import User
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

            if organization_name is not None:
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
                request.user.organization.gemini_api_key = str(gemini_api_key).strip() or None
                request.user.organization.save(update_fields=['gemini_api_key'])
                updates_made = True

            if enable_ai_personalization is not None:
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

    @action(detail=False, methods=['delete'], permission_classes=[IsAuthenticated], url_path='delete-organization')
    def delete_organization(self, request):
        request.user.organization.delete()
        return Response(
            {'message': 'Organization successfully deleted.'},
            status=status.HTTP_200_OK,
        )
