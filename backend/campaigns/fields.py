import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


ENCRYPTED_VALUE_PREFIX = "enc::"


def _get_mailbox_credentials_fernet():
    """
    Build a stable Fernet instance for mailbox credential encryption.

    A dedicated environment variable is required outside local/test
    environments so persistent data encryption does not silently depend on the
    general-purpose Django SECRET_KEY.
    """
    secret_source = getattr(settings, "MAILBOX_CREDENTIALS_ENCRYPTION_KEY", "")
    if not secret_source:
        if getattr(settings, "DEBUG", False):
            secret_source = settings.SECRET_KEY
        else:
            raise ImproperlyConfigured(
                "MAILBOX_CREDENTIALS_ENCRYPTION_KEY must be configured before storing mailbox credentials."
            )

    digest = hashlib.sha256(str(secret_source).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _is_encrypted_mailbox_credential(value):
    """Return True only when the value is a valid encrypted mailbox token."""
    if not isinstance(value, str) or not value.startswith(ENCRYPTED_VALUE_PREFIX):
        return False

    token = value[len(ENCRYPTED_VALUE_PREFIX) :]
    try:
        _get_mailbox_credentials_fernet().decrypt(token.encode("utf-8"))
        return True
    except InvalidToken:
        return False


def encrypt_mailbox_credential(value):
    """Encrypt a mailbox credential for at-rest storage."""
    if value in (None, ""):
        return value

    if _is_encrypted_mailbox_credential(value):
        return value

    token = _get_mailbox_credentials_fernet().encrypt(str(value).encode("utf-8"))
    return f"{ENCRYPTED_VALUE_PREFIX}{token.decode('utf-8')}"


def decrypt_mailbox_credential(value):
    """
    Decrypt a mailbox credential when it uses the encrypted storage format.

    Plaintext fallback is preserved temporarily so existing rows can be read and
    migrated forward safely.
    """
    if value in (None, "") or not isinstance(value, str):
        return value

    if not value.startswith(ENCRYPTED_VALUE_PREFIX):
        return value

    token = value[len(ENCRYPTED_VALUE_PREFIX) :]
    try:
        return _get_mailbox_credentials_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return value


class EncryptedTextField(models.TextField):
    """Text field that transparently encrypts/decrypts values with Fernet."""

    description = "Encrypted text"

    def from_db_value(self, value, expression, connection):
        return decrypt_mailbox_credential(value)

    def to_python(self, value):
        value = super().to_python(value)
        return decrypt_mailbox_credential(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return encrypt_mailbox_credential(value)
