# billing/forms.py
"""
Billing Forms
=============
All form definitions for Invoice, Payment, Return, Challan, and Balance management.
"""

import logging
from decimal import Decimal
from django import forms
from django.forms import inlineformset_factory, BaseInlineFormSet
from django.core.exceptions import ValidationError
from django.db.models import Sum

from .models import (
    Invoice, InvoiceItem, Payment, Return, ReturnItem,
    Challan, ChallanItem, Balance
)
from party.models import Party
from items.models import Item

logger = logging.getLogger(__name__)


# ================================================================
# INVOICE FORMS
# ================================================================

class InvoiceForm(forms.ModelForm):
    """
    Invoice creation/update form with party selection and limit options.
    """
    new_party_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter new party name (optional)'
        }),
        label="New Party Name"
    )
    
    new_party_phone = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Phone number (optional)'
        }),
        label="New Party Phone"
    )
    
    class Meta:
        model = Invoice
        fields = [
            'invoice_number', 'party', 'date',
            'is_limit_enabled', 'limit_amount'
        ]
        widgets = {
            'invoice_number': forms.TextInput(attrs={
                'class': 'form-control',
                'readonly': 'readonly'
            }),
            'party': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_party'
            }),
            'date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'is_limit_enabled': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'limit_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0'
            })
        }
    
    def clean(self):
        """Validate party selection or new party creation"""
        cleaned_data = super().clean()
        party = cleaned_data.get('party')
        new_party_name = cleaned_data.get('new_party_name', '').strip()
        
        # Must have either existing party or new party name
        if not party and not new_party_name:
            raise ValidationError("Please select an existing party or enter a new party name.")
        
        # Validate limit
        is_limit_enabled = cleaned_data.get('is_limit_enabled', False)
        limit_amount = cleaned_data.get('limit_amount')
        
        if is_limit_enabled and (not limit_amount or limit_amount <= 0):
            raise ValidationError({
                'limit_amount': "Limit amount must be greater than zero when limit is enabled."
            })
        
        return cleaned_data


class InvoiceItemForm(forms.ModelForm):
    """
    Individual invoice item form.
    """
    new_item_name = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter new item name (optional)'
        }),
        label="New Item Name"
    )
    
    class Meta:
        model = InvoiceItem
        fields = ['item', 'quantity', 'rate', 'gst_amount', 'discount_amount']
        widgets = {
            'item': forms.Select(attrs={
                'class': 'form-select item-select'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'step': '1'
            }),
            'rate': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0'
            }),
            'gst_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'readonly': 'readonly'
            }),
            'discount_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0'
            })
        }
    
    def clean(self):
        """Validate item selection or new item creation"""
        cleaned_data = super().clean()
        item = cleaned_data.get('item')
        new_item_name = cleaned_data.get('new_item_name', '').strip()
        quantity = cleaned_data.get('quantity')
        rate = cleaned_data.get('rate')
        
        # Must have either existing item or new item name
        if not item and not new_item_name:
            raise ValidationError("Please select an existing item or enter a new item name.")
        
        # Validate quantity and rate
        if quantity and quantity <= 0:
            raise ValidationError({'quantity': "Quantity must be greater than zero."})
        
        if rate and rate < 0:
            raise ValidationError({'rate': "Rate cannot be negative."})
        
        return cleaned_data


class BaseInvoiceItemFormSet(BaseInlineFormSet):
    """
    Custom formset for invoice items with validation.
    """
    def clean(self):
        """Validate that at least one item exists"""
        super().clean()
        
        if any(self.errors):
            return
        
        # Count non-deleted forms with data
        valid_forms = 0
        for form in self.forms:
            if not form.cleaned_data.get('DELETE', False):
                if form.cleaned_data.get('item') or form.cleaned_data.get('new_item_name'):
                    valid_forms += 1
        
        if valid_forms < 1:
            raise ValidationError("At least one invoice item is required.")


# Create the formset
InvoiceItemFormSet = inlineformset_factory(
    Invoice,
    InvoiceItem,
    form=InvoiceItemForm,
    formset=BaseInvoiceItemFormSet,
    extra=5,
    can_delete=True,
    min_num=1,
    validate_min=True
)


