from django.db import models

from .encryption import decrypt_value, encrypt_value


class EncryptedTextField(models.TextField):
    """TextField that transparently encrypts values at rest using Fernet."""

    description = 'Encrypted text field'

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ''):
            return value
        return encrypt_value(value)

    def from_db_value(self, value, expression, connection):
        if value in (None, ''):
            return value
        return decrypt_value(value)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        return name, 'campaigns.fields.EncryptedTextField', args, kwargs
