from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0008_merge_20260610_2213"),
    ]

    operations = [
        migrations.AddField(
            model_name="connectedemailaccount",
            name="imap_host",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="imap_port",
            field=models.IntegerField(default=993),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="imap_username",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="imap_password",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