# ================================================================
# PAYMENT FORMS
# ================================================================

class PaymentForm(forms.ModelForm):
    """
    Payment creation form with party and invoice selection.
    """
    new_party_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter new party name (optional)'
        }),
        label="New Party Name"
    )
    
    send_receipt = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label="Send Receipt via WhatsApp/Email"
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
                'type': 'date'
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0.01'
            }),
            'mode': forms.Select(attrs={
                'class': 'form-select'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional notes'
            })
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make invoice optional (for general payments)
        self.fields['invoice'].required = False
        
        # Filter invoices to show only unpaid ones
        self.fields['invoice'].queryset = Invoice.objects.filter(
            is_paid=False,
            is_active=True
        ).order_by('-date')
    
    def clean(self):
        """Validate payment amount against invoice balance"""
        cleaned_data = super().clean()
        party = cleaned_data.get('party')
        new_party_name = cleaned_data.get('new_party_name', '').strip()
        invoice = cleaned_data.get('invoice')
        amount = cleaned_data.get('amount')
        
        # Must have either existing party or new party name
        if not party and not new_party_name:
            raise ValidationError("Please select an existing party or enter a new party name.")
        
        # Validate amount is positive
        if amount and amount <= Decimal('0.00'):
            raise ValidationError({'amount': "Payment amount must be greater than zero."})
        
        # Validate against invoice balance if linked
        if invoice and amount:
            balance = invoice.balance_due or Decimal('0.00')
            
            if amount > balance:
                raise ValidationError({
                    'amount': f"Payment amount ₹{amount} exceeds balance due ₹{balance:.2f}"
                })
        
        return cleaned_data


# ================================================================
# RETURN FORMS
# ================================================================

# billing/forms.py
# REPLACE RETURN FORMS SECTION WITH THIS:

# ================================================================
# RETURN FORMS (FIXED - NON-INLINE)
# ================================================================

class ReturnForm(forms.ModelForm):
    """Return creation form."""
    class Meta:
        model = Return
        fields = ['invoice', 'return_date', 'reason', 'image']
        widgets = {
            'invoice': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_invoice',
                'required': True
            }),
            'return_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Reason for return (optional)'
            }),
            'image': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            })
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # ✅ FIXED: More permissive queryset - include ALL active invoices
        self.fields['invoice'].queryset = Invoice.objects.filter(
            is_active=True
        ).select_related('party').order_by('-date')
        
        # ✅ Make invoice required
        self.fields['invoice'].required = True
        
        # ✅ Optional: Make reason not required
        self.fields['reason'].required = False
        self.fields['image'].required = False

