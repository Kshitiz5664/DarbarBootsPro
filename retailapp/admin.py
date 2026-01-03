# retailapp/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Sum
from .models import RetailInvoice, RetailInvoiceItem, RetailReturn


@admin.register(RetailInvoice)
class RetailInvoiceAdmin(admin.ModelAdmin):
    """Enhanced admin interface for Retail Invoices with payment mode support"""
    
    list_display = (
        "invoice_number", 
        "customer_name", 
        "date", 
        "final_amount_display",
        "payment_status_badge",
        "transaction_ref_display",
        "is_active"
    )
    
    list_filter = (
        "payment_mode",
        "is_active", 
        "date",
        "created_at",
    )
    
    search_fields = (
        "invoice_number", 
        "customer_name",
        "customer_mobile",
        "transaction_reference",
    )
    
    readonly_fields = (
        "invoice_number",
        "base_amount", 
        "total_gst", 
        "total_discount", 
        "final_amount",
        "payment_date",
        "is_paid_display",
        "created_at", 
        "updated_at",
        "created_by",
        "updated_by",
    )
    
    fieldsets = (
        ('Invoice Information', {
            'fields': (
                'invoice_number',
                'date',
                'is_active',
            )
        }),
        ('Customer Details', {
            'fields': (
                'customer_name',
                'customer_mobile',
            )
        }),
        ('Payment Information', {
            'fields': (
                'payment_mode',
                'transaction_reference',
                'payment_date',
                'is_paid_display',
            ),
            'description': 'Select payment method. Choose "Unpaid" if payment not received.'
        }),
        ('Invoice Totals', {
            'fields': (
                'base_amount',
                'total_gst',
                'total_discount',
                'final_amount',
            ),
            'classes': ('collapse',),
            'description': 'These amounts are automatically calculated from invoice items.'
        }),
        ('Additional Information', {
            'fields': (
                'notes',
            ),
            'classes': ('collapse',),
        }),
        ('Audit Information', {
            'fields': (
                'created_by',
                'created_at',
                'updated_by',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )
    
    ordering = ("-date", "-created_at")
    
    date_hierarchy = 'date'
    
    list_per_page = 25
    
    actions = ['mark_as_paid_cash', 'mark_as_paid_upi', 'mark_as_unpaid', 'activate_invoices', 'deactivate_invoices']
    
    def final_amount_display(self, obj):
        """Display final amount with currency symbol"""
        return f"₹{obj.final_amount:,.2f}"
    final_amount_display.short_description = "Final Amount"
    final_amount_display.admin_order_field = "final_amount"
    
    def payment_status_badge(self, obj):
        """Display payment status with colored badge"""
        if obj.payment_mode == 'UNPAID':
            color = '#dc3545'  # Red
            icon = '⏳'
            text = 'Unpaid'
        elif obj.payment_mode == 'CASH':
            color = '#28a745'  # Green
            icon = '💵'
            text = 'Cash'
        elif obj.payment_mode == 'UPI':
            color = '#17a2b8'  # Cyan
            icon = '📱'
            text = 'UPI'
        elif obj.payment_mode == 'CARD':
            color = '#007bff'  # Blue
            icon = '💳'
            text = 'Card'
        elif obj.payment_mode == 'ONLINE':
            color = '#6610f2'  # Indigo
            icon = '🌐'
            text = 'Online'
        elif obj.payment_mode == 'CHEQUE':
            color = '#fd7e14'  # Orange
            icon = '📝'
            text = 'Cheque'
        else:
            color = '#6c757d'  # Gray
            icon = '💰'
            text = 'Other'
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-weight: bold; font-size: 11px;">{} {}</span>',
            color, icon, text
        )
    payment_status_badge.short_description = "Payment Status"
    payment_status_badge.admin_order_field = "payment_mode"
    
    def transaction_ref_display(self, obj):
        """Display transaction reference if available"""
        if obj.transaction_reference:
            return format_html(
                '<span style="font-family: monospace; background-color: #f8f9fa; '
                'padding: 2px 6px; border-radius: 3px;">{}</span>',
                obj.transaction_reference
            )
        return format_html('<span style="color: #999;">—</span>')
    transaction_ref_display.short_description = "Transaction Ref"
    
    def is_paid_display(self, obj):
        """Display computed is_paid property for readonly field"""
        if obj.is_paid:
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ Yes</span>'
            )
        return format_html(
            '<span style="color: red; font-weight: bold;">✗ No</span>'
        )
    is_paid_display.short_description = "Is Paid?"
    
    # Admin Actions
    def mark_as_paid_cash(self, request, queryset):
        """Mark selected invoices as paid with Cash"""
        updated = queryset.filter(is_active=True).update(
            payment_mode='CASH',
            updated_by=request.user
        )
        self.message_user(request, f'{updated} invoice(s) marked as paid (Cash).')
    mark_as_paid_cash.short_description = "Mark as Paid (Cash)"
    
    def mark_as_paid_upi(self, request, queryset):
        """Mark selected invoices as paid with UPI"""
        updated = queryset.filter(is_active=True).update(
            payment_mode='UPI',
            updated_by=request.user
        )
        self.message_user(request, f'{updated} invoice(s) marked as paid (UPI).')
    mark_as_paid_upi.short_description = "Mark as Paid (UPI)"
    
    def mark_as_unpaid(self, request, queryset):
        """Mark selected invoices as unpaid"""
        updated = queryset.filter(is_active=True).update(
            payment_mode='UNPAID',
            payment_date=None,
            transaction_reference='',
            updated_by=request.user
        )
        self.message_user(request, f'{updated} invoice(s) marked as unpaid.')
    mark_as_unpaid.short_description = "Mark as Unpaid"
    
    def activate_invoices(self, request, queryset):
        """Activate selected invoices"""
        updated = queryset.update(is_active=True, updated_by=request.user)
        self.message_user(request, f'{updated} invoice(s) activated.')
    activate_invoices.short_description = "Activate selected invoices"
    
    def deactivate_invoices(self, request, queryset):
        """Deactivate selected invoices (soft delete)"""
        updated = queryset.update(is_active=False, updated_by=request.user)
        self.message_user(request, f'{updated} invoice(s) deactivated.')
    deactivate_invoices.short_description = "Deactivate selected invoices"
    
    def save_model(self, request, obj, form, change):
        """Auto-set created_by and updated_by"""
        if not change:  # Creating new
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(RetailInvoiceItem)
class RetailInvoiceItemAdmin(admin.ModelAdmin):
    """Enhanced admin interface for Retail Invoice Items"""
    
    list_display = (
        "display_name", 
        "invoice_link",
        "quantity", 
        "rate_display",
        "gst_amount_display",
        "discount_amount_display",
        "total_display",
        "is_active"
    )
    
    list_filter = (
        "is_active",
        "created_at",
    )
    
    search_fields = (
        "manual_item_name", 
        "item__name", 
        "invoice__invoice_number",
        "invoice__customer_name",
    )
    
    readonly_fields = (
        "base_amount",
        "gst_amount",
        "discount_amount",
        "total",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
    )
    
    fieldsets = (
        ('Item Information', {
            'fields': (
                'invoice',
                'item',
                'manual_item_name',
            ),
            'description': 'Select an item from the list OR enter a manual item name.'
        }),
        ('Pricing Details', {
            'fields': (
                'quantity',
                'rate',
                'gst_percent',
                'discount_percent',
            )
        }),
        ('Calculated Amounts', {
            'fields': (
                'base_amount',
                'gst_amount',
                'discount_amount',
                'total',
            ),
            'classes': ('collapse',),
            'description': 'These amounts are automatically calculated.'
        }),
        ('Status', {
            'fields': (
                'is_active',
            )
        }),
        ('Audit Information', {
            'fields': (
                'created_by',
                'created_at',
                'updated_by',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )
    
    ordering = ("-created_at",)
    
    list_per_page = 50
    
    def invoice_link(self, obj):
        """Display clickable link to invoice"""
        if obj.invoice:
            url = reverse('admin:retailapp_retailinvoice_change', args=[obj.invoice.id])
            return format_html(
                '<a href="{}" style="font-weight: bold;">{}</a>',
                url, obj.invoice.invoice_number
            )
        return "—"
    invoice_link.short_description = "Invoice"
    
    def rate_display(self, obj):
        return f"₹{obj.rate:,.2f}"
    rate_display.short_description = "Rate"
    rate_display.admin_order_field = "rate"
    
    def gst_amount_display(self, obj):
        return f"₹{obj.gst_amount:,.2f}"
    gst_amount_display.short_description = "GST"
    gst_amount_display.admin_order_field = "gst_amount"
    
    def discount_amount_display(self, obj):
        return f"₹{obj.discount_amount:,.2f}"
    discount_amount_display.short_description = "Discount"
    discount_amount_display.admin_order_field = "discount_amount"
    
    def total_display(self, obj):
        return format_html(
            '<strong style="color: #28a745;">₹{:,.2f}</strong>',
            obj.total
        )
    total_display.short_description = "Total"
    total_display.admin_order_field = "total"
    
    def save_model(self, request, obj, form, change):
        """Auto-set created_by and updated_by"""
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(RetailReturn)
class RetailReturnAdmin(admin.ModelAdmin):
    """Enhanced admin interface for Retail Returns"""
    
    list_display = (
        "invoice_link",
        "item_display",
        "quantity",
        "amount_display",
        "return_date",
        "has_image",
        "is_active"
    )
    
    list_filter = (
        "is_active",
        "return_date",
        "created_at",
    )
    
    search_fields = (
        "invoice__invoice_number",
        "invoice__customer_name",
        "item__manual_item_name",
        "item__item__name",
        "reason",
    )
    
    readonly_fields = (
        "amount",
        "image_preview",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
    )
    
    fieldsets = (
        ('Return Information', {
            'fields': (
                'invoice',
                'item',
                'return_date',
                'quantity',
                'amount',
            )
        }),
        ('Additional Details', {
            'fields': (
                'reason',
                'image',
                'image_preview',
            )
        }),
        ('Status', {
            'fields': (
                'is_active',
            )
        }),
        ('Audit Information', {
            'fields': (
                'created_by',
                'created_at',
                'updated_by',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )
    
    ordering = ("-return_date", "-created_at")
    
    date_hierarchy = 'return_date'
    
    list_per_page = 30
    
    def invoice_link(self, obj):
        """Display clickable link to invoice"""
        if obj.invoice:
            url = reverse('admin:retailapp_retailinvoice_change', args=[obj.invoice.id])
            return format_html(
                '<a href="{}" style="font-weight: bold;">{}</a><br>'
                '<small style="color: #666;">{}</small>',
                url, 
                obj.invoice.invoice_number,
                obj.invoice.customer_name
            )
        return "—"
    invoice_link.short_description = "Invoice"
    
    def item_display(self, obj):
        """Display item name"""
        if obj.item:
            return obj.item.display_name
        return format_html('<em style="color: #999;">Manual Return</em>')
    item_display.short_description = "Item"
    
    def amount_display(self, obj):
        """Display amount with currency"""
        return format_html(
            '<strong style="color: #dc3545;">₹{:,.2f}</strong>',
            obj.amount
        )
    amount_display.short_description = "Amount"
    amount_display.admin_order_field = "amount"
    
    def has_image(self, obj):
        """Display if return has image"""
        if obj.image:
            return format_html(
                '<span style="color: green; font-size: 18px;">📷</span>'
            )
        return format_html(
            '<span style="color: #ccc;">—</span>'
        )
    has_image.short_description = "Image"
    has_image.boolean = True
    
    def image_preview(self, obj):
        """Display image preview if available"""
        if obj.image:
            return format_html(
                '<img src="{}" style="max-width: 300px; max-height: 300px; '
                'border: 1px solid #ddd; border-radius: 4px; padding: 5px;" />',
                obj.image.url
            )
        return format_html('<em style="color: #999;">No image uploaded</em>')
    image_preview.short_description = "Image Preview"
    
    def save_model(self, request, obj, form, change):
        """Auto-set created_by and updated_by"""
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


# Optional: Inline admin for better management
class RetailInvoiceItemInline(admin.TabularInline):
    """Inline for managing invoice items directly from invoice admin"""
    model = RetailInvoiceItem
    extra = 0
    readonly_fields = ('base_amount', 'gst_amount', 'discount_amount', 'total')
    fields = (
        'item', 
        'manual_item_name', 
        'quantity', 
        'rate', 
        'gst_percent', 
        'discount_percent',
        'total',
        'is_active'
    )
    
    def get_queryset(self, request):
        """Only show active items by default"""
        qs = super().get_queryset(request)
        return qs.filter(is_active=True)


class RetailReturnInline(admin.TabularInline):
    """Inline for managing returns directly from invoice admin"""
    model = RetailReturn
    extra = 0
    readonly_fields = ('amount', 'return_date')
    fields = ('item', 'quantity', 'amount', 'return_date', 'reason', 'is_active')
    
    def get_queryset(self, request):
        """Only show active returns by default"""
        qs = super().get_queryset(request)
        return qs.filter(is_active=True)


# You can uncomment these lines to add inlines to RetailInvoiceAdmin
# Simply add this to the RetailInvoiceAdmin class:
# inlines = [RetailInvoiceItemInline, RetailReturnInline]