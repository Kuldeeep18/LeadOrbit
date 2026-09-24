from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0010_custom_mailbox_security_updates'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='campaign',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                help_text='The user who created this campaign. Used as the Sandbox Mode test-email recipient.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='created_campaigns',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]