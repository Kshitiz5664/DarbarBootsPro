from django.contrib import admin

# Register your models here.
# retail/admin.py
from django.contrib import admin
from .models import RetailInvoice, RetailInvoiceItem, RetailReturn

@admin.register(RetailInvoice)
class RetailInvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "customer_name", "date", "final_amount", "is_paid", "is_active")
    search_fields = ("invoice_number", "customer_name")
    list_filter = ("is_paid", "is_active", "date")
    readonly_fields = ("invoice_number", "base_amount", "total_gst", "total_discount", "final_amount", "created_at", "updated_at")
    ordering = ("-date",)

@admin.register(RetailInvoiceItem)
class RetailInvoiceItemAdmin(admin.ModelAdmin):
    list_display = ("display_name", "invoice", "quantity", "rate", "gst_amount", "discount_amount", "total", "is_active")
    search_fields = ("manual_item_name", "item__name", "invoice__invoice_number")

@admin.register(RetailReturn)
class RetailReturnAdmin(admin.ModelAdmin):
    list_display = ("invoice", "item", "quantity", "amount", "return_date", "is_active")
    search_fields = ("invoice__invoice_number", "item__manual_item_name")
