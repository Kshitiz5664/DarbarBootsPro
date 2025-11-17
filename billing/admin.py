# billing/admin.py
from django.contrib import admin
from . import models


class SoftDeleteAdminMixin:
    """
    Admin mixin to:
    - Provide 'restore' admin action
    - Add 'is_active' filter/column
    """
    actions = ['restore_selected']

    def restore_selected(self, request, queryset):
        # Use .all() to include soft-deleted when admin chooses "All"
        for obj in queryset:
            obj.restore()
    restore_selected.short_description = "Restore selected records"

    def get_list_display(self, request):
        base = getattr(super(), 'list_display', ())
        return tuple(base) + ('is_active',)


@admin.register(models.Invoice)
class InvoiceAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ('invoice_number', 'party', 'date', 'base_amount', 'is_paid', 'is_active')
    search_fields = ('invoice_number', 'party__name')
    list_filter = ('is_active', 'is_paid', 'date')


@admin.register(models.InvoiceItem)
class InvoiceItemAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ('invoice', 'item', 'quantity', 'total', 'is_active')
    search_fields = ('invoice__invoice_number', 'item__name')
    list_filter = ('is_active',)


@admin.register(models.Payment)
class PaymentAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ('party', 'invoice', 'date', 'amount', 'mode', 'is_active')
    search_fields = ('party__name',)
    list_filter = ('mode', 'is_active')


@admin.register(models.Return)
class ReturnAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'invoice', 'party', 'return_date', 'amount', 'is_active')
    search_fields = ('invoice__invoice_number', 'party__name')
    list_filter = ('is_active',)


@admin.register(models.Challan)
class ChallanAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ('challan_number', 'party', 'date', 'is_active')
    search_fields = ('challan_number', 'party__name')
    list_filter = ('is_active',)


@admin.register(models.Balance)
class BalanceAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ('party', 'item', 'quantity', 'is_active')
    search_fields = ('party__name', 'item__name')
    list_filter = ('is_active',)
