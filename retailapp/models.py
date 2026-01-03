from decimal import Decimal
from django.db import models, transaction
from django.utils import timezone
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Sum

from items.models import Item
from core.mixins import SoftDeleteMixin


class RetailInvoice(SoftDeleteMixin, models.Model):
    """
    Retail (B2C) invoice: manual customer entry, auto invoice number,
    totals are derived from RetailInvoiceItem and RetailReturn.
    Enhanced with payment mode tracking and status management.
    """

    # Payment Mode Choices (includes UNPAID as a choice)
    class PaymentMode(models.TextChoices):
        UNPAID = 'UNPAID', 'Unpaid'
        CASH = 'CASH', 'Cash'
        UPI = 'UPI', 'UPI'
        CARD = 'CARD', 'Card'
        ONLINE = 'ONLINE', 'Online Banking'
        CHEQUE = 'CHEQUE', 'Cheque'
        OTHER = 'OTHER', 'Other'

    invoice_number = models.CharField(max_length=50, unique=True, editable=False)

    # Customer (manual)
    customer_name = models.CharField(max_length=255)
    customer_mobile = models.CharField(max_length=15, blank=True, null=True)

    date = models.DateField(default=timezone.now)

    base_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_gst = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_discount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    final_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    # Single payment field - if UNPAID then is_paid=False, else is_paid=True
    payment_mode = models.CharField(
        max_length=10,
        choices=PaymentMode.choices,
        default=PaymentMode.UNPAID,
        help_text="Select payment method (Unpaid or payment mode)"
    )
    
    payment_date = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Date when payment was completed"
    )
    
    transaction_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Transaction ID/Reference number for online payments"
    )

    notes = models.TextField(blank=True, null=True)

    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="retail_invoices_created"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="retail_invoices_updated"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-invoice_number"]
        verbose_name = "Retail Invoice"
        verbose_name_plural = "Retail Invoices"

    def __str__(self):
        return f"Retail Invoice {self.invoice_number}"

    # -------------------------
    # COMPUTED PROPERTY: is_paid (backward compatibility)
    # -------------------------
    @property
    def is_paid(self):
        """
        Computed property: invoice is paid if payment_mode is NOT 'UNPAID'
        This maintains backward compatibility with existing code.
        """
        return self.payment_mode != self.PaymentMode.UNPAID
    
    # -------------------------
    # HELPER METHOD: Mark as Unpaid
    # -------------------------
    def mark_as_unpaid(self, clear_details=True):
        """
        Helper method to mark invoice as unpaid.
        Useful for correcting accidental payment mode selection.
        
        Args:
            clear_details: If True, clears payment_date and transaction_reference
        """
        self.payment_mode = self.PaymentMode.UNPAID
        if clear_details:
            self.payment_date = None
            self.transaction_reference = None
        self.save()
    
    # -------------------------
    # HELPER METHOD: Update Payment
    # -------------------------
    def update_payment(self, payment_mode, transaction_ref=None):
        """
        Helper method to update payment details safely.
        
        Args:
            payment_mode: One of PaymentMode choices
            transaction_ref: Optional transaction reference
        """
        if payment_mode not in dict(self.PaymentMode.choices):
            raise ValidationError(f"Invalid payment mode: {payment_mode}")
        
        self.payment_mode = payment_mode
        
        if payment_mode == self.PaymentMode.UNPAID:
            # Mark as unpaid
            self.payment_date = None
            self.transaction_reference = None
        else:
            # Mark as paid
            if not self.payment_date:
                self.payment_date = timezone.now()
            if transaction_ref:
                self.transaction_reference = transaction_ref
        
        self.save()

    # -------------------------
    # ATOMIC, RACE-SAFE INVOICE NUMBER
    # -------------------------
    @classmethod
    def generate_invoice_number(cls):
        """
        Generate unique invoice number in format RTL-YYYYMMDD-XXX
        Uses a DB-level lock within a transaction to avoid race conditions.
        """
        today = timezone.now()
        prefix = today.strftime("RTL-%Y%m%d-")

        with transaction.atomic():
            last = (
                cls.objects.select_for_update()
                .filter(invoice_number__startswith=prefix)
                .order_by("-invoice_number")
                .first()
            )
            if last and last.invoice_number:
                try:
                    seq = int(last.invoice_number.split("-")[-1]) + 1
                except Exception:
                    seq = 1
            else:
                seq = 1

            return f"{prefix}{seq:03d}"

    def clean(self):
        """
        Validation rules:
        - If payment_mode is UNPAID, clear payment details
        - If payment_mode is not UNPAID, auto-set payment date if missing
        """
        super().clean()
        
        # If UNPAID, clear payment-related fields
        if self.payment_mode == self.PaymentMode.UNPAID:
            self.payment_date = None
            self.transaction_reference = None
        
        # If any payment mode selected (not UNPAID), auto-set payment date
        elif not self.payment_date:
            self.payment_date = timezone.now()

    def save(self, *args, **kwargs):
        # Ensure invoice_number set atomically on first save
        if not self.invoice_number:
            self.invoice_number = RetailInvoice.generate_invoice_number()
        
        # Run validations
        self.full_clean()
        
        super().save(*args, **kwargs)

    # -------------------------
    # TOTAL RECALCULATION (items + gst - discount - returns)
    # -------------------------
    def recalculate_totals(self):
        """
        Recompute invoice totals from active invoice items and active returns.
        final_amount = sum(base_amount) + sum(gst_amount) - sum(discount_amount) - sum(returns)
        """
        items_qs = self.retail_items.filter(is_active=True)
        base = items_qs.aggregate(t=Sum("base_amount"))["t"] or Decimal("0.00")
        gst = items_qs.aggregate(t=Sum("gst_amount"))["t"] or Decimal("0.00")
        discount = items_qs.aggregate(t=Sum("discount_amount"))["t"] or Decimal("0.00")

        returns_total = (
            self.retail_returns.filter(is_active=True).aggregate(t=Sum("amount"))["t"] or Decimal("0.00")
        )

        final = base + gst - discount - returns_total

        # Quantize and persist
        self.base_amount = Decimal(base).quantize(Decimal("0.01"))
        self.total_gst = Decimal(gst).quantize(Decimal("0.01"))
        self.total_discount = Decimal(discount).quantize(Decimal("0.01"))
        self.final_amount = Decimal(max(final, Decimal("0.00"))).quantize(Decimal("0.01"))

        # Update fields to avoid clobbering other changes
        self.save(update_fields=[
            "base_amount", "total_gst", "total_discount",
            "final_amount", "updated_at"
        ])


