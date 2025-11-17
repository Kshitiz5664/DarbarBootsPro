from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'billing'
    verbose_name = 'Billing Management'

    def ready(self):
        """
        Import signals when the app is ready so that they are registered.
        """
        import billing.signals  # noqa
