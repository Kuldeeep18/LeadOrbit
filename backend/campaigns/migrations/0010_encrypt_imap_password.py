from django.db import migrations

import campaigns.fields


def encrypt_existing_imap_passwords(apps, schema_editor):
    ConnectedEmailAccount = apps.get_model('campaigns', 'ConnectedEmailAccount')
    from campaigns.encryption import encrypt_value, is_encrypted

    for account in ConnectedEmailAccount.objects.exclude(imap_password='').iterator():
        if is_encrypted(account.imap_password):
            continue
        # Use queryset.update() so plaintext is encrypted once at the DB layer
        # before the field is converted to EncryptedTextField.
        ConnectedEmailAccount.objects.filter(pk=account.pk).update(
            imap_password=encrypt_value(account.imap_password),
        )


class Migration(migrations.Migration):
    dependencies = [
        ('campaigns', '0009_connectedemailaccount_imap_fields'),
    ]

    operations = [
        migrations.RunPython(encrypt_existing_imap_passwords, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='connectedemailaccount',
            name='imap_password',
            field=campaigns.fields.EncryptedTextField(blank=True, default=''),
        ),
    ]
