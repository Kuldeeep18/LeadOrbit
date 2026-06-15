# Generated manually for bounce metadata tracking

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0006_alter_sequencestep_channel_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="campaignlead",
            name="bounce_reason",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="campaignlead",
            name="bounce_type",
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
    ]
