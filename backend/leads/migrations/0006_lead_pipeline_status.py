from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0005_merge_0004_leadimportjob_0004_tag_color'),
    ]

    operations = [
        migrations.AddField(
            model_name='lead',
            name='pipeline_status',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
