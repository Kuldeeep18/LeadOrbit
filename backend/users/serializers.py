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
        fields = ['id', 'email', 'role', 'organization', 'is_active']

class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    organization_name = serializers.CharField()
    first_name = serializers.CharField(required=False)
    last_name = serializers.CharField(required=False)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def create(self, validated_data):
        org = Organization.objects.create(name=validated_data['organization_name'])
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            organization=org,
            role='ADMIN',  # First user in org is admin
        )
        return user
