from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0002_organization_enable_ai_personalization_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='timezone',
            field=models.CharField(blank=True, help_text='Default IANA timezone for the organization', max_length=63, null=True),
        ),
    ]
