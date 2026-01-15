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


# -----------------------
# Invoice
# -----------------------
class Invoice(SoftDeleteMixin, models.Model):
    invoice_number = models.CharField(max_length=50, unique=True)  # ✅ Already has business number
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

    def recalculate_base_amount(self):
        """Recalculate the base amount using all active InvoiceItems."""
        total = self.invoice_items.filter(is_active=True).aggregate(total=models.Sum('total'))['total'] or Decimal('0.00')
        self.base_amount = Decimal(total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.is_paid = self.total_paid >= self.base_amount
        self.updated_at = timezone.now()
        self.save(update_fields=['base_amount', 'is_paid', 'updated_at'])

    def hard_delete(self):
        """Permanently delete the invoice (bypass soft delete)."""
        super(Invoice, self).delete()


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

    def save(self, *args, **kwargs):
        quantity = Decimal(self.quantity or 0)
        rate = Decimal(self.rate or Decimal('0.00'))
        gst = Decimal(self.gst_amount or Decimal('0.00'))
        discount = Decimal(self.discount_amount or Decimal('0.00'))
        self.total = (quantity * rate + gst - discount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)

    def display_name(self):
        """Generate a human-readable display name combining invoice & item info."""
        invoice_num = self.invoice.invoice_number if self.invoice else 'NoInvoice'
        party_name = self.invoice.party.name if (self.invoice and self.invoice.party) else 'No Party'
        date_text = self.invoice.date.strftime('%d-%b-%Y') if (self.invoice and self.invoice.date) else 'No Date'
        return f"{invoice_num} | {party_name} | {date_text} | ₹{self.total:.2f}"

    def hard_delete(self):
        """Permanently delete the invoice item (bypass soft delete)."""
        super(InvoiceItem, self).delete()


# -----------------------
# Payment
# -----------------------
class Payment(SoftDeleteMixin, models.Model):
    # ✅ NEW: Auto-generated business number
    payment_number = models.CharField(
        max_length=50, 
        unique=True, 
        editable=False,
        help_text="Auto-generated payment reference number"
    )
    
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
        ordering = ['-date', '-payment_number']
        verbose_name = "Payment"
        verbose_name_plural = "Payments"

    def __str__(self):
        return f"Payment {self.payment_number} - ₹{self.amount} - {self.party.name}"

    # ✅ NEW: Auto-generate payment number
    @staticmethod
    def generate_payment_number():
        """Generate unique payment number in format: PAY-YYYYMM-0001"""
        today = timezone.now()
        year_month = today.strftime('%Y%m')
        prefix = f"PAY-{year_month}-"
        
        last_payment = Payment.objects.filter(
            payment_number__startswith=prefix
        ).order_by('-payment_number').first()
        
        if last_payment:
            try:
                last_number = int(last_payment.payment_number.split('-')[-1])
                new_number = last_number + 1
            except (ValueError, IndexError):
                new_number = 1
        else:
            new_number = 1
        
        return f"{prefix}{new_number:04d}"

    def save(self, *args, **kwargs):
        # Auto-generate payment number if not set
        if not self.payment_number:
            self.payment_number = self.generate_payment_number()
        super().save(*args, **kwargs)

    def hard_delete(self):
        """Permanently delete the payment (bypass soft delete)."""
        super(Payment, self).delete()


# -----------------------
# Return
# -----------------------
class Return(SoftDeleteMixin, models.Model):
    # ✅ NEW: Auto-generated business number
    return_number = models.CharField(
        max_length=50, 
        unique=True, 
        editable=False,
        help_text="Auto-generated return reference number"
    )
    
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
        ordering = ['-return_date', '-return_number']
        verbose_name = "Return"
        verbose_name_plural = "Returns"

    def __str__(self):
        return f"Return {self.return_number} - {self.invoice.invoice_number}"

    # ✅ NEW: Auto-generate return number
    @staticmethod
    def generate_return_number():
        """Generate unique return number in format: RET-YYYYMM-0001"""
        today = timezone.now()
        year_month = today.strftime('%Y%m')
        prefix = f"RET-{year_month}-"
        
        last_return = Return.objects.filter(
            return_number__startswith=prefix
        ).order_by('-return_number').first()
        
        if last_return:
            try:
                last_number = int(last_return.return_number.split('-')[-1])
                new_number = last_number + 1
            except (ValueError, IndexError):
                new_number = 1
        else:
            new_number = 1
        
        return f"{prefix}{new_number:04d}"

    def get_items_for_stock_restoration(self):
        """
        Extract invoice items that need stock restoration.
        Returns list of dicts: [{'item_id': int, 'quantity': int}, ...]
        """
        if hasattr(self, 'return_items') and self.return_items.filter(is_active=True).exists():
            items_to_restore = []
            for return_item in self.return_items.filter(is_active=True):
                if return_item.invoice_item.item:
                    items_to_restore.append({
                        'item_id': return_item.invoice_item.item.id,
                        'quantity': return_item.quantity
                    })
            return items_to_restore
        
        items_to_restore = []
        invoice_items = self.invoice.invoice_items.filter(is_active=True)
        
        if not invoice_items.exists():
            return items_to_restore
        
        invoice_total = self.invoice.base_amount or Decimal('0.00')
        if invoice_total <= 0:
            return items_to_restore
        
        return_percentage = self.amount / invoice_total
        
        for invoice_item in invoice_items:
            if invoice_item.item:
                quantity_to_return = int(invoice_item.quantity * return_percentage)
                
                if quantity_to_return == 0 and self.amount > 0:
                    quantity_to_return = 1
                
                if quantity_to_return > 0:
                    items_to_restore.append({
                        'item_id': invoice_item.item.id,
                        'quantity': quantity_to_return
                    })
        
        return items_to_restore
    
    def validate_return_amount(self):
        """Validate that return amount doesn't exceed allowable limit."""
        if self.amount <= 0:
            raise ValidationError("Return amount must be greater than zero.")
        
        existing_returns = self.invoice.returns.filter(
            is_active=True
        ).exclude(pk=self.pk).aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0.00')
        
        max_returnable = self.invoice.base_amount - existing_returns
        
        if self.amount > max_returnable:
            raise ValidationError(
                f"Return amount ₹{self.amount} exceeds maximum returnable "
                f"amount ₹{max_returnable:.2f}. "
                f"(Invoice Total: ₹{self.invoice.base_amount}, "
                f"Already Returned: ₹{existing_returns})"
            )
    
    def save(self, *args, **kwargs):
        # Auto-generate return number if not set
        if not self.return_number:
            self.return_number = self.generate_return_number()
        
        # Validate before saving (only for new returns)
        if not self.pk:
            self.validate_return_amount()
        
        super().save(*args, **kwargs)

    def hard_delete(self):
        """Permanently delete the return (bypass soft delete)."""
        super(Return, self).delete()


# -----------------------
# ReturnItem (Optional - Future Enhancement)
# -----------------------
class ReturnItem(SoftDeleteMixin, models.Model):
    """Track specific items and quantities being returned"""
    return_instance = models.ForeignKey(
        Return, 
        on_delete=models.CASCADE, 
        related_name='return_items'
    )
    invoice_item = models.ForeignKey(
        InvoiceItem, 
        on_delete=models.CASCADE,
        related_name='return_items'
    )
    quantity = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='returnitems_created'
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='returnitems_updated'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Return Item"
        verbose_name_plural = "Return Items"
    
    def __str__(self):
        item_name = self.invoice_item.item.name if self.invoice_item.item else 'Unknown'
        return f"{item_name} x{self.quantity} - ₹{self.amount}"
    
    def clean(self):
        """Validate return quantity doesn't exceed invoice quantity"""
        if not self.invoice_item:
            return
        
        existing_returns = ReturnItem.objects.filter(
            invoice_item=self.invoice_item,
            is_active=True
        ).exclude(pk=self.pk).aggregate(
            total=models.Sum('quantity')
        )['total'] or 0
        
        remaining = self.invoice_item.quantity - existing_returns
        
        if self.quantity > remaining:
            raise ValidationError(
                f"Cannot return {self.quantity} units. "
                f"Only {remaining} units remaining for this item."
            )
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def hard_delete(self):
        """Permanently delete the return item (bypass soft delete)."""
        super(ReturnItem, self).delete()


# -----------------------
# Challan & ChallanItem
# -----------------------
class Challan(SoftDeleteMixin, models.Model):
    challan_number = models.CharField(max_length=50, unique=True, editable=False)  # ✅ Already has business number
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
        ordering = ['-date', '-challan_number']
        verbose_name = "Delivery Challan"
        verbose_name_plural = "Delivery Challans"

    def __str__(self):
        return f"{self.challan_number} | {self.date.strftime('%d-%m-%Y')} | {self.party.name}"

    @staticmethod
    def generate_challan_number():
        """Generate unique challan number in format: CHN-YYYYMM-001"""
        today = timezone.now()
        year_month = today.strftime('%Y%m')
        prefix = f"CHN-{year_month}-"
        
        last_challan = Challan.objects.filter(
            challan_number__startswith=prefix
        ).order_by('-challan_number').first()
        
        if last_challan:
            last_number = int(last_challan.challan_number.split('-')[-1])
            new_number = last_number + 1
        else:
            new_number = 1
        
        return f"{prefix}{new_number:03d}"

    def save(self, *args, **kwargs):
        if not self.challan_number:
            self.challan_number = self.generate_challan_number()
        super().save(*args, **kwargs)

    def hard_delete(self):
        """Permanently delete the challan (bypass soft delete)."""
        super(Challan, self).delete()


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

    def hard_delete(self):
        """Permanently delete the challan item (bypass soft delete)."""
        super(ChallanItem, self).delete()


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

    def hard_delete(self):
        """Permanently delete the balance (bypass soft delete)."""
        super(Balance, self).delete()


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
def validate_return_amount_signal(sender, instance, **kwargs):
    """Signal to validate return amount before save"""
    if instance.pk:
        return
    invoice = instance.invoice
    if invoice:
        existing_returns = invoice.returns.filter(is_active=True).aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0.00')
        allowed = invoice.base_amount - Decimal(existing_returns)
        if instance.amount > allowed:
            raise ValidationError({
                'amount': f"Return amount (₹{instance.amount}) exceeds allowable remaining amount (₹{allowed})."
            })


@receiver([post_save, post_delete], sender=Return)
def touch_invoice_on_return(sender, instance, **kwargs):
    """Update invoice timestamp when return is modified"""
    invoice = instance.invoice
    if invoice:
        invoice.updated_at = timezone.now()
        invoice.save(update_fields=['updated_at'])
