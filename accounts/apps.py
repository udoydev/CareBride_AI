from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        from django.db.models.signals import post_migrate
        from accounts.models import SiteSettings
        from decimal import Decimal
        from django.db.models.fields import DecimalField

        def sync_site_settings_default(sender, **kwargs):
            """After any migration, ensure the SiteSettings singleton's
            platform_commission_rate matches the model's default value.
            This way changing the default in models.py + running 'migrate'
            automatically updates the admin panel value."""
            if sender.name != 'accounts':
                return
            try:
                site_settings = SiteSettings.get_solo()
                # Read the default directly from the model field definition
                field = SiteSettings._meta.get_field('platform_commission_rate')
                default_value = field.get_default()
                if default_value is not None:
                    desired = Decimal(str(default_value))
                    if site_settings.platform_commission_rate != desired:
                        site_settings.platform_commission_rate = desired
                        site_settings.save(update_fields=['platform_commission_rate'])
            except Exception:
                pass

        post_migrate.connect(sync_site_settings_default)
