import uuid

from django.db import migrations, models
import django.utils.timezone
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0010_merge_0009_campaign_cached_counters_0009_campaignlead_bounce_metadata'),
    ]

    operations = [
        migrations.CreateModel(
            name='DailySendCount',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('send_date', models.DateField(default=django.utils.timezone.now)),
                ('count', models.PositiveIntegerField(default=0)),
                ('connected_account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='daily_send_counts', to='campaigns.connectedemailaccount')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tenants.organization')),
            ],
            options={
                'unique_together': {('organization', 'connected_account', 'send_date')},
            },
        ),
        migrations.AddIndex(
            model_name='dailysendcount',
            index=models.Index(fields=['connected_account', 'send_date'], name='campaigns_dai_connected_a7b4f6_idx'),
        ),
    ]
