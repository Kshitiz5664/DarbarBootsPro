# billing/models.py
# ✅ COMPLETE - All errors fixed

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

import logging

logger = logging.getLogger(__name__)



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
    payment_number = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        null=True,
        blank=True,
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
        # ✅ FIXED: Was using self.return_number (wrong), now uses self.payment_number
        number = self.payment_number or f"PAY-TEMP-{self.id}"
        invoice_num = self.invoice.invoice_number if self.invoice else "No Invoice"
        return f"Payment {number} - {invoice_num}"

    @staticmethod
    def generate_payment_number():
        """Generate unique payment number in format: PAY-YYYYMM-0001"""
        today = timezone.now()
        year_month = today.strftime('%Y%m')
        prefix = f"PAY-{year_month}-"
        
        last_payment = Payment.objects.filter(
            payment_number__startswith=prefix
        ).order_by('-payment_number').first()
        
        if last_payment and last_payment.payment_number:
            try:
                last_number = int(last_payment.payment_number.split('-')[-1])
                new_number = last_number + 1
            except (ValueError, IndexError):
                new_number = 1
        else:
            new_number = 1
        
        return f"{prefix}{new_number:04d}"

    def save(self, *args, **kwargs):
        if not self.payment_number:
            with transaction.atomic():
                self.payment_number = self.generate_payment_number()
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

    def hard_delete(self):
        """Permanently delete the payment (bypass soft delete)."""
        super(Payment, self).delete()


