from django.db import models

from .encryption import decrypt_value, encrypt_value


class EncryptedTextField(models.TextField):
    """
    TextField that transparently encrypts values at rest using Fernet.

    Application code reads and writes plaintext; ciphertext is stored in the
    database and decrypted automatically on retrieval.
    """

    description = 'Encrypted text field'

    def get_prep_value(self, value):
        """
        Encrypt a plaintext value before it is written to the database.

        Args:
            value: Plaintext field value from the model instance.

        Returns:
            str | None: Encrypted ciphertext, or None/empty when unset.
        """
        value = super().get_prep_value(value)
        if value in (None, ''):
            return value
        return encrypt_value(value)

    def from_db_value(self, value, expression, connection):
        """
        Decrypt a database value when loading a model instance.

        Args:
            value: Raw value returned from the database driver.
            expression: ORM expression (unused).
            connection: Database connection (unused).

        Returns:
            str | None: Decrypted plaintext, or None/empty when unset.
        """
        if value in (None, ''):
            return value
        return decrypt_value(value)

    def deconstruct(self):
        """
        Serialize the field for Django migrations.

        Returns:
            tuple: Migration deconstruction tuple with a stable import path.
        """
        name, path, args, kwargs = super().deconstruct()
        return name, 'campaigns.fields.EncryptedTextField', args, kwargs
