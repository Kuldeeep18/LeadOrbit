from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0007_leadimportjob_created_count_updated_count'),
    ]

    operations = [
        migrations.AddField(
            model_name='lead',
            name='timezone',
            field=models.CharField(blank=True, help_text='IANA timezone name such as America/New_York', max_length=63, null=True),
        ),
    ]
