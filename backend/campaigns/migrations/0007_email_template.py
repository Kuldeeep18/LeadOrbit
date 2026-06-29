import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0006_alter_sequencestep_channel_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailTemplate',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(max_length=255)),
                ('subject', models.TextField()),
                ('body', models.TextField()),
                ('category', models.CharField(blank=True, default='general', max_length=50)),
                ('usage_count', models.IntegerField(default=0)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tenants.organization')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
