from django.conf import settings

def is_local_tracking_domain(domain):
    """
    Returns True if the domain should be treated as a local tracking domain.
    """
    if not getattr(settings, 'DEBUG', False):
        return False
    domain = domain.lower()
    return domain.startswith('localhost') or 'localhost' in domain
