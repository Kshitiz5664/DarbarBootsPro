from django.apps import apps
from django.db import transaction
from django.db import models
from django.conf import settings
import re
from django.db import transaction

class Item(models.Model):
    name = models.CharField(max_length=255)
    hns_code = models.CharField(
        max_length=100, 
        unique=True, 
        verbose_name="HNS Code",
        null=True, 
        blank=True
    )
    price_retail = models.DecimalField(max_digits=10, decimal_places=2)
    price_wholesale = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=0)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, help_text="GST %")
    discount = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=0.00, 
        help_text="Discount %"
    )
    image = models.ImageField(upload_to='item_images/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Item'
        verbose_name_plural = 'Items'

    def __str__(self):
        return f"{self.name} ({self.hns_code})"  # ✅ FIXED: Added closing quote
    
    @property
    def is_low_stock(self):
        """Check if quantity is low (you can adjust the threshold)"""
        return self.quantity <= 10
    
    @property
    def price_with_gst(self):
        """Calculate wholesale price including GST"""
        return self.price_wholesale + (self.price_wholesale * self.gst_percent / 100)
    

def generate_hns_no_migration():
    import re

    prefix = "HSN"

    Item = apps.get_model('items', 'Item')  # <-- FIXED (no circular import)

    with transaction.atomic():
        last_item = (
            Item.objects
            .select_for_update()
            .filter(hns_code__startswith=prefix)
            .order_by('-id')
            .first()
        )

        if not last_item or not last_item.hns_code:
            return f"{prefix}-0001"

        match = re.search(r'(\d+)$', last_item.hns_code)
        last_num = int(match.group(1)) if match else 0
        next_num = last_num + 1

        return f"{prefix}-{next_num:04d}"
    
def hard_delete(self):
    super(Item, self).delete()

