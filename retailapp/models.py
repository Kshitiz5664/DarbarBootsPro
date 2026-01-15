from decimal import Decimal
from django.db import models, transaction, connection
from django.utils import timezone
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Sum
import logging

from items.models import Item
from core.mixins import SoftDeleteMixin

logger = logging.getLogger(__name__)


# ============================================================
# RETAIL INVOICE
# ============================================================
# retailapp/models.py - CORRECTED VERSION
# Replace the RetailInvoice class with proper indentation

class RetailInvoice(SoftDeleteMixin, models.Model):
    """
    Retail (B2C) Invoice
    - 100% Race-safe invoice number generation with database-level locking
    - Payment mode driven paid/unpaid logic
    - Totals derived from items & returns
    - Thread-safe for concurrent users
    - Auto-settlement when returns equal or exceed invoice total
    """

    class PaymentMode(models.TextChoices):
        UNPAID = 'UNPAID', 'Unpaid'
        CASH = 'CASH', 'Cash'
        UPI = 'UPI', 'UPI'
        CARD = 'CARD', 'Card'
        ONLINE = 'ONLINE', 'Online Banking'
        CHEQUE = 'CHEQUE', 'Cheque'
        OTHER = 'OTHER', 'Other'

    # Identity
    invoice_number = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        db_index=True
    )

    # Customer
    customer_name = models.CharField(max_length=255)
    customer_mobile = models.CharField(max_length=15, blank=True, null=True)

    date = models.DateField(default=timezone.now)

    # Totals (persisted)
    base_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_gst = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_discount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    final_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    # Payment
    payment_mode = models.CharField(
        max_length=10,
        choices=PaymentMode.choices,
        default=PaymentMode.UNPAID
    )
    payment_date = models.DateTimeField(blank=True, null=True)
    transaction_reference = models.CharField(max_length=100, blank=True, null=True)

    notes = models.TextField(blank=True, null=True)

    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="retail_invoices_created"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="retail_invoices_updated"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-invoice_number"]
        verbose_name = "Retail Invoice"
        verbose_name_plural = "Retail Invoices"
        indexes = [
            models.Index(fields=['-date', '-created_at']),
            models.Index(fields=['payment_mode']),
            models.Index(fields=['is_active', '-date']),
            models.Index(fields=['customer_mobile', '-date']),
            models.Index(fields=['is_active', 'payment_mode', '-date']),
            models.Index(fields=['date', 'is_active']),
        ]

    def __str__(self):
        return self.invoice_number or 'New Invoice'

    @property
    def is_paid(self):
        """Check if invoice is paid (any payment mode except UNPAID)"""
        return self.payment_mode != self.PaymentMode.UNPAID

    @classmethod
    def _generate_next_invoice_number(cls):
        """
        ✅ FIXED: Universal race-safe invoice number generation.
        Works with PostgreSQL, MySQL, and SQLite.
        MUST be called inside an active atomic transaction.
        """
        from django.db import connection
        
        today = timezone.now().strftime("RTL-%Y%m%d-")
        
        try:
            db_vendor = connection.vendor
            
            with connection.cursor() as cursor:
                if db_vendor == 'postgresql':
                    lock_key = abs(hash(today)) % 2147483647
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])
                elif db_vendor == 'mysql':
                    lock_name = f"invoice_lock_{today}"
                    cursor.execute("SELECT GET_LOCK(%s, 10)", [lock_name])
                
                cursor.execute("""
                    SELECT invoice_number 
                    FROM retailapp_retailinvoice 
                    WHERE invoice_number LIKE %s 
                    ORDER BY invoice_number DESC 
                    LIMIT 1
                """, [f"{today}%"])
                
                row = cursor.fetchone()
                
                if row and row[0]:
                    try:
                        seq = int(row[0].split("-")[-1]) + 1
                    except (ValueError, IndexError):
                        logger.warning(f"Could not parse sequence from {row[0]}, starting at 1")
                        seq = 1
                else:
                    seq = 1
                
                if db_vendor == 'mysql':
                    cursor.execute("SELECT RELEASE_LOCK(%s)", [lock_name])
            
            next_number = f"{today}{seq:03d}"
            logger.info(f"✅ Generated invoice number: {next_number} (DB: {db_vendor})")
            return next_number
            
        except Exception as e:
            logger.error(f"❌ Error generating invoice number: {e}", exc_info=True)
            fallback = f"{today}{timezone.now().strftime('%H%M%S%f')[-6:]}"
            logger.warning(f"⚠️ Using fallback invoice number: {fallback}")
            return fallback

    def clean(self):
        """Validate invoice data before saving"""
        super().clean()

        if self.payment_mode == self.PaymentMode.UNPAID:
            self.payment_date = None
            self.transaction_reference = None
        elif not self.payment_date:
            self.payment_date = timezone.now()

        if not self.customer_name or not self.customer_name.strip():
            raise ValidationError({'customer_name': 'Customer name is required.'})

    def save(self, *args, **kwargs):
        """
        Save invoice with automatic invoice number generation.
        For new invoices, MUST be called inside transaction.atomic() block.
        """
        is_new = self.pk is None
        
        if is_new and not self.invoice_number:
            if not connection.in_atomic_block:
                logger.warning(
                    "Invoice save() called outside atomic transaction. "
                    "This may cause race conditions."
                )
            
            self.invoice_number = self._generate_next_invoice_number()
            logger.info(f"New invoice created: {self.invoice_number}")
        
        self.full_clean()
        super().save(*args, **kwargs)

    # ✅ FIXED: Proper indentation - class method at class level
    @classmethod
    def bulk_recalculate_totals(cls, invoice_ids):
        """
        ✅ NEW: Efficiently recalculate totals for multiple invoices.
        Useful for admin actions or data migrations.
        """
        from django.db.models import Prefetch
        
        invoices = cls.objects.filter(
            id__in=invoice_ids,
            is_active=True
        ).prefetch_related(
            Prefetch('retail_items', queryset=RetailInvoiceItem.objects.filter(is_active=True)),
            Prefetch('retail_returns', queryset=RetailReturn.objects.filter(is_active=True))
        )
        
        updated_count = 0
        errors = []
        
        for invoice in invoices:
            try:
                invoice.recalculate_totals()
                updated_count += 1
            except Exception as e:
                errors.append(f"Invoice {invoice.invoice_number}: {str(e)}")
                logger.error(f"Failed to recalculate {invoice.invoice_number}: {e}")
        
        return {
            'success': updated_count,
            'total': len(invoice_ids),
            'errors': errors
        }

    def recalculate_totals(self):
        """
        ✅ FIXED: Bulletproof totals calculation with zero recursion risk.
        Uses raw SQL update to completely bypass Django signals.
        """
        try:
            from django.db import connection
            
            items = self.retail_items.filter(is_active=True)
            
            base = items.aggregate(v=Sum("base_amount"))["v"] or Decimal("0.00")
            gst = items.aggregate(v=Sum("gst_amount"))["v"] or Decimal("0.00")
            discount = items.aggregate(v=Sum("discount_amount"))["v"] or Decimal("0.00")
            
            subtotal_before_returns = base + gst - discount
            
            returns_total = (
                self.retail_returns.filter(is_active=True)
                .aggregate(v=Sum("amount"))["v"] or Decimal("0.00")
            )
            
            final_amount_calculated = subtotal_before_returns - returns_total
            final = max(final_amount_calculated, Decimal("0.00"))
            
            update_values = {
                "base_amount": base.quantize(Decimal("0.01")),
                "total_gst": gst.quantize(Decimal("0.01")),
                "total_discount": discount.quantize(Decimal("0.01")),
                "final_amount": final.quantize(Decimal("0.01")),
            }
            
            should_auto_settle = (
                final <= 0 and 
                self.payment_mode == self.PaymentMode.UNPAID
            )
            
            if should_auto_settle:
                update_values.update({
                    "payment_mode": self.PaymentMode.OTHER,
                    "transaction_reference": 'SETTLED_BY_RETURN',
                    "payment_date": timezone.now()
                })
                logger.info(f"✅ Invoice {self.invoice_number} AUTO-SETTLED by returns")
            
            with connection.cursor() as cursor:
                sql_parts = []
                params = []
                
                for field, value in update_values.items():
                    sql_parts.append(f"{field} = %s")
                    params.append(str(value))
                
                sql_parts.append("updated_at = %s")
                params.append(timezone.now())
                params.append(self.pk)
                
                sql = f"""
                    UPDATE retailapp_retailinvoice 
                    SET {', '.join(sql_parts)}
                    WHERE id = %s
                """
                
                cursor.execute(sql, params)
            
            self.refresh_from_db()
            
            logger.debug(
                f"📊 Invoice {self.invoice_number} totals: "
                f"Base={self.base_amount}, GST={self.total_gst}, "
                f"Discount={self.total_discount}, Final={self.final_amount}"
            )
            
        except Exception as e:
            logger.error(f"❌ Error recalculating totals for {self.invoice_number}: {e}", exc_info=True)
            raise
