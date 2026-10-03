from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0005_merge_0004_leadimportjob_0004_tag_color'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='leadtag',
            constraint=models.UniqueConstraint(fields=('lead', 'tag'), name='unique_lead_tag'),
        ),
    ]
