import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


ENCRYPTED_VALUE_PREFIX = "enc::"


def _get_mailbox_credentials_fernet():
    """
    Build a stable Fernet instance for mailbox credential encryption.

    A dedicated environment variable can override the project SECRET_KEY, but
    SECRET_KEY remains a safe fallback so local/dev environments still work.
    """
    secret_source = (
        getattr(settings, "MAILBOX_CREDENTIALS_ENCRYPTION_KEY", "") or settings.SECRET_KEY
    )
    digest = hashlib.sha256(str(secret_source).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_mailbox_credential(value):
    """Encrypt a mailbox credential for at-rest storage."""
    if value in (None, ""):
        return value

    if isinstance(value, str) and value.startswith(ENCRYPTED_VALUE_PREFIX):
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
