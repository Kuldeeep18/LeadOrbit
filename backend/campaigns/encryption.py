import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _get_fernet_key_bytes():
    configured = (getattr(settings, 'FIELD_ENCRYPTION_KEY', '') or '').strip()
    if configured:
        return configured.encode('utf-8')
    if settings.DEBUG:
        return base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    raise ImproperlyConfigured(
        'FIELD_ENCRYPTION_KEY must be set in production. '
        'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
    )


def _get_fernet():
    return Fernet(_get_fernet_key_bytes())


def encrypt_value(value):
    if value in (None, ''):
        return value
    return _get_fernet().encrypt(str(value).encode('utf-8')).decode('utf-8')


def decrypt_value(value):
    if value in (None, ''):
        return value
    try:
        return _get_fernet().decrypt(str(value).encode('utf-8')).decode('utf-8')
    except InvalidToken:
        # Support legacy plaintext values until the next save re-encrypts them.
        return value


def is_encrypted(value):
    if value in (None, ''):
        return False
    try:
        _get_fernet().decrypt(str(value).encode('utf-8'))
        return True
    except InvalidToken:
        return False
