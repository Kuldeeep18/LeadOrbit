from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0005_merge_0004_leadimportjob_0004_tag_color'),
    ]

    operations = [
        migrations.AddField(
            model_name='lead',
            name='pipeline_status',
            field=models.CharField(
                choices=[
                    ('new', 'New'),
                    ('contacted', 'Contacted'),
                    ('interested', 'Interested'),
                    ('replied', 'Replied'),
                    ('converted', 'Converted'),
                    ('closed', 'Closed'),
                ],
                default='new',
                db_index=True,
                max_length=20,
            ),
        ),
    ]
