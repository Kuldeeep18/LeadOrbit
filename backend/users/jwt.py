from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class CustomTokenObtainSerializer(TokenObtainPairSerializer):
    username_field = 'email'

    def validate(self, attrs):
        data = super().validate(attrs)
        if not getattr(self.user, 'is_email_verified', False):
            raise serializers.ValidationError({'detail': 'Please verify your email before logging in.'})
        return data
