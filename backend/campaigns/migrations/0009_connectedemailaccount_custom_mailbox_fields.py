from django.db import migrations, models
from django.db.models import Q
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0008_merge_20260610_2213"),
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
            name="access_token",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="connectedemailaccount",
            name="provider",
            field=models.CharField(
                choices=[
                    ("GOOGLE", "Google"),
                    ("MICROSOFT", "Microsoft"),
                    ("CUSTOM", "Custom SMTP/IMAP"),
                ],
                default="GOOGLE",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="imap_host",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="imap_password",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="imap_port",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="imap_use_ssl",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="imap_username",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="smtp_host",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="smtp_password",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="smtp_port",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="smtp_use_ssl",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="smtp_use_tls",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="smtp_username",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
