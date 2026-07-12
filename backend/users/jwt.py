import jwt
from datetime import datetime, timedelta, timezone
from django.conf import settings
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class CustomTokenObtainSerializer(TokenObtainPairSerializer):
    username_field = 'email'

    def validate(self, attrs):
        # We need to authenticate first. SimpleJWT validation handles active user check.
        data = super().validate(attrs)

        # Enforce email verification
        if not self.user.is_email_verified:
            raise serializers.ValidationError('Email not verified. Please verify your email first.')

        # Enforce MFA/2FA check
        if self.user.mfa_enabled:
            temp_token = jwt.encode(
                {
                    'user_id': str(self.user.id),
                    'mfa_pending': True,
                    'exp': datetime.now(timezone.utc) + timedelta(minutes=5)
                },
                settings.SECRET_KEY,
                algorithm='HS256'
            )
            return {
                'mfa_required': True,
                'mfa_token': temp_token,
                'email': self.user.email
            }

        return data