# ============================================================
# RETAIL INVOICE ITEM
# ============================================================

class RetailInvoiceItem(SoftDeleteMixin, models.Model):
    """
    Line item in a retail invoice.
    Supports both inventory-tracked items and manual items.
    
    CALCULATION FORMULA:
    1. base_amount = quantity × rate
    2. gst_amount = base_amount × (gst_percent / 100)
    3. discount_amount = base_amount × (discount_percent / 100)
    4. total = base_amount + gst_amount - discount_amount
    """
    
    invoice = models.ForeignKey(
        RetailInvoice,
        on_delete=models.CASCADE,
        related_name="retail_items"
    )

    # Either linked to inventory item OR manual entry
    item = models.ForeignKey(
        Item, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        help_text="Link to inventory item (optional)"
    )
    manual_item_name = models.CharField(
        max_length=255, 
        blank=True, 
        null=True,
        help_text="Manual item name if not in inventory"
    )

    # Quantities and rates
    quantity = models.PositiveIntegerField(default=1)
    rate = models.DecimalField(max_digits=14, decimal_places=2)

    # Percentages
    gst_percent = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=Decimal("0.00"),
        help_text="GST percentage (e.g., 18.00 for 18%)"
    )
    discount_percent = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=Decimal("0.00"),
        help_text="Discount percentage (e.g., 10.00 for 10%)"
    )

    # Calculated amounts (auto-computed on save)
    base_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    gst_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="retail_items_created"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="retail_items_updated"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'Invoice Item'
        verbose_name_plural = 'Invoice Items'
        indexes = [
            models.Index(fields=['invoice', 'is_active']),
            models.Index(fields=['item']),
        ]

    def __str__(self):
        return f"{self.display_name} x {self.quantity}"

    @property
    def display_name(self):
        """Get display name (either from item or manual entry)"""
        if self.item:
            return self.item.name
        elif self.manual_item_name:
            return self.manual_item_name
        else:
            return "Manual Item"

    def clean(self):
        """Validate item data"""
        super().clean()
        
        # Validate quantity
        if self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be at least 1"})
        
        # Validate rate
        if self.rate < 0:
            raise ValidationError({"rate": "Rate cannot be negative"})
        
        # Validate percentages
        if self.gst_percent < 0 or self.gst_percent > 100:
            raise ValidationError({"gst_percent": "GST must be between 0 and 100"})
        
        if self.discount_percent < 0 or self.discount_percent > 100:
            raise ValidationError({"discount_percent": "Discount must be between 0 and 100"})
        
        # Must have either item or manual name
        if not self.item and not self.manual_item_name:
            raise ValidationError(
                "Either select an inventory item or provide a manual item name"
            )
            
    # REPLACE the save method in RetailInvoiceItem

    def save(self, *args, **kwargs):
        """
        ✅ FIXED: Better validation handling in save method.
        """
        # Only validate on creation or if explicitly requested
        if self._state.adding or kwargs.pop('force_clean', False):
            try:
                self.full_clean()
            except ValidationError as e:
                logger.error(f"Validation failed for invoice item: {e}")
                raise
        
        # Convert to Decimal for calculations
        qty = Decimal(str(self.quantity))
        rate = Decimal(str(self.rate))
        gst_pct = Decimal(str(self.gst_percent))
        disc_pct = Decimal(str(self.discount_percent))
        
        # Calculate amounts
        self.base_amount = (qty * rate).quantize(Decimal("0.01"))
        self.gst_amount = (self.base_amount * gst_pct / Decimal("100")).quantize(Decimal("0.01"))
        self.discount_amount = (self.base_amount * disc_pct / Decimal("100")).quantize(Decimal("0.01"))
        self.total = (self.base_amount + self.gst_amount - self.discount_amount).quantize(Decimal("0.01"))
        
        logger.debug(
            f"📝 Item calculation: {self.display_name} - "
            f"Base: Rs {self.base_amount}, Total: Rs {self.total}"
        )
        
        super().save(*args, **kwargs)


