from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import User


class CustomTokenObtainSerializer(TokenObtainPairSerializer):
    username_field = 'email'

    def validate(self, attrs):
        # Signup rejects emails that differ only by case, so accept any casing at login.
        email = (attrs.get(self.username_field) or '').strip()
        if email and not User.objects.filter(email=email).exists():
            stored = User.objects.filter(email__iexact=email).values_list('email', flat=True).first()
            if stored:
                attrs[self.username_field] = stored
        return super().validate(attrs)
