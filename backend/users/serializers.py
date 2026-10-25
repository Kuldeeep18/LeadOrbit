from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from .models import User
from tenants.models import Organization

class OrganizationSerializer(serializers.ModelSerializer):
    # The Gemini key is a secret: members only learn whether one is saved.
    has_gemini_api_key = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ['id', 'name', 'billing_plan', 'created_at', 'enable_ai_personalization', 'has_gemini_api_key']

    def get_has_gemini_api_key(self, obj):
        return bool(obj.gemini_api_key)

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

    def validate(self, attrs):
        candidate = User(email=attrs['email'])
        try:
            validate_password(attrs['password'], candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': list(exc.messages)})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        org = Organization.objects.create(name=validated_data['organization_name'])
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            organization=org,
            role='ADMIN',  # First user in org is admin
        )
        return user
