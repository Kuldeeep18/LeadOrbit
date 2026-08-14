from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0006_alter_sequencestep_channel_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='connectedemailaccount',
            name='provider',
            field=models.CharField(
                choices=[
                    ('GOOGLE', 'Google'),
                    ('MICROSOFT', 'Microsoft'),
                    ('SMTP', 'Custom SMTP/IMAP'),
                ],
                default='GOOGLE',
                max_length=20,
            ),
        ),
        migrations.AddField(model_name='connectedemailaccount', name='smtp_host', field=models.CharField(blank=True, default='', max_length=255)),
        migrations.AddField(model_name='connectedemailaccount', name='smtp_port', field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='connectedemailaccount', name='smtp_username', field=models.CharField(blank=True, default='', max_length=255)),
        migrations.AddField(model_name='connectedemailaccount', name='smtp_password', field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='connectedemailaccount', name='smtp_use_tls', field=models.BooleanField(default=True)),
        migrations.AddField(model_name='connectedemailaccount', name='imap_host', field=models.CharField(blank=True, default='', max_length=255)),
        migrations.AddField(model_name='connectedemailaccount', name='imap_port', field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='connectedemailaccount', name='imap_username', field=models.CharField(blank=True, default='', max_length=255)),
        migrations.AddField(model_name='connectedemailaccount', name='imap_password', field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='connectedemailaccount', name='imap_use_ssl', field=models.BooleanField(default=True)),
    ]
