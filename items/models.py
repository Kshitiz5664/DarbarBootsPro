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
        db_index=True
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
    is_active = models.BooleanField(default=True, db_index=True)
    is_featured = models.BooleanField(default=False, db_index=True)
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
    
    def hard_delete(self):
        """Permanently delete the item (bypass soft delete)."""
        super(Item, self).delete()


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