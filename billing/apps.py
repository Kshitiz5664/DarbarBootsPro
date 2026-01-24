from django.apps import AppConfig


# billing/apps.py
class BillingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'billing'
    verbose_name = 'Billing Management'
    
    def ready(self):
        import billing.signals  # noqa: F401

