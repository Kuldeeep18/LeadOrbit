from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='lead',
            name='custom_variables',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
