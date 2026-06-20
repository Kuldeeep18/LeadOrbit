# Generated migration for adding cached counter fields to Campaign model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0008_merge_20260610_2213'),  # Adjust to the latest migration
    ]

    operations = [
        migrations.AddField(
            model_name='campaign',
            name='leads_count',
            field=models.IntegerField(default=0, help_text='Total enrolled leads'),
        ),
        migrations.AddField(
            model_name='campaign',
            name='sent_count',
            field=models.IntegerField(default=0, help_text='Leads with sent messages'),
        ),
        migrations.AddField(
            model_name='campaign',
            name='open_count',
            field=models.IntegerField(default=0, help_text='Leads that opened emails'),
        ),
        migrations.AddField(
            model_name='campaign',
            name='reply_count',
            field=models.IntegerField(default=0, help_text='Leads that replied'),
        ),
        migrations.AddField(
            model_name='campaign',
            name='clicked_count',
            field=models.IntegerField(default=0, help_text='Leads that clicked links'),
        ),
        migrations.AddField(
            model_name='campaign',
            name='bounced_count',
            field=models.IntegerField(default=0, help_text='Bounced leads'),
        ),
    ]
