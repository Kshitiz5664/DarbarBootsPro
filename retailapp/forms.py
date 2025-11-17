# retail/forms.py
from django import forms
from django.core.exceptions import ValidationError
from .models import RetailInvoice, RetailInvoiceItem, RetailReturn
from items.models import Item
from decimal import Decimal

class RetailInvoiceForm(forms.ModelForm):
    class Meta:
        model = RetailInvoice
        fields = ["customer_name", "customer_mobile", "date", "notes"]
        widgets = {
            "customer_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Customer name"}),
            "customer_mobile": forms.TextInput(attrs={"class": "form-control", "placeholder": "Mobile number"}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Notes (optional)"}),
        }

class RetailInvoiceItemForm(forms.ModelForm):
    # Allows selecting an existing item OR free-text manual name
    item = forms.ModelChoiceField(
        queryset=Item.objects.filter(is_deleted=False, is_active=True),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Select from existing items (or leave blank and enter manual name)."
    )

    manual_item_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Manual item name"})
    )

    class Meta:
        model = RetailInvoiceItem
        fields = ["item", "manual_item_name", "quantity", "rate", "gst_percent", "discount_percent"]
        widgets = {
            "quantity": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "rate": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "gst_percent": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "discount_percent": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }

    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        # if item prefilled, auto-fill rate/gst
        if self.instance and self.instance.item:
            item = self.instance.item
            self.fields["rate"].initial = getattr(item, "price_retail", None) or getattr(item, "price_wholesale", None)
            self.fields["gst_percent"].initial = getattr(item, "gst_percent", Decimal("0.00"))

    def clean(self):
        cleaned = super().clean()
        item = cleaned.get("item")
        manual_name = cleaned.get("manual_item_name")
        rate = cleaned.get("rate")
        qty = cleaned.get("quantity")

        if not item and not manual_name:
            raise ValidationError("Provide either an existing item or a manual item name.")
        if rate is None or Decimal(rate) < 0:
            raise ValidationError("Rate must be non-negative.")
        if qty is None or qty <= 0:
            raise ValidationError("Quantity must be at least 1.")
        return cleaned

class RetailReturnForm(forms.ModelForm):
    item = forms.ModelChoiceField(
        queryset=RetailInvoiceItem.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Select an invoice item to auto-calc amount (optional)."
    )

    class Meta:
        model = RetailReturn
        fields = ["item", "return_date", "quantity", "amount", "reason", "image"]
        widgets = {
            "return_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": '0.01'}),
            "reason": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "image": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        if invoice:
            self.fields["item"].queryset = invoice.retail_items.filter(is_active=True)
