from django import forms
from django.forms import inlineformset_factory
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .models import (
    Invoice, InvoiceItem, Payment, Return,
    Challan, ChallanItem, Balance
)
from party.models import Party
from items.models import Item


# =========================================================
# INVOICE FORM
# =========================================================
class InvoiceForm(forms.ModelForm):
    new_party_name = forms.CharField(
        max_length=255, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Or enter new party name'})
    )
    new_party_phone = forms.CharField(
        max_length=20, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone number'})
    )

    # ✅ FIXED FIELD NAME (aligned with model + view)
    is_limit_enabled = forms.BooleanField(required=False, label="Enable Invoice Limit")

    limit_amount = forms.DecimalField(
        max_digits=10, decimal_places=2,
        required=False, initial=0, min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Invoice limit amount'})
    )

    class Meta:
        model = Invoice
        fields = ['invoice_number', 'party', 'date', 'is_paid', 'is_limit_enabled', 'limit_amount']
        widgets = {
            'invoice_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'INV-001'}),
            'party': forms.Select(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'is_paid': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean(self):
        cleaned_data = super().clean()

        # ✅ Handle party creation inline
        party = cleaned_data.get('party')
        new_party_name = cleaned_data.get('new_party_name')
        if new_party_name and not party:
            new_party_phone = cleaned_data.get('new_party_phone')
            party = Party.objects.create(name=new_party_name.strip(), phone=new_party_phone)
            cleaned_data['party'] = party
        elif not party and not new_party_name:
            raise ValidationError("Please select a party or enter a new party name.")

        # ✅ Validate limit logic correctly
        is_limit_enabled = cleaned_data.get('is_limit_enabled')
        limit_amount = cleaned_data.get('limit_amount') or 0
        if is_limit_enabled and limit_amount <= 0:
            raise ValidationError("Invoice limit must be greater than 0 if enabled.")

        return cleaned_data


# =========================================================
# INVOICE ITEM FORM
# =========================================================
class InvoiceItemInlineForm(forms.ModelForm):
    new_item_name = forms.CharField(
        max_length=255, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Or enter new item name'})
    )

    class Meta:
        model = InvoiceItem
        fields = ['item', 'quantity', 'rate', 'gst_amount', 'discount_amount', 'total']
        widgets = {
            'item': forms.Select(attrs={'class': 'form-control item-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control quantity-input', 'min': '1', 'value': '1'}),
            'rate': forms.NumberInput(attrs={'class': 'form-control rate-input', 'step': '0.01', 'min': '0'}),
            'gst_amount': forms.NumberInput(attrs={'class': 'form-control gst-input', 'step': '0.01', 'min': '0', 'value': '0'}),
            'discount_amount': forms.NumberInput(attrs={'class': 'form-control discount-input', 'step': '0.01', 'min': '0', 'value': '0'}),
            'total': forms.NumberInput(attrs={'class': 'form-control total-input', 'step': '0.01', 'readonly': 'readonly'}),
        }

    def clean(self):
        cleaned_data = super().clean()

        # ✅ Inline item creation (same logic retained)
        item = cleaned_data.get('item')
        new_item_name = cleaned_data.get('new_item_name')
        if new_item_name and not item:
            item = Item.objects.create(name=new_item_name.strip())
            cleaned_data['item'] = item

        # ✅ Total computation
        quantity = cleaned_data.get('quantity') or 0
        rate = cleaned_data.get('rate') or 0
        gst = cleaned_data.get('gst_amount') or 0
        discount = cleaned_data.get('discount_amount') or 0
        cleaned_data['total'] = (quantity * rate) + gst - discount

        return cleaned_data


# =========================================================
# INVOICE ITEM FORMSET
# =========================================================
class BaseInvoiceItemFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        # ✅ Removed the hard stop ValidationError (view handles this)
        valid_forms = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get('DELETE', False)]

        for form in valid_forms:
            quantity = form.cleaned_data.get('quantity')
            rate = form.cleaned_data.get('rate')
            if quantity is not None and quantity <= 0:
                form.add_error('quantity', "Quantity must be greater than zero.")
            if rate is not None and rate < 0:
                form.add_error('rate', "Rate cannot be negative.")


# ✅ Simplified: one default row to avoid validation issues
InvoiceItemFormSet = inlineformset_factory(
    Invoice, InvoiceItem,
    form=InvoiceItemInlineForm,
    formset=BaseInvoiceItemFormSet,
    extra=1,
    can_delete=True
)


# =========================================================
# PAYMENT FORM
# =========================================================

from django import forms
from django.core.exceptions import ValidationError
from decimal import Decimal
from .models import Payment, Party, Invoice

class PaymentForm(forms.ModelForm):
    send_receipt = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'id_send_receipt'
        }),
        label="Send WhatsApp receipt to party"
    )

    download_receipt = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'id_download_receipt'
        }),
        label="Download PDF Receipt"
    )

    new_party_name = forms.CharField(
        required=False,
        label="New Party Name",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter party name',
            'id': 'id_new_party_name'
        })
    )

    class Meta:
        model = Payment
        fields = ['party', 'invoice', 'date', 'amount', 'mode', 'notes']
        widgets = {
            'party': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_party'
            }),
            'invoice': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_invoice'
            }),
            'date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'id': 'id_date'
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0.01',
                'placeholder': '0.00',
                'id': 'id_amount'
            }),
            'mode': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_mode'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Add any notes or reference details...',
                'id': 'id_notes'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set empty labels for choices
        if 'party' in self.fields:
            self.fields['party'].empty_label = "-- Select Party --"
            self.fields['party'].required = False
        if 'invoice' in self.fields:
            self.fields['invoice'].empty_label = "-- No Invoice (Optional) --"
        if 'mode' in self.fields:
            self.fields['mode'].empty_label = "-- Select Payment Mode --"

    def clean(self):
        cleaned = super().clean()
        party = cleaned.get('party')
        new_party_name = cleaned.get('new_party_name', '').strip()
        invoice = cleaned.get('invoice')
        amount = cleaned.get('amount')

        # Party validation - either existing or new party name required
        if not party and not new_party_name:
            raise ValidationError("Please select an existing party or enter a new party name.")

        # Invoice-specific validation
        if invoice and amount:
            total_amount = invoice.total_amount or Decimal('0.00')
            total_paid = invoice.total_paid or Decimal('0.00')
            total_returns = sum(r.amount for r in invoice.returns.all())
            current_balance = total_amount - total_paid - total_returns
            
            # Ensure balance is not negative
            if current_balance < Decimal('0.00'):
                current_balance = Decimal('0.00')
            
            # Check if payment exceeds pending balance
            if amount > current_balance:
                raise ValidationError(
                    f"Payment amount ₹{amount} exceeds the pending balance of ₹{current_balance:.2f}. "
                    f"Please enter a valid amount."
                )

        return cleaned

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is not None and amount <= 0:
            raise ValidationError("Payment amount must be greater than zero.")
        return amount

