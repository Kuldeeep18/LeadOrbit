import campaigns.fields
from django.db import migrations


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


def decrypt_existing_mailbox_passwords(apps, schema_editor):
    ConnectedEmailAccount = apps.get_model("campaigns", "ConnectedEmailAccount")
    quote_name = schema_editor.connection.ops.quote_name
    table = quote_name(ConnectedEmailAccount._meta.db_table)
    id_column = quote_name("id")

    with schema_editor.connection.cursor() as cursor:
        for account in ConnectedEmailAccount.objects.iterator():
            updates = {}
            if account.smtp_password:
                updates["smtp_password"] = account.smtp_password
            if account.imap_password:
                updates["imap_password"] = account.imap_password
            if not updates:
                continue

            set_clause = ", ".join(f"{quote_name(field)} = %s" for field in updates)
            cursor.execute(
                f"UPDATE {table} SET {set_clause} WHERE {id_column} = %s",
                [*updates.values(), account.pk],
            )


class Migration(migrations.Migration):

    dependencies = [
        ("campaigns", "0009_campaign_cached_counters"),
        ("campaigns", "0009_campaignlead_bounce_metadata"),
        ("campaigns", "0009_connectedemailaccount_custom_mailbox_fields"),
    ]

    operations = [
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
            decrypt_existing_mailbox_passwords,
        ),
    ]