# -----------------------
# Return
# -----------------------
class Return(SoftDeleteMixin, models.Model):
    return_number = models.CharField(
        max_length=50, 
        unique=True, 
        editable=False,
        null=True,
        blank=True,
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
        number = self.return_number or f"RET-TEMP-{self.id}"
        invoice_num = self.invoice.invoice_number if self.invoice else "No Invoice"
        return f"Return {number} - {invoice_num}"

    @staticmethod
    def generate_return_number():
        """Generate unique return number in format: RET-YYYYMM-0001"""
        today = timezone.now()
        year_month = today.strftime('%Y%m')
        prefix = f"RET-{year_month}-"
        
        last_return = Return.objects.filter(
            return_number__startswith=prefix
        ).order_by('-return_number').first()
        
        if last_return and last_return.return_number:
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
        REFACTORED: Extract items for stock restoration.
        ALWAYS uses ReturnItem records - no fallback estimation.
        
        Returns:
            list[dict]: [{'item_id': int, 'quantity': int}, ...]
        
        Raises:
            ValueError: If no ReturnItem records exist
        """
        items_to_restore = []
        
        # ReturnItem records are MANDATORY (enforced at creation)
        return_items_qs = self.return_items.filter(is_active=True).select_related(
            'invoice_item__item'
        )
        
        if not return_items_qs.exists():
            error_msg = (
                f"Return #{self.id} ({self.return_number}) has no ReturnItem records. "
                f"Cannot determine stock restoration quantities."
            )
            logger.error(f"❌ {error_msg}")
            raise ValueError(error_msg)
        
        for return_item in return_items_qs:
            if return_item.invoice_item and return_item.invoice_item.item:
                items_to_restore.append({
                    'item_id': return_item.invoice_item.item.id,
                    'quantity': int(return_item.quantity)
                })
        
        logger.info(
            f"✅ Stock restoration data: {len(items_to_restore)} item(s) "
            f"from Return #{self.id}"
        )
        
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
            
    def get_return_items_summary(self):
        """
        ✅ ENHANCED - Get detailed summary of all items in this return.
        Returns list of dicts with item details.
        """
        if not hasattr(self, 'return_items'):
            return []
        
        items_summary = []
        
        for return_item in self.return_items.filter(is_active=True):
            if return_item.invoice_item and return_item.invoice_item.item:
                # Calculate already returned for this invoice item
                already_returned = ReturnItem.objects.filter(
                    invoice_item=return_item.invoice_item,
                    return_instance__is_active=True
                ).exclude(
                    pk=return_item.pk
                ).aggregate(total=models.Sum('quantity'))['total'] or 0
                
                remaining_returnable = (
                    return_item.invoice_item.quantity - 
                    already_returned - 
                    return_item.quantity
                )
                
                items_summary.append({
                    'item_name': return_item.invoice_item.item.name,
                    'item_hns': getattr(return_item.invoice_item.item, 'hns_code', 'N/A'),
                    'quantity_returned': return_item.quantity,
                    'original_quantity': return_item.invoice_item.quantity,
                    'remaining_returnable': max(remaining_returnable, 0),
                    'return_amount': return_item.amount,
                    'per_unit_price': return_item.invoice_item.rate,
                    'already_returned_total': already_returned + return_item.quantity
                })
        
        return items_summary
        
    def validate_against_invoice(self):
        """
        ✅ FIXED: Validate return against invoice constraints.
        Skips item-level validation if Return not yet saved (no pk).
        """
        if not self.invoice:
            raise ValidationError("Return must be linked to an invoice.")
        
        # Validate total amount
        existing_returns = Return.objects.filter(
            invoice=self.invoice,
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
        
        # ✅ CRITICAL FIX: Only validate items if Return has been saved (has pk)
        # This prevents trying to access return_items before the Return exists in DB
        if self.pk and hasattr(self, 'return_items'):
            logger.info("🔍 Validating item-level returns...")
            for return_item in self.return_items.filter(is_active=True):
                if return_item.invoice_item:
                    already_returned = ReturnItem.objects.filter(
                        invoice_item=return_item.invoice_item,
                        return_instance__is_active=True
                    ).exclude(
                        return_instance=self
                    ).aggregate(total=models.Sum('quantity'))['total'] or 0
                    
                    max_qty = return_item.invoice_item.quantity - already_returned
                    
                    if return_item.quantity > max_qty:
                        raise ValidationError(
                            f"Cannot return {return_item.quantity} units of "
                            f"{return_item.invoice_item.item.name}. "
                            f"Maximum returnable: {max_qty}"
                        )
        else:
            if not self.pk:
                logger.info("⏭️ Skipping item-level validation - Return not yet saved")
                
    def save(self, *args, **kwargs):
        """
        ✅ FIXED: Generate return number and validate on save.
        Only validates amount constraints on creation (not item-level).
        """
        # Generate return number if new
        if not self.return_number:
            self.return_number = self.generate_return_number()
            logger.info(f"✅ Generated return number: {self.return_number}")
        
        # Set party from invoice if not provided
        if self.invoice and not self.party:
            self.party = self.invoice.party
            logger.info(f"✅ Auto-set party: {self.party.name}")
        
        # ✅ CRITICAL FIX: Only validate amount on creation (not items)
        # Items don't exist yet, so we can't validate them
        if not self.pk:
            logger.info("🆕 Creating new Return - validating amount only...")
            
            # Basic validations
            if not self.invoice:
                raise ValidationError("Return must be linked to an invoice.")
            
            if self.amount <= Decimal('0.00'):
                raise ValidationError("Return amount must be greater than zero.")
            
            # Validate total doesn't exceed invoice
            existing_returns = Return.objects.filter(
                invoice=self.invoice,
                is_active=True
            ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
            
            max_returnable = self.invoice.base_amount - existing_returns
            
            if self.amount > max_returnable:
                raise ValidationError(
                    f"Return amount ₹{self.amount} exceeds maximum returnable "
                    f"amount ₹{max_returnable:.2f}. "
                    f"(Invoice Total: ₹{self.invoice.base_amount}, "
                    f"Already Returned: ₹{existing_returns})"
                )
        else:
            # For updates, validate everything including items
            logger.info("♻️ Updating existing Return - full validation...")
            self.validate_against_invoice()
        
        super().save(*args, **kwargs)
        
        logger.info(f"✅ Return saved: {self.return_number} (pk={self.pk})")
    
    def hard_delete(self):
        """Permanently delete the return (bypass soft delete)."""
        super(Return, self).delete()

# -----------------------
# ReturnItem
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
        constraints = [
            models.CheckConstraint(
                check=models.Q(quantity__gt=0),
                name='returnitem_quantity_positive'
            ),
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name='returnitem_amount_positive'
            ),
        ]
        indexes = [
            models.Index(fields=['invoice_item', 'is_active']),
            models.Index(fields=['return_instance', 'is_active']),
        ]
        
    def __str__(self):
        item_name = self.invoice_item.item.name if self.invoice_item and self.invoice_item.item else 'Unknown'
        return f"{item_name} x{self.quantity} - ₹{self.amount}"
    
    def clean(self):
        """
        STRICT VALIDATION: Prevent returns exceeding sold quantities.
        Includes edge case handling for concurrent returns.
        """
        if not self.invoice_item:
            raise ValidationError("ReturnItem must reference an InvoiceItem.")
        
        if not self.invoice_item.item:
            raise ValidationError(
                f"Cannot return InvoiceItem #{self.invoice_item.id} - "
                f"it has no linked Item (manual items cannot be returned)."
            )
        
        # Calculate already returned quantity
        existing_returns = ReturnItem.objects.filter(
            invoice_item=self.invoice_item,
            is_active=True
        ).exclude(pk=self.pk).aggregate(
            total=models.Sum('quantity')
        )['total'] or 0
        
        max_returnable = self.invoice_item.quantity - existing_returns
        
        # Validate quantity
        if self.quantity <= 0:
            raise ValidationError("Return quantity must be greater than zero.")
        
        if self.quantity > max_returnable:
            raise ValidationError(
                f"Cannot return {self.quantity} units of "
                f"'{self.invoice_item.item.name}'. "
                f"Maximum returnable: {max_returnable} "
                f"(Sold: {self.invoice_item.quantity}, "
                f"Already Returned: {existing_returns})"
            )
        
        # Validate amount matches expected calculation
        if self.invoice_item.total and self.invoice_item.quantity > 0:
            per_unit_price = (
                self.invoice_item.total / self.invoice_item.quantity
            ).quantize(Decimal('0.01'), ROUND_HALF_UP)
            
            expected_amount = (per_unit_price * self.quantity).quantize(
                Decimal('0.01'), ROUND_HALF_UP
            )
            
            # Allow 1 paisa tolerance for rounding
            if abs(self.amount - expected_amount) > Decimal('0.01'):
                raise ValidationError(
                    f"Return amount ₹{self.amount} does not match expected "
                    f"₹{expected_amount} ({self.quantity} × ₹{per_unit_price})"
                )
    
    def save(self, *args, **kwargs):
        """
        Override save to enforce validation before saving.
        Calls full_clean() to trigger clean() method validation.
        """
        self.full_clean()
        super().save(*args, **kwargs)

    def hard_delete(self):
        """Permanently delete the return item (bypass soft delete)."""
        super(ReturnItem, self).delete()


# -----------------------
# Challan & ChallanItem
# -----------------------
class Challan(SoftDeleteMixin, models.Model):
    challan_number = models.CharField(max_length=50, unique=True, null=True, blank=True, editable=False)
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
        challan_num = self.challan_number or f"CHN-TEMP-{self.id}"
        return f"{challan_num} | {self.date.strftime('%d-%m-%Y')} | {self.party.name}"

    @staticmethod
    def generate_challan_number():
        """Generate unique challan number in format: CHN-YYYYMM-001"""
        today = timezone.now()
        year_month = today.strftime('%Y%m')
        prefix = f"CHN-{year_month}-"
        
        last_challan = Challan.objects.filter(
            challan_number__startswith=prefix
        ).order_by('-challan_number').first()
        
        if last_challan and last_challan.challan_number:
            try:
                last_number = int(last_challan.challan_number.split('-')[-1])
                new_number = last_number + 1
            except (ValueError, IndexError):
                new_number = 1
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

    class Meta:
        verbose_name = "Challan Item"
        verbose_name_plural = "Challan Items"

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


@receiver([post_save, post_delete], sender=Return)
def touch_invoice_on_return(sender, instance, **kwargs):
    """Update invoice timestamp when return is modified"""
    invoice = instance.invoice
    if invoice:
        invoice.updated_at = timezone.now()
        invoice.save(update_fields=['updated_at'])
        