class ReturnItemForm(forms.Form):  # ✅ Changed to regular Form (not ModelForm)
    """
    Individual return item form.
    NOT a ModelForm - we'll create ReturnItem objects manually in the view.
    """
    invoice_item = forms.ModelChoiceField(
        queryset=InvoiceItem.objects.none(),
        widget=forms.Select(attrs={
            'class': 'form-select return-invoice-item',
            'required': 'required'
        }),
        label="Item"
    )
    
    quantity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control return-quantity',
            'min': '1',
            'step': '1',
            'required': 'required'
        }),
        label="Quantity"
    )
    
    amount = forms.DecimalField(
        min_value=Decimal('0.01'),
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control return-amount',
            'step': '0.01',
            'min': '0.01',
            'readonly': 'readonly',
            'required': 'required'
        }),
        label="Amount"
    )
    
    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        if invoice:
            self.fields['invoice_item'].queryset = InvoiceItem.objects.filter(
                invoice=invoice,
                is_active=True,
                item__isnull=False
            ).select_related('item').order_by('item__name')
    
    def clean(self):
        cleaned_data = super().clean()
        invoice_item = cleaned_data.get('invoice_item')
        quantity = cleaned_data.get('quantity')
        
        if not invoice_item or not quantity:
            return cleaned_data
        
        # Calculate already returned
        already_returned = ReturnItem.objects.filter(
            invoice_item=invoice_item,
            return_instance__is_active=True
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        max_returnable = invoice_item.quantity - already_returned
        
        if quantity > max_returnable:
            raise ValidationError({
                'quantity': f"Cannot return {quantity} units. Maximum: {max_returnable}"
            })
        
        return cleaned_data


class BaseReturnItemFormSet(forms.BaseFormSet):  # ✅ Changed from BaseInlineFormSet
    """Custom formset for return items."""
    
    def __init__(self, *args, invoice=None, **kwargs):
        self.invoice = invoice
        super().__init__(*args, **kwargs)
    
    def _construct_form(self, i, **kwargs):
        """Pass invoice to each form"""
        kwargs['invoice'] = self.invoice
        return super()._construct_form(i, **kwargs)
    
    def clean(self):
        """Validate at least one item"""
        if any(self.errors):
            return
        
        valid_items = 0
        for form in self.forms:
            if form.cleaned_data:
                if form.cleaned_data.get('invoice_item') and form.cleaned_data.get('quantity'):
                    valid_items += 1
        
        if valid_items < 1:
            raise ValidationError("At least one item must be returned.")


# ✅ FIXED: Use regular formset_factory (not inline)
from django.forms import formset_factory

ReturnItemFormSet = formset_factory(
    ReturnItemForm,
    formset=BaseReturnItemFormSet,
    extra=1,
    can_delete=False,  # No delete for creation
    min_num=1,
    validate_min=True,
    max_num=50  # Reasonable limit
)

# ================================================================
# CHALLAN FORMS
# ================================================================

class ChallanForm(forms.ModelForm):
    """
    Challan (Delivery Note) creation form.
    """
    class Meta:
        model = Challan
        fields = ['party', 'invoice', 'date', 'transport_details']
        widgets = {
            'party': forms.Select(attrs={
                'class': 'form-select',
                'required': 'required'
            }),
            'invoice': forms.Select(attrs={
                'class': 'form-select'
            }),
            'date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'transport_details': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Vehicle number, driver name, etc.'
            })
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make invoice optional
        self.fields['invoice'].required = False
        
        # Filter to active invoices only
        self.fields['invoice'].queryset = Invoice.objects.filter(
            is_active=True
        ).order_by('-date')


class ChallanItemForm(forms.ModelForm):
    """
    Individual challan item form.
    """
    class Meta:
        model = ChallanItem
        fields = ['item', 'quantity']
        widgets = {
            'item': forms.Select(attrs={
                'class': 'form-select'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'step': '1'
            })
        }


class BaseChallanItemFormSet(BaseInlineFormSet):
    """Custom formset for challan items"""
    def clean(self):
        """Validate at least one item exists"""
        super().clean()
        
        if any(self.errors):
            return
        
        valid_items = 0
        for form in self.forms:
            if not form.cleaned_data.get('DELETE', False):
                if form.cleaned_data.get('item'):
                    valid_items += 1
        
        if valid_items < 1:
            raise ValidationError("At least one item is required.")


# Create the formset
ChallanItemFormSet = inlineformset_factory(
    Challan,
    ChallanItem,
    form=ChallanItemForm,
    formset=BaseChallanItemFormSet,
    extra=3,
    can_delete=True,
    min_num=1,
    validate_min=True
)


# ================================================================
# BALANCE FORMS
# ================================================================

class BalanceForm(forms.ModelForm):
    """
    Balance management form for old outstanding balances.
    """
    class Meta:
        model = Balance
        fields = ['party', 'item', 'quantity', 'price', 'discount_percent']
        widgets = {
            'party': forms.Select(attrs={
                'class': 'form-select'
            }),
            'item': forms.Select(attrs={
                'class': 'form-select'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0'
            }),
            'discount_percent': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'max': '100'
            })
        }


class BaseBalanceFormSet(BaseInlineFormSet):
    """Custom formset for balance management"""
    pass


# Create the formset (not inline, but standalone)
from django.forms import modelformset_factory

BalanceFormSet = modelformset_factory(
    Balance,
    form=BalanceForm,
    formset=BaseBalanceFormSet,
    extra=3,
    can_delete=True
)
