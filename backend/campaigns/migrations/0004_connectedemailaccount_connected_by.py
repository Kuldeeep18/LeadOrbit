from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_connected_by(apps, schema_editor):
    ConnectedEmailAccount = apps.get_model('campaigns', 'ConnectedEmailAccount')
    User = apps.get_model('users', 'User')

    for account in ConnectedEmailAccount.objects.filter(connected_by__isnull=True):
        users_in_org = User.objects.filter(organization_id=account.organization_id)
        matched_user = users_in_org.filter(email__iexact=account.email_address).first()
        if matched_user:
            ConnectedEmailAccount.objects.filter(id=account.id).update(connected_by_id=matched_user.id)
            continue

        # If the org has exactly one user, attribute the sender account to that user.
        only_user = users_in_org.first() if users_in_org.count() == 1 else None
        if only_user:
            ConnectedEmailAccount.objects.filter(id=account.id).update(connected_by_id=only_user.id)


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0003_alter_sequencestep_channel_type'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='connectedemailaccount',
            name='connected_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='connected_email_accounts',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(backfill_connected_by, migrations.RunPython.noop),
    ]
