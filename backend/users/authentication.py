from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed


class EmailVerifiedJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not getattr(user, 'is_email_verified', False):
            raise AuthenticationFailed('Please verify your email before accessing the API.')
        return user
