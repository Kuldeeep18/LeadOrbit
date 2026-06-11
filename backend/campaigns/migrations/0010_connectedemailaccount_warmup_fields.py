from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("campaigns", "0009_campaignlead_bounce_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="connectedemailaccount",
            name="current_daily_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="daily_sending_limit",
            field=models.IntegerField(default=100),
        ),
        migrations.AddField(
            model_name="connectedemailaccount",
            name="warmup_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
