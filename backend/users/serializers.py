from rest_framework import serializers
from .models import User
from tenants.models import Organization

class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = '__all__'

class UserSerializer(serializers.ModelSerializer):
    organization = OrganizationSerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'first_name',
            'last_name',
            'avatar_url',
            'role',
            'organization',
            'is_active',
        ]

class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    organization_name = serializers.CharField()
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    avatar_url = serializers.URLField(required=False, allow_blank=True)

    def create(self, validated_data):
        org = Organization.objects.create(name=validated_data['organization_name'])
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            organization=org,
            role='ADMIN',  # First user in org is admin
            first_name=validated_data.get('first_name', '').strip() or None,
            last_name=validated_data.get('last_name', '').strip() or None,
            avatar_url=validated_data.get('avatar_url', '').strip() or None,
        )
        return user