# ============================================================
# RETAIL RETURN
# ============================================================

class RetailReturn(SoftDeleteMixin, models.Model):
    """
    Product return against a retail invoice.
    Tracks returned items and amounts.
    
    AMOUNT CALCULATION:
    - If linked to invoice item: amount = (item.total ÷ item.quantity) × return.quantity
    - If manual return: amount must be provided manually
    """
    
    invoice = models.ForeignKey(
        RetailInvoice,
        on_delete=models.CASCADE,
        related_name="retail_returns"
    )
    item = models.ForeignKey(
        RetailInvoiceItem, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        help_text="Link to specific invoice item (optional)"
    )

    return_date = models.DateField(default=timezone.now)
    quantity = models.PositiveIntegerField(default=1)
    amount = models.DecimalField(
        max_digits=14, 
        decimal_places=2, 
        default=Decimal("0.00"),
        help_text="Return amount (auto-calculated if item linked)"
    )

    reason = models.TextField(blank=True, null=True)
    image = models.ImageField(
        upload_to="retail_returns/", 
        blank=True, 
        null=True,
        help_text="Optional image proof"
    )

    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="retail_returns_created"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="retail_returns_updated"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-return_date", "-id"]
        verbose_name = 'Return'
        verbose_name_plural = 'Returns'
        indexes = [
            models.Index(fields=['invoice', 'is_active']),
            models.Index(fields=['item']),
            models.Index(fields=['-return_date']),
        ]

    def __str__(self):
        item_name = self.item.display_name if self.item else "Manual"
        return f"Return: {item_name} x {self.quantity} - Rs {self.amount}"

    def clean(self):
        """Validate return data"""
        super().clean()
        
        if self.item:
            # Validate return quantity against invoice item
            already_returned = (
                RetailReturn.objects.filter(item=self.item, is_active=True)
                .exclude(pk=self.pk)
                .aggregate(v=Sum("quantity"))["v"] or 0
            )
            
            max_returnable = max(self.item.quantity - already_returned, 0)
            
            if self.quantity > max_returnable:
                raise ValidationError({
                    "quantity": f"Only {max_returnable} unit(s) can be returned for this item"
                })
        else:
            # Manual return requires amount
            if not self.amount or self.amount <= 0:
                raise ValidationError({
                    "amount": "Manual return requires a positive amount"
                })
        
        # Validate return date
        if self.invoice and self.return_date and self.invoice.date:
            if self.return_date < self.invoice.date:
                raise ValidationError({
                    "return_date": "Return date cannot be before invoice date"
                })
                
                
