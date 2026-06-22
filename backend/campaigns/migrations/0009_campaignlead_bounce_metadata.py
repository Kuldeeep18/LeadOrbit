from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("campaigns", "0008_merge_20260610_2213"),
    ]

    operations = [
        migrations.AddField(
            model_name="campaignlead",
            name="bounce_code",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="campaignlead",
            name="bounce_reason",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="campaignlead",
            name="bounce_type",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
    ]
