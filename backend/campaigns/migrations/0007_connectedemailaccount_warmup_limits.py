from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0006_alter_sequencestep_channel_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='connectedemailaccount',
            name='daily_sending_limit',
            field=models.PositiveIntegerField(default=100),
        ),
        migrations.AddField(
            model_name='connectedemailaccount',
            name='current_daily_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='connectedemailaccount',
            name='warmup_enabled',
            field=models.BooleanField(default=False),
        ),
    ]
