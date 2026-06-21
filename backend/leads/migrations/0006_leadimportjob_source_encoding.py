from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0005_merge_0004_leadimportjob_0004_tag_color'),
    ]

    operations = [
        migrations.AddField(
            model_name='leadimportjob',
            name='source_encoding',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
