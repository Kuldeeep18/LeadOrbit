"""Fernet-based helpers for encrypting sensitive field values at rest."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _get_fernet_key_bytes():
    """
    Resolve the Fernet key used for field encryption.

    Returns:
        bytes: URL-safe base64-encoded 32-byte Fernet key.

    Raises:
        ImproperlyConfigured: If FIELD_ENCRYPTION_KEY is unset outside DEBUG mode.
    """
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
    """
    Return a configured Fernet instance for encrypt/decrypt operations.

    Returns:
        Fernet: Symmetric encryptor bound to the project encryption key.
    """
    return Fernet(_get_fernet_key_bytes())


def encrypt_value(value):
    """
    Encrypt a plaintext string for database storage.

    Args:
        value: Plaintext value to encrypt. None and empty strings pass through.

    Returns:
        str | None: Fernet-encrypted ciphertext, or the original empty value.
    """
    if value in (None, ''):
        return value
    return _get_fernet().encrypt(str(value).encode('utf-8')).decode('utf-8')


def decrypt_value(value):
    """
    Decrypt a Fernet-encrypted string from the database.

    Args:
        value: Encrypted ciphertext, or None/empty string.

    Returns:
        str | None: Decrypted plaintext, the original empty value, or legacy
        plaintext when the value is not valid Fernet ciphertext.
    """
    if value in (None, ''):
        return value
    try:
        return _get_fernet().decrypt(str(value).encode('utf-8')).decode('utf-8')
    except InvalidToken:
        # Support legacy plaintext values until the next save re-encrypts them.
        return value


def is_encrypted(value):
    """
    Check whether a stored value is Fernet-encrypted ciphertext.

    Args:
        value: Stored database value to inspect.

    Returns:
        bool: True when the value decrypts successfully with the project key.
    """
    if value in (None, ''):
        return False
    try:
        _get_fernet().decrypt(str(value).encode('utf-8'))
        return True
    except InvalidToken:
        return False
