from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0009_campaign_cached_counters'),
        ('campaigns', '0009_campaignlead_bounce_metadata'),
    ]

    operations = [
        migrations.AddField(
            model_name='campaignlead',
            name='last_bounced_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='campaignlead',
            name='last_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
