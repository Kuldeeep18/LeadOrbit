from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0002_organization_enable_ai_personalization_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='custom_tracking_domain',
            field=models.CharField(blank=True, help_text='Optional branded tracking domain, e.g. track.company.com', max_length=253, null=True),
        ),
    ]
