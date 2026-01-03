from django.apps import apps
from django.db import transaction, models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
import re


class Item(models.Model):
    """
    Inventory item model with retail/wholesale pricing, GST, and soft-delete support.
    """
    name = models.CharField(max_length=255, db_index=True)
    hns_code = models.CharField(
        max_length=100, 
        unique=True, 
        verbose_name="HNS Code",
        null=True, 
        blank=True,
        db_index=True,
        editable=False  # ✅ FIXED: Make HNS code non-editable
    )
    price_retail = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    price_wholesale = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    quantity = models.PositiveIntegerField(default=0)
    gst_percent = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        help_text="GST %",
        validators=[MinValueValidator(0), MaxValueValidator(50)]
    )
    discount = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=0.00, 
        help_text="Discount %",
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    image = models.ImageField(
        upload_to='item_images/', 
        null=True, 
        blank=True,
        help_text="Product image (max 5MB)"
    )
    is_active = models.BooleanField(
        default=True, 
        db_index=True,
        help_text="Active items appear in invoice creation forms"
    )
    is_featured = models.BooleanField(
        default=False, 
        db_index=True,
        help_text="Featured items appear on dashboard/homepage"
    )
    is_deleted = models.BooleanField(default=False, db_index=True)
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="items_created"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="items_updated"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Item'
        verbose_name_plural = 'Items'
        indexes = [
            models.Index(fields=['is_active', 'is_deleted', '-is_featured']),
            models.Index(fields=['hns_code']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.name} ({self.hns_code})"
    
    def clean(self):
        """Validate business logic constraints."""
        super().clean()
        
        if self.price_wholesale and self.price_retail:
            if self.price_wholesale > self.price_retail:
                raise ValidationError({
                    'price_wholesale': 'Wholesale price cannot exceed retail price.'
                })
    
    @property
    def is_low_stock(self):
        """Check if quantity is low (threshold: 10 units)."""
        return self.quantity <= 10
    
    @property
    def is_out_of_stock(self):
        """Check if item is out of stock."""
        return self.quantity == 0
    
    @property
    def price_with_gst(self):
        """Calculate wholesale price including GST."""
        if self.price_wholesale and self.gst_percent:
            return self.price_wholesale + (self.price_wholesale * self.gst_percent / 100)
        return self.price_wholesale
    
    @property
    def discounted_price_retail(self):
        """Calculate retail price after discount."""
        if self.price_retail and self.discount:
            return self.price_retail - (self.price_retail * self.discount / 100)
        return self.price_retail
    
    @property
    def discounted_price_wholesale(self):
        """Calculate wholesale price after discount."""
        if self.price_wholesale and self.discount:
            return self.price_wholesale - (self.price_wholesale * self.discount / 100)
        return self.price_wholesale
    
    # ✅ NEW: Inventory Management Methods
    def deduct_stock(self, quantity, invoice_type='retail'):
        """
        Deduct stock when invoice is created.
        
        Args:
            quantity (int): Quantity to deduct
            invoice_type (str): 'retail' or 'wholesale'
        
        Raises:
            ValidationError: If insufficient stock
        """
        if quantity <= 0:
            raise ValidationError(f"Quantity must be positive. Got: {quantity}")
        
        if self.quantity < quantity:
            raise ValidationError(
                f"Insufficient stock for {self.name}. "
                f"Available: {self.quantity}, Requested: {quantity}"
            )
        
        self.quantity -= quantity
        self.save(update_fields=['quantity', 'updated_at'])
        
        # Log the transaction
        self._log_stock_movement(
            quantity=-quantity,
            movement_type=f'{invoice_type}_sale',
            notes=f"Stock deducted for {invoice_type} invoice"
        )
    
    def add_stock(self, quantity, reason='return'):
        """
        Add stock when items are returned or restocked.
        
        Args:
            quantity (int): Quantity to add
            reason (str): Reason for stock addition ('return', 'restock', 'adjustment')
        """
        if quantity <= 0:
            raise ValidationError(f"Quantity must be positive. Got: {quantity}")
        
        self.quantity += quantity
        self.save(update_fields=['quantity', 'updated_at'])
        
        # Log the transaction
        self._log_stock_movement(
            quantity=quantity,
            movement_type=reason,
            notes=f"Stock added due to {reason}"
        )
    
    def _log_stock_movement(self, quantity, movement_type, notes=''):
        """
        Log stock movements for audit trail.
        Creates StockMovement record if the model exists.
        """
        try:
            StockMovement = apps.get_model('items', 'StockMovement')
            StockMovement.objects.create(
                item=self,
                quantity=quantity,
                movement_type=movement_type,
                notes=notes
            )
        except LookupError:
            # StockMovement model doesn't exist yet
            pass
    
    def hard_delete(self):
        """Permanently delete the item (bypass soft delete)."""
        super(Item, self).delete()


class StockMovement(models.Model):
    """
    Track all inventory movements for audit trail.
    """
    MOVEMENT_TYPES = [
        ('retail_sale', 'Retail Sale'),
        ('wholesale_sale', 'Wholesale Sale'),
        ('return', 'Return'),
        ('restock', 'Restock'),
        ('adjustment', 'Manual Adjustment'),
        ('damaged', 'Damaged/Lost'),
    ]
    
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='stock_movements'
    )
    quantity = models.IntegerField(
        help_text="Positive for additions, negative for deductions"
    )
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="stock_movements_created"
    )
    
    # Reference to invoice if applicable
    invoice_id = models.PositiveIntegerField(null=True, blank=True)
    invoice_type = models.CharField(
        max_length=10,
        choices=[('retail', 'Retail'), ('wholesale', 'Wholesale')],
        null=True,
        blank=True
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Stock Movement'
        verbose_name_plural = 'Stock Movements'
        indexes = [
            models.Index(fields=['item', '-created_at']),
            models.Index(fields=['movement_type', '-created_at']),
        ]
    
    def __str__(self):
        sign = '+' if self.quantity > 0 else ''
        return f"{self.item.name}: {sign}{self.quantity} ({self.movement_type})"


def generate_hns_no_migration():
    """
    Generate unique HNS code with format: HSN-XXXX
    Thread-safe implementation using database-level locking.
    """
    prefix = "HSN"
    
    # Get Item model without circular import
    Item = apps.get_model('items', 'Item')

    with transaction.atomic():
        # Lock the table for safe concurrent access
        last_item = (
            Item.objects
            .select_for_update()
            .filter(hns_code__startswith=prefix, hns_code__isnull=False)
            .order_by('-id')
            .first()
        )

        if not last_item or not last_item.hns_code:
            return f"{prefix}-0001"

        # Extract the numeric part from the last HNS code
        match = re.search(r'(\d+)$', last_item.hns_code)
        last_num = int(match.group(1)) if match else 0
        next_num = last_num + 1

        return f"{prefix}-{next_num:04d}"
    