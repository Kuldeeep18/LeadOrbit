import campaigns.fields
from django.db import migrations, models
from django.db.models import Q
from django.db.models.functions import Lower


def encrypt_existing_mailbox_passwords(apps, schema_editor):
    ConnectedEmailAccount = apps.get_model("campaigns", "ConnectedEmailAccount")

    for account in ConnectedEmailAccount.objects.iterator():
        update_fields = []
        if account.smtp_password:
            update_fields.append("smtp_password")
        if account.imap_password:
            update_fields.append("imap_password")

        if update_fields:
            account.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ("campaigns", "0009_campaign_cached_counters"),
        ("campaigns", "0009_campaignlead_bounce_metadata"),
        ("campaigns", "0009_connectedemailaccount_custom_mailbox_fields"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="connectedemailaccount",
            constraint=models.UniqueConstraint(
                Lower("email_address"),
                "organization",
                "connected_by",
                "provider",
                condition=Q(provider="CUSTOM"),
                name="uniq_custom_connected_account_per_user_email",
            ),
        ),
        migrations.AlterField(
            model_name="connectedemailaccount",
            name="smtp_password",
            field=campaigns.fields.EncryptedTextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="connectedemailaccount",
            name="imap_password",
            field=campaigns.fields.EncryptedTextField(blank=True, null=True),
        ),
        migrations.RunPython(
            encrypt_existing_mailbox_passwords,
            migrations.RunPython.noop,
        ),
    ]
