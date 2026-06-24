from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_user_is_email_verified'),
        ('users', '0002_user_member_role_default'),
    ]

    operations = []