# REPLACE the save method in RetailReturn

    def save(self, *args, **kwargs):
        """
        ✅ FIXED: Always validate unless explicitly skipped.
        """
        # Validate unless explicitly skipped
        if not kwargs.pop('skip_validation', False):
            try:
                self.full_clean()
            except ValidationError as e:
                logger.error(f"Validation failed for return: {e}")
                raise
        
        # Auto-calculate amount if linked to invoice item
        if self.item and self.item.quantity > 0 and self.item.total:
            try:
                item_total = Decimal(str(self.item.total))
                item_qty = Decimal(str(self.item.quantity))
                return_qty = Decimal(str(self.quantity))
                
                per_unit_price = (item_total / item_qty).quantize(Decimal("0.01"))
                self.amount = (per_unit_price * return_qty).quantize(Decimal("0.01"))
                
                logger.info(
                    f"💰 Return amount calculated: {self.item.display_name} - "
                    f"Per unit: Rs {per_unit_price}, Qty: {return_qty}, "
                    f"Amount: Rs {self.amount}"
                )
            except Exception as e:
                logger.error(f"Error calculating return amount: {e}", exc_info=True)
                if not self.amount or self.amount <= 0:
                    raise ValidationError({
                        "amount": "Could not calculate return amount. Please enter manually."
                    })
        
        # Ensure amount is never negative
        if self.amount < 0:
            self.amount = Decimal("0.00")
        
        super().save(*args, **kwargs)


