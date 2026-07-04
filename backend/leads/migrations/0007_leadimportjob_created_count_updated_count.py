from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0006_lead_pipeline_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='leadimportjob',
            name='created_count',
            field=models.IntegerField(default=0, help_text='New leads created'),
        ),
        migrations.AddField(
            model_name='leadimportjob',
            name='updated_count',
            field=models.IntegerField(default=0, help_text='Existing leads updated'),
        ),
    ]
