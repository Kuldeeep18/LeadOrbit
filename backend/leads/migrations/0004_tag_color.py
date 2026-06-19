# Generated migration for Issue #244 — custom tag colors

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0003_merge_0002_blockeddomain_0002_lead_custom_variables"),
    ]

    operations = [
        migrations.AddField(
            model_name="tag",
            name="color",
            field=models.CharField(
                default="#6366f1",
                help_text="Hex color code for the tag badge, e.g. #6366f1",
                max_length=7,
            ),
        ),
    ]
