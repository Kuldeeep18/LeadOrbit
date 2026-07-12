from rest_framework.throttling import SimpleRateThrottle

class LoginRateThrottle(SimpleRateThrottle):
    scope = 'login'

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)

        username = None
        if hasattr(request, 'data') and isinstance(request.data, dict):
            username = request.data.get('email')

        if username:
            return self.cache_format % {
                'scope': self.scope,
                'ident': f"{ident}_{username}"
            }
        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }
