from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('ADMIN', 'Admin'),
                    ('MANAGER', 'Manager'),
                    ('MEMBER', 'Member'),
                    ('USER', 'User'),
                ],
                default='MEMBER',
                max_length=20,
            ),
        ),
    ]
