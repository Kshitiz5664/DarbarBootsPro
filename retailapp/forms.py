# retailapp/forms.py
from django import forms
from django.core.exceptions import ValidationError
from decimal import Decimal

from .models import RetailInvoice, RetailInvoiceItem, RetailReturn
from items.models import Item


class RetailInvoiceForm(forms.ModelForm):
    """Form for creating/editing retail invoices"""
    
    class Meta:
        model = RetailInvoice
        fields = ['customer_name', 'customer_mobile', 'date', 'is_paid', 'notes']
        widgets = {
            'customer_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Customer name',
                'required': True,
            }),
            'customer_mobile': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Mobile number (optional)',
                'maxlength': '15',
            }),
            'date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'is_paid': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Notes (optional)',
            }),
        }
    
    def clean_customer_name(self):
        name = self.cleaned_data.get('customer_name', '').strip()
        if not name:
            raise ValidationError('Customer name is required.')
        return name
    
    def clean_customer_mobile(self):
        mobile = self.cleaned_data.get('customer_mobile', '')
        if mobile:
            mobile = mobile.strip()
            # Remove spaces and dashes for validation
            clean_mobile = mobile.replace(' ', '').replace('-', '')
            if not clean_mobile.isdigit():
                raise ValidationError('Mobile number should contain only digits.')
            if len(clean_mobile) < 10:
                raise ValidationError('Mobile number should be at least 10 digits.')
        return mobile


class RetailInvoiceItemForm(forms.ModelForm):
    """Form for invoice line items - used for validation reference"""
    
    item = forms.ModelChoiceField(
        queryset=Item.objects.filter(is_deleted=False, is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select item-select'}),
        help_text='Select from existing items or enter manual name below.'
    )
    
    manual_item_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Manual item name'
        })
    )
    
    class Meta:
        model = RetailInvoiceItem
        fields = ['item', 'manual_item_name', 'quantity', 'rate', 'gst_percent', 'discount_percent']
        widgets = {
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'value': '1',
            }),
            'rate': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
            }),
            'gst_percent': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'max': '100',
                'value': '0',
            }),
            'discount_percent': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'max': '100',
                'value': '0',
            }),
        }
    
    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.invoice = invoice
        
        # Pre-fill from existing item if editing
        if self.instance and self.instance.pk and self.instance.item:
            item = self.instance.item
            if not self.initial.get('rate'):
                self.initial['rate'] = getattr(item, 'price_retail', None) or getattr(item, 'price_wholesale', None)
            if not self.initial.get('gst_percent'):
                self.initial['gst_percent'] = getattr(item, 'gst_percent', Decimal('0.00'))
    
    def clean(self):
        cleaned_data = super().clean()
        item = cleaned_data.get('item')
        manual_name = cleaned_data.get('manual_item_name', '').strip()
        rate = cleaned_data.get('rate')
        quantity = cleaned_data.get('quantity')
        
        # Must have either item or manual name
        if not item and not manual_name:
            raise ValidationError('Please select an existing item or provide a manual item name.')
        
        # Validate rate
        if rate is None or Decimal(str(rate)) < 0:
            raise ValidationError({'rate': 'Rate must be a non-negative number.'})
        
        # Validate quantity
        if quantity is None or quantity <= 0:
            raise ValidationError({'quantity': 'Quantity must be at least 1.'})
        
        return cleaned_data


class RetailReturnForm(forms.ModelForm):
    """Form for creating returns against an invoice"""
    
    item = forms.ModelChoiceField(
        queryset=RetailInvoiceItem.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Select an invoice item to auto-calculate amount, or leave empty for manual return.'
    )
    
    class Meta:
        model = RetailReturn
        fields = ['item', 'return_date', 'quantity', 'amount', 'reason', 'image']
        widgets = {
            'return_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'value': '1',
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': 'Auto-calculated if item selected',
            }),
            'reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Reason for return (optional)',
            }),
            'image': forms.ClearableFileInput(attrs={
                'class': 'form-control',
            }),
        }
    
    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.invoice = invoice
        
        if invoice:
            # Only show active items from this invoice
            self.fields['item'].queryset = invoice.retail_items.filter(is_active=True)
            self.fields['item'].label_from_instance = lambda obj: f"{obj.display_name} (Qty: {obj.quantity}, ₹{obj.total})"
    
    def clean(self):
        cleaned_data = super().clean()
        item = cleaned_data.get('item')
        quantity = cleaned_data.get('quantity', 1)
        amount = cleaned_data.get('amount')
        
        if item:
            # Validate quantity doesn't exceed available
            from django.db.models import Sum
            prior_returns = RetailReturn.objects.filter(
                item=item,
                is_active=True
            ).exclude(pk=self.instance.pk if self.instance.pk else None).aggregate(
                total=Sum('quantity')
            )['total'] or 0
            
            available = max(item.quantity - prior_returns, 0)
            
            if quantity > available:
                raise ValidationError({
                    'quantity': f'Cannot return {quantity} units. Only {available} unit(s) available for return.'
                })
        else:
            # Manual return - amount is required
            if not amount or Decimal(str(amount)) <= 0:
                raise ValidationError({
                    'amount': 'For manual returns without selecting an item, please provide a positive amount.'
                })
        
        return cleaned_data