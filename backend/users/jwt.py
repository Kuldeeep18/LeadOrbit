from django.core.cache import cache
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework import serializers


class CustomTokenObtainSerializer(TokenObtainPairSerializer):
    username_field = 'email'
    
    def validate(self, attrs):
        email = attrs.get('email')
        ip = self.context['request'].META.get('REMOTE_ADDR')
        
        # ─── Check if account is locked ──────────────────────────────
        lock_key = f"account_locked_{email}"
        if cache.get(lock_key):
            raise serializers.ValidationError(
                'Account temporarily locked. Reset your password or try again later.'
            )
        
        try:
            # ─── Attempt validation ────────────────────────────────────
            response = super().validate(attrs)
            
            # Success - reset failed attempts
            attempts_key = f"login_attempts_email_{email}"
            cache.delete(attempts_key)
            
            ip_key = f"login_attempts_ip_{ip}"
            cache.delete(ip_key)
            
            return response
            
        except serializers.ValidationError as e:
            # ─── Failed login - track attempt ─────────────────────────
            
            # Track IP attempts
            ip_key = f"login_attempts_ip_{ip}"
            ip_attempts = cache.get(ip_key, 0) + 1
            cache.set(ip_key, ip_attempts, timeout=3600)
            
            # Track email attempts
            attempts_key = f"login_attempts_email_{email}"
            attempts = cache.get(attempts_key, 0) + 1
            cache.set(attempts_key, attempts, timeout=3600)
            
            # Lock account after 5 failed attempts
            if attempts >= 5:
                lock_key = f"account_locked_{email}"
                cache.set(lock_key, True, timeout=900)  # 15 minutes
                raise serializers.ValidationError(
                    'Account locked due to too many failed login attempts. Please try again later.'
                )
            
            # Re-raise the original error
            raise

        