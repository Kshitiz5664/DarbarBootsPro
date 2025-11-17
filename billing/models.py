# billing/models.py
from decimal import Decimal, ROUND_HALF_UP
from django.db import models, transaction
from django.conf import settings
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.mixins import SoftDeleteMixin
from items.models import Item
from party.models import Party
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone


# -----------------------
# Invoice
# -----------------------
class Invoice(SoftDeleteMixin, models.Model):
    invoice_number = models.CharField(max_length=50, unique=True)
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name='invoices')
    date = models.DateField()

    base_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    is_paid = models.BooleanField(default=False)
    is_limit_enabled = models.BooleanField(default=False)
    limit_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
        help_text="nullable invoice limit"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='invoices_created'
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='invoices_updated'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-invoice_number']
        verbose_name = "Invoice"
        verbose_name_plural = "Invoices"

    def __str__(self):
        return f"Invoice {self.invoice_number}"

    # -----------------------
    # Computed Properties
    # -----------------------

    @property
    def total_return(self):
        total = self.returns.filter(is_active=True).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
        return Decimal(total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def total_paid(self):
        total = self.payments.filter(is_active=True).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
        return Decimal(total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def total_amount(self):
        base = Decimal(self.base_amount or Decimal('0.00'))
        ret = Decimal(self.total_return or Decimal('0.00'))
        final = base - ret
        return Decimal(max(final, 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def balance_due(self):
        balance = self.total_amount - self.total_paid
        return Decimal(max(balance, 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # -----------------------
    # Utility Functions
    # -----------------------
    def recalculate_base_amount(self):
        """Recalculate the base amount using all active InvoiceItems."""
        total = self.invoice_items.filter(is_active=True).aggregate(total=models.Sum('total'))['total'] or Decimal('0.00')
        self.base_amount = Decimal(total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.is_paid = self.total_paid >= self.base_amount
        self.updated_at = timezone.now()
        self.save(update_fields=['base_amount', 'is_paid', 'updated_at'])


# -----------------------
# InvoiceItem
# -----------------------
class InvoiceItem(SoftDeleteMixin, models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='invoice_items')
    item = models.ForeignKey(Item, on_delete=models.SET_NULL, null=True)
    quantity = models.PositiveIntegerField()
    rate = models.DecimalField(max_digits=14, decimal_places=2)
    gst_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='invoiceitems_created'
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='invoiceitems_updated'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Invoice Item"
        verbose_name_plural = "Invoice Items"

    def __str__(self):
        return f"{self.item.name if self.item else 'Unknown Item'} ({self.quantity})"

    # -----------------------
    # Save Override
    # -----------------------
    def save(self, *args, **kwargs):
        quantity = Decimal(self.quantity or 0)
        rate = Decimal(self.rate or Decimal('0.00'))
        gst = Decimal(self.gst_amount or Decimal('0.00'))
        discount = Decimal(self.discount_amount or Decimal('0.00'))
        self.total = (quantity * rate + gst - discount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)

    # -----------------------
    # Display Helper
    # -----------------------
    def display_name(self):
        """Generate a human-readable display name combining invoice & item info."""
        invoice_num = self.invoice.invoice_number if self.invoice else 'NoInvoice'
        party_name = self.invoice.party.name if (self.invoice and self.invoice.party) else 'No Party'
        date_text = self.invoice.date.strftime('%d-%b-%Y') if (self.invoice and self.invoice.date) else 'No Date'
        return f"{invoice_num} | {party_name} | {date_text} | ₹{self.total:.2f}"


# -----------------------
# Payment
# -----------------------
class Payment(SoftDeleteMixin, models.Model):
    PAYMENT_MODES = [
        ('cash', 'Cash'),
        ('upi', 'UPI'),
        ('bank', 'Bank Transfer'),
        ('cheque', 'Cheque'),
    ]

    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name='payments')
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    mode = models.CharField(max_length=10, choices=PAYMENT_MODES)
    notes = models.TextField(blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='payments_created'
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='payments_updated'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date']
        verbose_name = "Payment"
        verbose_name_plural = "Payments"

    def __str__(self):
        return f"Payment ₹{self.amount} - {self.party.name}"


# -----------------------
# Return
# -----------------------
class Return(SoftDeleteMixin, models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='returns')
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name='returns')
    return_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reason = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='returns/', blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='returns_created'
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='returns_updated'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-return_date']
        verbose_name = "Return"
        verbose_name_plural = "Returns"

    def __str__(self):
        return f"Return #{self.id} - {self.invoice.invoice_number}"


# -----------------------
# Challan & ChallanItem
# -----------------------
class Challan(SoftDeleteMixin, models.Model):
    challan_number = models.CharField(max_length=50, unique=True, editable=False)
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name='challans')
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='challans')
    date = models.DateField()
    transport_details = models.TextField(blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='challans_created'
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='challans_updated'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date']
        verbose_name = "Delivery Challan"
        verbose_name_plural = "Delivery Challans"

    def __str__(self):
        # Display format: CHN-001 | 02-11-2025 | Party Name
        return f"{self.challan_number} | {self.date.strftime('%d-%m-%Y')} | {self.party.name}"

    @staticmethod
    def generate_challan_number():
        """Generate unique challan number in format: CHN-YYYYMM-001"""
        today = timezone.now()
        year_month = today.strftime('%Y%m')
        prefix = f"CHN-{year_month}-"
        
        # Get the last challan number for this month
        last_challan = Challan.objects.filter(
            challan_number__startswith=prefix
        ).order_by('-challan_number').first()
        
        if last_challan:
            # Extract the sequence number and increment
            last_number = int(last_challan.challan_number.split('-')[-1])
            new_number = last_number + 1
        else:
            new_number = 1
        
        return f"{prefix}{new_number:03d}"

    def save(self, *args, **kwargs):
        if not self.challan_number:
            self.challan_number = self.generate_challan_number()
        super().save(*args, **kwargs)


class ChallanItem(SoftDeleteMixin, models.Model):
    challan = models.ForeignKey(Challan, on_delete=models.CASCADE, related_name='challan_items')
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='challanitems_created'
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='challanitems_updated'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.item.name} ({self.quantity})"

# -----------------------
# Balance
# -----------------------
class Balance(SoftDeleteMixin, models.Model):
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name='balances')
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=0)
    price = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='balances_created'
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='balances_updated'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['party', 'item']
        ordering = ['party', 'item']
        verbose_name = "Old Balance"
        verbose_name_plural = "Old Balances"

    def __str__(self):
        return f"{self.party.name} - {self.item.name}"


# -----------------------
# Signals
# -----------------------
@receiver([post_save, post_delete], sender=InvoiceItem)
def invoiceitem_changed(sender, instance, **kwargs):
    invoice = instance.invoice
    if invoice:
        with transaction.atomic():
            invoice.recalculate_base_amount()


@receiver(pre_save, sender=Return)
def validate_return_amount(sender, instance, **kwargs):
    if instance.pk:
        return
    invoice = instance.invoice
    if invoice:
        existing_returns = invoice.returns.filter(is_active=True).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
        allowed = invoice.base_amount - Decimal(existing_returns)
        if instance.amount > allowed:
            raise ValidationError({'amount': f"Return amount (₹{instance.amount}) exceeds allowable remaining amount (₹{allowed})."})


@receiver([post_save, post_delete], sender=Return)
def touch_invoice_on_return(sender, instance, **kwargs):
    invoice = instance.invoice
    if invoice:
        invoice.updated_at = timezone.now()
        invoice.save(update_fields=['updated_at'])
