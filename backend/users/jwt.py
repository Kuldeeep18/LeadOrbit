from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class CustomTokenObtainSerializer(TokenObtainPairSerializer):
    username_field = 'email'

    def validate(self, attrs):
        # Strip stray whitespace from copy-pasted emails (Issue #474).
        # Password is intentionally left untouched.
        if isinstance(attrs.get(self.username_field), str):
            attrs[self.username_field] = attrs[self.username_field].strip()
        return super().validate(attrs)
    