# retailapp/forms.py
from django import forms
from django.core.exceptions import ValidationError
from decimal import Decimal

from .models import RetailInvoice, RetailInvoiceItem, RetailReturn
from items.models import Item


class RetailInvoiceForm(forms.ModelForm):
    """Form for creating/editing retail invoices with payment mode support"""
    
    class Meta:
        model = RetailInvoice
        fields = ['customer_name', 'customer_mobile', 'date', 'payment_mode', 'transaction_reference', 'notes']
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
            'payment_mode': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_payment_mode',
            }),
            'transaction_reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Transaction ID / Reference Number',
                'id': 'id_transaction_reference',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Notes (optional)',
            }),
        }
        help_texts = {
            'payment_mode': 'Select "Unpaid" if payment not received, or choose payment method',
            'transaction_reference': 'Optional: Enter transaction ID for UPI/Online/Card payments',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Make transaction_reference optional but show/hide based on payment mode
        self.fields['transaction_reference'].required = False
        
        # Add custom label with better formatting
        self.fields['payment_mode'].label = 'Payment Status & Method'
        self.fields['transaction_reference'].label = 'Transaction Reference (Optional)'
    
    def clean_customer_name(self):
        """Validate customer name is not empty"""
        name = self.cleaned_data.get('customer_name', '').strip()
        if not name:
            raise ValidationError('Customer name is required.')
        return name
    
    def clean_customer_mobile(self):
        """Validate mobile number format"""
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
    
    def clean_transaction_reference(self):
        """Clean and validate transaction reference"""
        transaction_ref = self.cleaned_data.get('transaction_reference') or ''
        transaction_ref = transaction_ref.strip() if transaction_ref else ''
        payment_mode = self.cleaned_data.get('payment_mode')
        
        # If payment mode is UNPAID, clear transaction reference
        if payment_mode == RetailInvoice.PaymentMode.UNPAID:
            return ''
        
        return transaction_ref
    
    def clean(self):
        """Cross-field validation for payment mode and transaction reference"""
        cleaned_data = super().clean()
        payment_mode = cleaned_data.get('payment_mode')
        transaction_ref = cleaned_data.get('transaction_reference') or ''
        transaction_ref = transaction_ref.strip() if transaction_ref else ''
        
        # If payment mode is UNPAID, ensure transaction reference is cleared
        if payment_mode == RetailInvoice.PaymentMode.UNPAID:
            cleaned_data['transaction_reference'] = ''
        else:
            cleaned_data['transaction_reference'] = transaction_ref
        
        # Optional: Warn if digital payment selected but no transaction ref
        if payment_mode in [
            RetailInvoice.PaymentMode.UPI,
            RetailInvoice.PaymentMode.ONLINE,
            RetailInvoice.PaymentMode.CARD
        ] and not transaction_ref:
            # This is just a warning, not an error
            # You can uncomment below to add a non-field error
            # self.add_error('transaction_reference', 
            #     'Transaction reference is recommended for digital payments.')
            pass
        
        return cleaned_data


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
        }),
        help_text='Use this if item is not in the list'
    )
    
    class Meta:
        model = RetailInvoiceItem
        fields = ['item', 'manual_item_name', 'quantity', 'rate', 'gst_percent', 'discount_percent']
        widgets = {
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'value': '1',
                'step': '1',
            }),
            'rate': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0.00',
            }),
            'gst_percent': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'max': '100',
                'value': '0',
                'placeholder': '0.00',
            }),
            'discount_percent': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'max': '100',
                'value': '0',
                'placeholder': '0.00',
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
        """Validate item form data"""
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
        """Validate return form data"""
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


class RetailInvoiceQuickPaymentForm(forms.Form):
    """
    Quick form to update payment status of an existing invoice.
    Can be used in dashboard for quick payment updates.
    """
    payment_mode = forms.ChoiceField(
        choices=RetailInvoice.PaymentMode.choices,
        widget=forms.Select(attrs={
            'class': 'form-select',
        }),
        help_text='Update payment status'
    )
    
    transaction_reference = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Transaction ID (optional)',
        }),
        help_text='Optional: Transaction reference for digital payments'
    )
    
    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance
        
        if instance:
            self.fields['payment_mode'].initial = instance.payment_mode
            self.fields['transaction_reference'].initial = instance.transaction_reference
    
    def clean(self):
        """Validate payment form"""
        cleaned_data = super().clean()
        payment_mode = cleaned_data.get('payment_mode')
        transaction_ref = cleaned_data.get('transaction_reference') or ''
        
        # Clear transaction reference if UNPAID
        if payment_mode == RetailInvoice.PaymentMode.UNPAID:
            cleaned_data['transaction_reference'] = ''
        else:
            cleaned_data['transaction_reference'] = transaction_ref.strip() if transaction_ref else ''
        
        return cleaned_data
    
    def save(self):
        """Apply payment changes to the invoice"""
        if not self.instance:
            raise ValueError('No invoice instance provided')
        
        self.instance.payment_mode = self.cleaned_data['payment_mode']
        self.instance.transaction_reference = self.cleaned_data.get('transaction_reference', '').strip()
        
        # Let the model's clean() method handle payment_date logic
        self.instance.full_clean()
        self.instance.save()
        
        return self.instance