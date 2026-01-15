# billing/forms.py
from django import forms
from django.forms import inlineformset_factory
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.db import models  # ✅ ADDED: Required for aggregate operations
from decimal import Decimal

from .models import (
    Invoice, InvoiceItem, Payment, Return, ReturnItem,
    Challan, ChallanItem, Balance
)
from party.models import Party
from items.models import Item


# =========================================================
# INVOICE FORM
# =========================================================
class InvoiceForm(forms.ModelForm):
    new_party_name = forms.CharField(
        max_length=255, 
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Or enter new party name'
        })
    )
    new_party_phone = forms.CharField(
        max_length=20, 
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Phone number'
        })
    )

    is_limit_enabled = forms.BooleanField(
        required=False, 
        label="Enable Invoice Limit",
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'id_is_limit_enabled'
        })
    )

    limit_amount = forms.DecimalField(
        max_digits=10, 
        decimal_places=2,
        required=False, 
        initial=0, 
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Invoice limit amount',
            'step': '0.01'
        })
    )

    class Meta:
        model = Invoice
        fields = ['invoice_number', 'party', 'date', 'is_paid', 'is_limit_enabled', 'limit_amount']
        widgets = {
            'invoice_number': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Auto-generated if left empty'
            }),
            'party': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_party'
            }),
            'date': forms.DateInput(attrs={
                'type': 'date', 
                'class': 'form-control',
                'required': True
            }),
            'is_paid': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set empty label for party dropdown
        if 'party' in self.fields:
            self.fields['party'].empty_label = "-- Select Party --"
            self.fields['party'].required = False
        
        # Make date required
        self.fields['date'].required = True

    def clean(self):
        cleaned_data = super().clean()

        # Handle party creation inline
        party = cleaned_data.get('party')
        new_party_name = cleaned_data.get('new_party_name', '').strip()
        
        if new_party_name and not party:
            new_party_phone = cleaned_data.get('new_party_phone', '').strip()
            party, created = Party.objects.get_or_create(
                name__iexact=new_party_name,
                defaults={
                    'name': new_party_name,
                    'phone': new_party_phone
                }
            )
            cleaned_data['party'] = party
        elif not party and not new_party_name:
            raise ValidationError("Please select a party or enter a new party name.")

        # Validate limit logic
        is_limit_enabled = cleaned_data.get('is_limit_enabled')
        limit_amount = cleaned_data.get('limit_amount') or Decimal('0.00')
        
        if is_limit_enabled and limit_amount <= 0:
            raise ValidationError({
                'limit_amount': "Invoice limit must be greater than 0 if enabled."
            })

        return cleaned_data


# =========================================================
# INVOICE ITEM FORM
# =========================================================
class InvoiceItemInlineForm(forms.ModelForm):
    new_item_name = forms.CharField(
        max_length=255, 
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Or enter new item name'
        })
    )

    class Meta:
        model = InvoiceItem
        fields = ['item', 'quantity', 'rate', 'gst_amount', 'discount_amount', 'total']
        widgets = {
            'item': forms.Select(attrs={
                'class': 'form-select item-select'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control quantity-input', 
                'min': '1', 
                'value': '1'
            }),
            'rate': forms.NumberInput(attrs={
                'class': 'form-control rate-input', 
                'step': '0.01', 
                'min': '0'
            }),
            'gst_amount': forms.NumberInput(attrs={
                'class': 'form-control gst-input', 
                'step': '0.01', 
                'min': '0', 
                'value': '0'
            }),
            'discount_amount': forms.NumberInput(attrs={
                'class': 'form-control discount-input', 
                'step': '0.01', 
                'min': '0', 
                'value': '0'
            }),
            'total': forms.NumberInput(attrs={
                'class': 'form-control total-input', 
                'step': '0.01', 
                'readonly': 'readonly'
            }),
        }

    def clean(self):
        cleaned_data = super().clean()

        # Handle inline item creation
        item = cleaned_data.get('item')
        new_item_name = cleaned_data.get('new_item_name', '').strip()
        
        if new_item_name and not item:
            item, created = Item.objects.get_or_create(
                name__iexact=new_item_name,
                defaults={
                    'name': new_item_name,
                    'price_retail': cleaned_data.get('rate', Decimal('0.00')),
                    'price_wholesale': cleaned_data.get('rate', Decimal('0.00'))
                }
            )
            cleaned_data['item'] = item

        # Validate quantities
        quantity = cleaned_data.get('quantity')
        rate = cleaned_data.get('rate')
        
        if quantity is not None and quantity <= 0:
            raise ValidationError({'quantity': "Quantity must be greater than zero."})
        
        if rate is not None and rate < 0:
            raise ValidationError({'rate': "Rate cannot be negative."})

        # Total computation (optional - model handles this)
        if quantity and rate:
            gst = cleaned_data.get('gst_amount') or Decimal('0.00')
            discount = cleaned_data.get('discount_amount') or Decimal('0.00')
            cleaned_data['total'] = (quantity * rate) + gst - discount

        return cleaned_data


