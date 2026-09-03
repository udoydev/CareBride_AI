from decimal import Decimal
from django.db import migrations, models


def update_commission_rate(apps, schema_editor):
    """Update existing SiteSettings records to match the new model default.

    The post_migrate signal in accounts/apps.py will also sync this on future
    migrations, but this RunPython ensures the value is correct on the SAME
    migration that changes the default.
    """
    SiteSettings = apps.get_model("accounts", "SiteSettings")
    new_default = Decimal("10.00")
    SiteSettings.objects.update(platform_commission_rate=new_default)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0020_site_commission_rate"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sitesettings",
            name="platform_commission_rate",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("10.00"),
                help_text="Platform commission rate (percentage) charged on each paid appointment. Default: 10%%",
                max_digits=5,
            ),
        ),
        migrations.RunPython(
            update_commission_rate,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