# =========================================================
# RETURN FORM
# =========================================================
class ReturnForm(forms.ModelForm):
    class Meta:
        model = Return
        fields = ['invoice', 'party', 'return_date', 'amount', 'reason', 'image']
        widgets = {
            'invoice': forms.Select(attrs={'class': 'form-control'}),
            'party': forms.Select(attrs={'class': 'form-control'}),
            'return_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Reason for return'}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }


# =========================================================
# CHALLAN FORM + FORMSET
# =========================================================
class ChallanForm(forms.ModelForm):
    class Meta:
        model = Challan
        fields = ['party', 'invoice', 'date', 'transport_details']
        # Removed 'challan_number' since it's auto-generated
        widgets = {
            'party': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            'invoice': forms.Select(attrs={
                'class': 'form-select'
            }),
            'date': forms.DateInput(attrs={
                'type': 'date', 
                'class': 'form-control',
                'required': True
            }),
            'transport_details': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 3, 
                'placeholder': 'Enter transport details (Vehicle No, Driver Name, etc.)'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make party and date required
        self.fields['party'].required = True
        self.fields['date'].required = True
        self.fields['invoice'].required = False
        
        # Add help text
        self.fields['party'].help_text = 'Select the party to deliver goods to'
        self.fields['invoice'].help_text = 'Optionally link this challan to an invoice'
        self.fields['date'].help_text = 'Challan date'


ChallanItemFormSet = inlineformset_factory(
    Challan,
    ChallanItem,
    fields=['item', 'quantity'],
    extra=1,  # Start with 1 empty row instead of 3
    can_delete=True,
    widgets={
        'item': forms.Select(attrs={
            'class': 'form-select',
            'required': True
        }),
        'quantity': forms.NumberInput(attrs={
            'class': 'form-control', 
            'min': '1',
            'placeholder': 'Qty',
            'required': True
        }),
    },
    # Ensure at least one item is required
    validate_min=True,
    min_num=1,
)
# =========================================================
# BALANCE FORM + FORMSET
# =========================================================
class BalanceForm(forms.ModelForm):
    class Meta:
        model = Balance
        fields = ['party', 'item', 'quantity', 'price', 'discount_percent']
        widgets = {
            'party': forms.Select(attrs={'class': 'form-control'}),
            'item': forms.Select(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'discount_percent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '100'}),
        }


BalanceFormSet = forms.modelformset_factory(
    Balance,
    form=BalanceForm,
    extra=1,
    can_delete=True,
)
