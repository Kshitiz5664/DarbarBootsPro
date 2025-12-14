from django.db import models
from django.conf import settings
from django.core.validators import MinLengthValidator
from django.core.exceptions import ValidationError
import re


class PartyManager(models.Manager):
    """Manager to return only active parties by default."""
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class Party(models.Model):
    """
    Customer/Vendor party model with contact information and payment tracking.
    Supports soft delete for data preservation.
    """
    name = models.CharField(
        max_length=255, 
        unique=True,
        db_index=True,
        validators=[MinLengthValidator(2)]
    )
    contact_person = models.CharField(
        max_length=255, 
        blank=True, 
        null=True
    )
    phone = models.CharField(
        max_length=20, 
        blank=True, 
        null=True,
        help_text="Phone number with country code"
    )
    email = models.EmailField(
        blank=True, 
        null=True
    )
    address = models.TextField(
        blank=True, 
        null=True
    )
    total_pending = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=0,
        help_text="Cached pending amount for performance"
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True
    )

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
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PartyManager()  # Active parties
    all_objects = models.Manager()  # All parties including inactive

    class Meta:
        ordering = ['name']
        verbose_name = "Party"
        verbose_name_plural = "Parties"
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['is_active', 'name']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        """Validate model data."""
        super().clean()
        
        # Validate phone number format if provided
        if self.phone:
            phone_digits = ''.join(filter(str.isdigit, self.phone))
            if len(phone_digits) < 10:
                raise ValidationError({
                    'phone': 'Phone number must contain at least 10 digits.'
                })

    @property
    def total_invoiced(self):
        """Calculate total amount from all invoices."""
        return sum(inv.total_amount for inv in self.invoices.all())

    @property
    def total_paid(self):
        """Calculate total amount paid across all invoices."""
        return sum(pay.amount for pay in self.payments.all())

    @property
    def pending_amount(self):
        """Calculate pending balance (invoiced - paid)."""
        return self.total_invoiced - self.total_paid

    @property
    def formatted_phone(self):
        """Return formatted phone number for display."""
        if self.phone:
            phone_digits = ''.join(filter(str.isdigit, self.phone))
            if len(phone_digits) == 10:
                return f"+91 {phone_digits[:5]} {phone_digits[5:]}"
            return self.phone
        return "N/A"

    def soft_delete(self):
        """Soft delete the party by marking as inactive."""
        self.is_active = False
        self.save(update_fields=['is_active', 'updated_at'])

    def hard_delete(self):
        """Permanently delete the party (bypass soft delete)."""
        super(Party, self).delete()