from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0010_custom_mailbox_security_updates'),
    ]

    operations = [
        migrations.AddField(
            model_name='connectedemailaccount',
            name='warmup_enabled',
            field=models.BooleanField(
                default=False,
                help_text='Enable the 14-day automated domain warm-up schedule for this mailbox.',
            ),
        ),
        migrations.AddField(
            model_name='connectedemailaccount',
            name='warmup_start_date',
            field=models.DateField(
                blank=True,
                null=True,
                help_text='Date when warm-up was activated. Set automatically when warmup_enabled is first turned on.',
            ),
        ),
        migrations.AddField(
            model_name='connectedemailaccount',
            name='warmup_day',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Current warm-up day (0 = not started, 1–14 = in progress, 15 = completed).',
            ),
        ),
        migrations.AddField(
            model_name='connectedemailaccount',
            name='warmup_max_daily_limit',
            field=models.PositiveIntegerField(
                default=500,
                help_text='Target daily send ceiling. Warm-up stops once this limit is reached.',
            ),
        ),
        migrations.AddField(
            model_name='connectedemailaccount',
            name='daily_send_limit',
            field=models.PositiveIntegerField(
                default=0,
                help_text=(
                    'Maximum emails this account may send per calendar day (UTC). '
                    '0 = no limit. Updated automatically by the warm-up scheduler.'
                ),
            ),
        ),
    ]
