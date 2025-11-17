from .models import Item
from django.contrib import admin
from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from .models import Item


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    """Advanced admin configuration for Item model with soft-delete handling and visual cues."""

    # ---------- DISPLAY SETTINGS ----------
    list_display = [
        'name',
        'hns_code',
        'price_retail',
        'price_wholesale',
        'quantity',
        'gst_percent',
        'discount',
        'stock_status',
        'is_active',
        'is_featured',
        'image_preview',
        'updated_at',
    ]
    list_filter = ['is_active', 'is_featured', 'is_deleted', 'created_at']
    search_fields = ['name', 'hns_code']
    list_editable = [
        'price_retail',
        'price_wholesale',
        'quantity',
        'is_active',
        'is_featured',
    ]
    readonly_fields = [
        'created_at',
        'updated_at',
        'created_by',
        'updated_by',
        'image_preview',
    ]

    # ---------- FIELD GROUPING ----------
    fieldsets = (
        (_('Basic Information'), {
            'fields': ('name', 'hns_code', 'image', 'image_preview'),
        }),
        (_('Pricing'), {
            'fields': ('price_retail', 'price_wholesale', 'gst_percent', 'discount'),
        }),
        (_('Inventory'), {
            'fields': ('quantity',),
        }),
        (_('Status Flags'), {
            'fields': ('is_active', 'is_featured', 'is_deleted'),
        }),
        (_('Audit Trail (System Managed)'), {
            'fields': ('created_by', 'updated_by', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    # ---------- PAGINATION & PERFORMANCE ----------
    list_per_page = 25
    ordering = ['-updated_at']
    save_on_top = True

    # ---------- CUSTOM ADMIN LOGIC ----------
    
    def has_delete_permission(self, request, obj=None):
        return True  # allow delete button to show



    def stock_status(self, obj):
        """Show intuitive color-coded stock indicators."""
        if obj.quantity == 0:
            color, label = '#dc3545', 'Out of Stock'       # Red
        elif obj.quantity <= 10:
            color, label = '#fd7e14', 'Low Stock'          # Orange
        else:
            color, label = '#198754', 'In Stock'           # Green

        return format_html('<b><span style="color:{};">{}</span></b>', color, label)

    stock_status.short_description = _('Stock Status')

    def image_preview(self, obj):
        """Display image thumbnail or placeholder."""
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height: 80px; max-width: 80px; border-radius: 6px; object-fit: cover;" />',
                obj.image.url
            )
        return format_html('<span style="color: #888;">No Image</span>')

    image_preview.short_description = _('Image')

    def save_model(self, request, obj, form, change):
        """Attach audit trail for created/updated by."""
        if not change or not obj.created_by_id:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
        self.message_user(request, _("Item record saved successfully."))

    def get_queryset(self, request):
        """Default: show only non-deleted items; superusers can view all."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(is_deleted=False)

    def delete_model(self, request, obj):
        """Superuser = hard delete, Staff = soft delete."""
        if request.user.is_superuser:
            obj.__class__.objects.filter(pk=obj.pk).delete()  # hard delete
        else:
            obj.is_deleted = True
            obj.save()

def delete_queryset(self, request, queryset):
    """Superuser = hard delete multiple, Staff = soft delete."""
    if request.user.is_superuser:
        queryset.model.objects.filter(pk__in=queryset.values('pk')).delete()
    else:
        queryset.update(is_deleted=True)


    # ---------- ADMIN ACTIONS ----------
    actions = ['restore_items']

    @admin.action(description=_("Restore selected soft-deleted items"))
    def restore_items(self, request, queryset):
        restored = queryset.update(is_deleted=False)
        self.message_user(request, _(f"{restored} item(s) restored successfully."))

