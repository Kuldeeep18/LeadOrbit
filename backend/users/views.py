from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import User
from .serializers import UserSerializer
from .permissions import IsOrgAdmin

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return User.objects.filter(organization=self.request.user.organization)

    @action(detail=False, methods=['delete'], permission_classes=[IsOrgAdmin], url_path='delete-organization')
    def delete_organization(self, request):
        org = request.user.organization
        if org:
            org.delete()
            return Response({'message': 'Organization successfully deleted.'}, status=status.HTTP_200_OK)
        return Response({'error': 'No organization found.'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], permission_classes=[IsOrgAdmin], url_path='invite')
    def invite_user(self, request):
        email = request.data.get('email')
        role = request.data.get('role', 'USER')
        if not email:
            return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)
        if role not in dict(User.ROLE_CHOICES):
            return Response({'error': 'Invalid role'}, status=status.HTTP_400_BAD_REQUEST)
        org = request.user.organization
        if User.objects.filter(email=email, organization=org).exists():
            return Response({'error': 'User already in organization'}, status=status.HTTP_400_BAD_REQUEST)
        user = User.objects.create_user(email=email, organization=org, role=role, is_active=False)
        return Response({'message': f'Invitation sent to {email} with role {role}'}, status=status.HTTP_201_CREATED)