class RetailInvoiceItem(SoftDeleteMixin, models.Model):
    """
    Line item for retail invoice.
    Supports linking to existing Item OR manual_item_name (free-text).
    Prices/deductions computed on save.
    """

    invoice = models.ForeignKey(RetailInvoice, on_delete=models.CASCADE, related_name="retail_items")
    item = models.ForeignKey(Item, on_delete=models.SET_NULL, null=True, blank=True)
    manual_item_name = models.CharField(max_length=255, blank=True, null=True)

    quantity = models.PositiveIntegerField(default=1)
    rate = models.DecimalField(max_digits=14, decimal_places=2)

    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))

    base_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    gst_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="retail_items_created"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="retail_items_updated"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Retail Invoice Item"
        verbose_name_plural = "Retail Invoice Items"

    @property
    def display_name(self):
        if self.item:
            return self.item.name
        return self.manual_item_name or "Manual Item"

    def clean(self):
        """
        Business validations:
        - rate must be non-negative
        - quantity must be positive
        """
        if self.rate is None or Decimal(self.rate) < 0:
            raise ValidationError({"rate": "Rate must be a non-negative number."})
        if self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be at least 1."})

    def save(self, *args, **kwargs):
        # Ensure business validations run
        self.full_clean()

        qty = Decimal(self.quantity)
        rate = Decimal(self.rate)

        # Base price = qty * rate
        self.base_amount = (qty * rate).quantize(Decimal("0.01"))
        # GST = qty * rate * gst_percent/100
        self.gst_amount = (qty * rate * (Decimal(self.gst_percent) / Decimal("100"))).quantize(Decimal("0.01"))
        # Discount = qty * rate * discount_percent/100
        self.discount_amount = (qty * rate * (Decimal(self.discount_percent) / Decimal("100"))).quantize(Decimal("0.01"))
        # Final line total
        self.total = (self.base_amount + self.gst_amount - self.discount_amount).quantize(Decimal("0.01"))

        super().save(*args, **kwargs)