# =========================================================
# INVOICE ITEM FORMSET
# =========================================================
class BaseInvoiceItemFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        
        # Count valid forms (not deleted, has data)
        valid_forms = [
            f for f in self.forms 
            if f.cleaned_data and not f.cleaned_data.get('DELETE', False)
        ]

        # Additional form-level validation
        for form in valid_forms:
            quantity = form.cleaned_data.get('quantity')
            rate = form.cleaned_data.get('rate')
            
            if quantity is not None and quantity <= 0:
                form.add_error('quantity', "Quantity must be greater than zero.")
            
            if rate is not None and rate < 0:
                form.add_error('rate', "Rate cannot be negative.")


InvoiceItemFormSet = inlineformset_factory(
    Invoice, 
    InvoiceItem,
    form=InvoiceItemInlineForm,
    formset=BaseInvoiceItemFormSet,
    extra=1,
    can_delete=True,
)


# =========================================================
# PAYMENT FORM
# =========================================================
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
            self.fields['invoice'].required = False
        
        if 'mode' in self.fields:
            self.fields['mode'].empty_label = "-- Select Payment Mode --"

    def clean(self):
        cleaned = super().clean()
        party = cleaned.get('party')
        new_party_name = cleaned.get('new_party_name', '').strip()
        invoice = cleaned.get('invoice')
        amount = cleaned.get('amount')

        # Party validation
        if not party and not new_party_name:
            raise ValidationError("Please select an existing party or enter a new party name.")

        # Handle party creation
        if new_party_name and not party:
            party, created = Party.objects.get_or_create(
                name__iexact=new_party_name,
                defaults={'name': new_party_name}
            )
            cleaned['party'] = party

        # Invoice-specific validation
        if invoice and amount:
            total_amount = invoice.total_amount or Decimal('0.00')
            total_paid = invoice.total_paid or Decimal('0.00')
            
            current_balance = total_amount - total_paid
            
            if current_balance < Decimal('0.00'):
                current_balance = Decimal('0.00')
            
            if amount > current_balance:
                raise ValidationError({
                    'amount': f"Payment amount ₹{amount} exceeds the pending balance of ₹{current_balance:.2f}."
                })

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
            'invoice': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_invoice',
                'required': True
            }),
            'party': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_party',
                'readonly': True
            }),
            'return_date': forms.DateInput(attrs={
                'type': 'date', 
                'class': 'form-control',
                'required': True
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control', 
                'step': '0.01', 
                'min': '0.01',
                'placeholder': 'Return amount'
            }),
            'reason': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 3, 
                'placeholder': 'Reason for return (optional)'
            }),
            'image': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Make required fields explicit
        self.fields['invoice'].required = True
        self.fields['return_date'].required = True
        self.fields['amount'].required = True
        
        # Party is auto-filled from invoice
        if 'instance' in kwargs and kwargs['instance'].invoice:
            self.fields['party'].initial = kwargs['instance'].invoice.party
            self.fields['party'].widget.attrs['readonly'] = True

    def clean(self):
        cleaned_data = super().clean()
        invoice = cleaned_data.get('invoice')
        amount = cleaned_data.get('amount')
        
        if not invoice:
            raise ValidationError({'invoice': "Please select an invoice."})
        
        if not amount or amount <= 0:
            raise ValidationError({'amount': "Return amount must be greater than zero."})
        
        # Auto-set party from invoice
        if invoice:
            cleaned_data['party'] = invoice.party
        
        # ✅ FIXED: Validate return amount doesn't exceed invoice total
        if invoice and amount:
            existing_returns = Return.objects.filter(
                invoice=invoice,
                is_active=True
            ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
            
            max_returnable = invoice.base_amount - existing_returns
            
            if amount > max_returnable:
                raise ValidationError({
                    'amount': f"Return amount ₹{amount} exceeds maximum returnable amount ₹{max_returnable:.2f}. "
                              f"(Invoice Total: ₹{invoice.base_amount}, Already Returned: ₹{existing_returns})"
                })
        
        return cleaned_data


# =========================================================
# RETURN ITEM FORM (Future Enhancement - Optional)
# =========================================================
class ReturnItemForm(forms.ModelForm):
    """Form for tracking specific items in a return"""
    
    class Meta:
        model = ReturnItem
        fields = ['invoice_item', 'quantity', 'amount']
        widgets = {
            'invoice_item': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'placeholder': 'Quantity to return'
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'readonly': 'readonly'
            }),
        }

    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Filter invoice items to only show items from selected invoice
        if invoice:
            self.fields['invoice_item'].queryset = InvoiceItem.objects.filter(
                invoice=invoice,
                is_active=True
            )
            self.fields['invoice_item'].label_from_instance = lambda obj: (
                f"{obj.item.name if obj.item else 'Unknown'} "
                f"(Qty: {obj.quantity}, Rate: ₹{obj.rate})"
            )

    def clean(self):
        cleaned_data = super().clean()
        invoice_item = cleaned_data.get('invoice_item')
        quantity = cleaned_data.get('quantity')
        
        if invoice_item and quantity:
            # Check if quantity doesn't exceed invoice quantity
            if quantity > invoice_item.quantity:
                raise ValidationError({
                    'quantity': f"Cannot return {quantity} units. "
                               f"Invoice only has {invoice_item.quantity} units."
                })
            
            # Check against already returned quantities
            existing_returns = ReturnItem.objects.filter(
                invoice_item=invoice_item,
                is_active=True
            ).aggregate(total=models.Sum('quantity'))['total'] or 0
            
            remaining = invoice_item.quantity - existing_returns
            
            if quantity > remaining:
                raise ValidationError({
                    'quantity': f"Cannot return {quantity} units. "
                               f"Only {remaining} units remaining (already returned {existing_returns})."
                })
            
            # Auto-calculate amount based on invoice item rate
            if invoice_item.total and invoice_item.quantity:
                per_unit_price = invoice_item.total / invoice_item.quantity
                from decimal import ROUND_HALF_UP
                cleaned_data['amount'] = (per_unit_price * quantity).quantize(
                    Decimal('0.01'), 
                    rounding=ROUND_HALF_UP
                )
        
        return cleaned_data


