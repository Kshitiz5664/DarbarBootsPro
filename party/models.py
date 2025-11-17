from django.db import models
from django.conf import settings

class PartyManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)

class Party(models.Model):
    name = models.CharField(max_length=255, unique=True)
    contact_person = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    total_pending = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name="parties_created"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name="parties_updated"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PartyManager()  # Active parties
    all_objects = models.Manager()  # All parties including soft deleted

    class Meta:
        ordering = ['name']
        verbose_name = "Party"
        verbose_name_plural = "Parties"

    def __str__(self):
        return self.name

    @property
    def total_invoiced(self):
        return sum(inv.total_amount for inv in self.invoices.all())

    @property
    def total_paid(self):
        return sum(pay.amount for pay in self.payments.all())

    @property
    def pending_amount(self):
        return self.total_invoiced - self.total_paid

    def soft_delete(self):
        """Soft delete the party"""
        self.is_active = False
        self.save()