class RetailReturn(SoftDeleteMixin, models.Model):
    """
    Retail return against a RetailInvoiceItem.
    Supports automatic amount calculation when returning an existing invoice item,
    and manual returns (item can be None) — for manual returns you must provide amount.
    """

    invoice = models.ForeignKey(RetailInvoice, on_delete=models.CASCADE, related_name="retail_returns")
    item = models.ForeignKey(RetailInvoiceItem, on_delete=models.SET_NULL, null=True, blank=True)

    return_date = models.DateField(default=timezone.now)
    quantity = models.PositiveIntegerField(default=1)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    reason = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to="retail_returns/", blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="retail_returns_created"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="retail_returns_updated"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-return_date"]
        verbose_name = "Retail Return"
        verbose_name_plural = "Retail Returns"

    def clean(self):
        """
        Validations:
        - If item linked: cannot return more than purchased minus earlier returns.
        - If item is None (manual return): amount must be provided and > 0.
        """
        if self.item:
            # sum of previously returned qty for this invoice item (active ones)
            prior_returns_qty = (
                RetailReturn.objects.filter(item=self.item, is_active=True)
                .exclude(pk=self.pk)
                .aggregate(s=Sum("quantity"))["s"] or 0
            )
            allowable = max(self.item.quantity - int(prior_returns_qty), 0)
            if self.quantity > allowable:
                raise ValidationError({
                    "quantity": f"Cannot return {self.quantity} units. Only {allowable} unit(s) available for return."
                })
        else:
            # Manual return requires positive amount (caller must set amount)
            if (self.amount is None) or (Decimal(self.amount) <= Decimal("0.00")):
                raise ValidationError({"amount": "Manual returns must supply a positive amount."})

    def save(self, *args, **kwargs):
        # Run validations
        self.full_clean()

        # If returning an existing invoice item, compute amount automatically using per unit price
        if self.item:
            if self.item.quantity and self.item.quantity > 0:
                # compute the per-unit net amount using line total / quantity
                per_unit = (Decimal(self.item.total) / Decimal(self.item.quantity)).quantize(Decimal("0.01"))
                self.amount = (per_unit * Decimal(self.quantity)).quantize(Decimal("0.01"))
            else:
                # defensive fallback: compute from item's rate/gst/discount if available
                per_unit = (Decimal(self.item.rate) + (Decimal(self.item.rate) * Decimal(self.item.gst_percent) / Decimal("100"))
                            - (Decimal(self.item.rate) * Decimal(self.item.discount_percent) / Decimal("100")))
                self.amount = (per_unit * Decimal(self.quantity)).quantize(Decimal("0.01"))

        # Persist
        super().save(*args, **kwargs)


# -----------------------
# SIGNALS: keep invoice totals consistent
# -----------------------
@receiver([post_save, post_delete], sender=RetailInvoiceItem)
def retail_item_changed(sender, instance, **kwargs):
    """
    Recalculate invoice totals whenever invoice items change.
    """
    invoice = instance.invoice
    if invoice:
        try:
            invoice.recalculate_totals()
        except Exception:
            # swallow to avoid breaking save flow; in production log this.
            pass


@receiver([post_save, post_delete], sender=RetailReturn)
def retail_return_changed(sender, instance, **kwargs):
    """
    Recalculate invoice totals whenever a return is created/updated/deleted.
    This ensures totals always equal items +/- returns.
    """
    invoice = instance.invoice
    if invoice:
        try:
            invoice.recalculate_totals()
        except Exception:
            pass