# ReturnItem Formset (Future Enhancement)
ReturnItemFormSet = inlineformset_factory(
    Return,
    ReturnItem,
    form=ReturnItemForm,
    extra=1,
    can_delete=True,
    min_num=0,
    validate_min=False,
)


# =========================================================
# CHALLAN FORM + FORMSET
# =========================================================
class ChallanForm(forms.ModelForm):
    class Meta:
        model = Challan
        fields = ['party', 'invoice', 'date', 'transport_details']
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
        
        # Make required fields explicit
        self.fields['party'].required = True
        self.fields['date'].required = True
        self.fields['invoice'].required = False
        
        # Set empty labels
        self.fields['party'].empty_label = "-- Select Party --"
        self.fields['invoice'].empty_label = "-- Link to Invoice (Optional) --"
        
        # Add help text
        self.fields['party'].help_text = 'Select the party to deliver goods to'
        self.fields['invoice'].help_text = 'Optionally link this challan to an invoice'
        self.fields['date'].help_text = 'Challan date'


class ChallanItemForm(forms.ModelForm):
    """Individual challan item form"""
    
    class Meta:
        model = ChallanItem
        fields = ['item', 'quantity']
        widgets = {
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
        }

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if quantity is not None and quantity <= 0:
            raise ValidationError("Quantity must be greater than zero.")
        return quantity


ChallanItemFormSet = inlineformset_factory(
    Challan,
    ChallanItem,
    form=ChallanItemForm,
    extra=1,
    can_delete=True,
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
            }),
        }

    def clean_discount_percent(self):
        discount = self.cleaned_data.get('discount_percent')
        if discount is not None and (discount < 0 or discount > 100):
            raise ValidationError("Discount must be between 0% and 100%.")
        return discount


BalanceFormSet = forms.modelformset_factory(
    Balance,
    form=BalanceForm,
    extra=1,
    can_delete=True,
)