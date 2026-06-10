import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _derive_fernet():
    seed = f"{settings.SECRET_KEY}:leadorbit:lead-data".encode("utf-8")
    digest = hashlib.sha256(seed).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class EncryptedTextField(models.TextField):
    def _decrypt(self, value):
        if value in self.empty_values:
            return value

        if not isinstance(value, str):
            return value

        try:
            return _derive_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError, TypeError, AttributeError):
            return value

    def from_db_value(self, value, expression, connection):
        return self._decrypt(value)

    def to_python(self, value):
        if value in self.empty_values or isinstance(value, str):
            return self._decrypt(value)
        return value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in self.empty_values:
            return value
        return _derive_fernet().encrypt(str(value).encode("utf-8")).decode("utf-8")


class EncryptedJSONField(models.TextField):
    def _deserialize(self, value):
        if value in self.empty_values:
            return {}

        if isinstance(value, (dict, list)):
            return value

        if not isinstance(value, str):
            return value

        try:
            decrypted = _derive_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
            return json.loads(decrypted)
        except (InvalidToken, ValueError, TypeError, AttributeError, json.JSONDecodeError):
            try:
                return json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                return {}

    def from_db_value(self, value, expression, connection):
        return self._deserialize(value)

    def to_python(self, value):
        return self._deserialize(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in self.empty_values:
            value = {}
        if not isinstance(value, str):
            value = json.dumps(value)
        return _derive_fernet().encrypt(value.encode("utf-8")).decode("utf-8")