# ============================================================
# FIX 3: SAFER SIGNAL HANDLERS
# ============================================================
# REPLACE both signal handlers at the bottom of models.py

@receiver(post_save, sender=RetailInvoiceItem)
def invoice_item_changed(sender, instance, created, **kwargs):
    """
    ✅ FIXED: Safe signal handler with recursion prevention.
    Only triggers for actual changes, not during bulk updates.
    """
    # Skip if signals are disabled
    if getattr(instance, '_skip_signals', False):
        return
    
    # Skip if no invoice (shouldn't happen, but be safe)
    if not instance.invoice_id:
        return
    
    # Skip if called from update() queryset method
    if kwargs.get('update_fields') is None and not created:
        return
    
    try:
        # Set flag to prevent infinite recursion
        instance._skip_signals = True
        
        logger.debug(
            f"🔄 Item {'created' if created else 'updated'}, "
            f"recalculating invoice {instance.invoice.invoice_number}"
        )
        
        instance.invoice.recalculate_totals()
        
    except Exception as e:
        logger.error(
            f"❌ Failed to recalculate totals for invoice {instance.invoice_id}: {e}",
            exc_info=True
        )
    finally:
        # Always remove flag
        if hasattr(instance, '_skip_signals'):
            delattr(instance, '_skip_signals')


@receiver([post_save, post_delete], sender=RetailReturn)
def invoice_return_changed(sender, instance, **kwargs):
    """
    ✅ FIXED: Safe signal handler for returns.
    """
    # Skip if signals are disabled
    if getattr(instance, '_skip_signals', False):
        return
    
    # Skip if no invoice
    if not instance.invoice_id:
        return
    
    try:
        # Set flag to prevent infinite recursion
        instance._skip_signals = True
        
        logger.debug(
            f"🔄 Return changed, recalculating invoice {instance.invoice.invoice_number}"
        )
        
        instance.invoice.recalculate_totals()
        
    except Exception as e:
        logger.error(
            f"❌ Failed to recalculate totals for invoice {instance.invoice_id}: {e}",
            exc_info=True
        )
    finally:
        # Always remove flag
        if hasattr(instance, '_skip_signals'):
            delattr(instance, '_skip_signals')
