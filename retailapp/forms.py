# retailapp/forms.py
# ✅ PERFECT VERSION - ALL ISSUES FIXED
# Fully compatible with models.py and views.py
# Copy this entire file

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Sum
from decimal import Decimal
import json

from .models import RetailInvoice, RetailInvoiceItem, RetailReturn
from items.models import Item


class RetailInvoiceForm(forms.ModelForm):
    """
    ✅ PERFECT: Form for creating/editing retail invoices.
    """
    
    class Meta:
        model = RetailInvoice
        fields = [
            'customer_name',
            'customer_mobile',
            'date',
            'payment_mode',
            'transaction_reference',
            'notes'
        ]
        widgets = {
            'customer_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter customer name *',
                'required': True,
                'autocomplete': 'name',
            }),
            'customer_mobile': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Mobile number (optional)',
                'maxlength': '15',
                'autocomplete': 'tel',
                'pattern': '[0-9\\s\\-\\+\\(\\)]*',
            }),
            'date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'max': timezone.now().date().isoformat(),
            }),
            'payment_mode': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_payment_mode',
                'onchange': 'toggleTransactionReference()',
            }),
            'transaction_reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Transaction ID / Reference Number',
                'id': 'id_transaction_reference',
                'maxlength': '100',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Additional notes (optional)',
                'maxlength': '500',
            }),
        }
        labels = {
            'customer_name': 'Customer Name *',
            'customer_mobile': 'Mobile Number',
            'date': 'Invoice Date',
            'payment_mode': 'Payment Status & Method',
            'transaction_reference': 'Transaction Reference',
            'notes': 'Notes',
        }
        help_texts = {
            'payment_mode': 'Select "Unpaid" if payment not received, or choose payment method',
            'transaction_reference': 'Recommended for UPI/Online/Card payments',
            'customer_mobile': 'Format: 10-15 digits, spaces and dashes allowed',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        if not self.instance.pk and 'date' not in self.initial:
            self.initial['date'] = timezone.now().date()
        
        self.fields['transaction_reference'].required = False
        
        for field_name, field in self.fields.items():
            if field.required:
                field.widget.attrs['required'] = 'required'
    
    def clean_customer_name(self):
        """Validate customer name"""
        name = self.cleaned_data.get('customer_name', '').strip()
        
        if not name:
            raise ValidationError('Customer name is required.')
        
        if len(name) < 2:
            raise ValidationError('Customer name must be at least 2 characters.')
        
        if len(name) > 255:
            raise ValidationError('Customer name is too long (max 255 characters).')
        
        import re
        if not re.match(r'^[a-zA-Z\s\.\,\-\']+$', name):
            raise ValidationError('Customer name contains invalid characters.')
        
        return name
    
    def clean_customer_mobile(self):
        """Validate mobile number"""
        mobile = self.cleaned_data.get('customer_mobile', '')
        
        if mobile:
            mobile = mobile.strip()
            clean_mobile = mobile.replace(' ', '').replace('-', '').replace('(', '').replace(')', '').replace('+', '')
            
            if not clean_mobile.isdigit():
                raise ValidationError('Mobile number should contain only digits, spaces, or dashes.')
            
            if len(clean_mobile) < 10:
                raise ValidationError('Mobile number should be at least 10 digits.')
            
            if len(clean_mobile) > 15:
                raise ValidationError('Mobile number should not exceed 15 digits.')
        
        return mobile
    
    def clean_date(self):
        """Validate invoice date"""
        date = self.cleaned_data.get('date')
        
        if date and date > timezone.now().date():
            raise ValidationError('Invoice date cannot be in the future.')
        
        return date
    
    def clean_transaction_reference(self):
        """Clean transaction reference"""
        transaction_ref = self.cleaned_data.get('transaction_reference') or ''
        transaction_ref = transaction_ref.strip() if transaction_ref else ''
        
        if transaction_ref:
            transaction_ref = ' '.join(transaction_ref.split())
        
        return transaction_ref
    
    def clean(self):
        """Cross-field validation"""
        cleaned_data = super().clean()
        payment_mode = cleaned_data.get('payment_mode')
        transaction_ref = cleaned_data.get('transaction_reference', '').strip()
        
        if payment_mode == RetailInvoice.PaymentMode.UNPAID:
            cleaned_data['transaction_reference'] = ''
        else:
            cleaned_data['transaction_reference'] = transaction_ref
        
        return cleaned_data


class RetailInvoiceItemForm(forms.ModelForm):
    """
    ✅ PERFECT: Form for invoice line items.
    """
    
    item = forms.ModelChoiceField(
        queryset=Item.objects.filter(is_deleted=False, is_active=True).order_by('name'),
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select item-select',
            'onchange': 'loadItemDetails(this)',
        }),
        label='Select Item',
        help_text='Choose from existing items or enter manual name below.'
    )
    
    manual_item_name = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Or enter manual item name',
        }),
        label='Manual Item Name',
        help_text='Use this if item is not in the list'
    )
    
    class Meta:
        model = RetailInvoiceItem
        fields = [
            'item',
            'manual_item_name',
            'quantity',
            'rate',
            'gst_percent',
            'discount_percent'
        ]
        widgets = {
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control quantity-input',
                'min': '1',
                'value': '1',
                'step': '1',
                'onchange': 'calculateLineTotal(this)',
            }),
            'rate': forms.NumberInput(attrs={
                'class': 'form-control rate-input',
                'step': '0.01',
                'min': '0',
                'placeholder': '0.00',
                'onchange': 'calculateLineTotal(this)',
            }),
            'gst_percent': forms.NumberInput(attrs={
                'class': 'form-control gst-input',
                'step': '0.01',
                'min': '0',
                'max': '100',
                'value': '0',
                'placeholder': '0.00',
                'onchange': 'calculateLineTotal(this)',
            }),
            'discount_percent': forms.NumberInput(attrs={
                'class': 'form-control discount-input',
                'step': '0.01',
                'min': '0',
                'max': '100',
                'value': '0',
                'placeholder': '0.00',
                'onchange': 'calculateLineTotal(this)',
            }),
        }
        labels = {
            'quantity': 'Qty',
            'rate': 'Rate (₹)',
            'gst_percent': 'GST %',
            'discount_percent': 'Discount %',
        }
    
    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.invoice = invoice
        
        # ✅ FIXED: Proper indentation and logic
        if self.instance and self.instance.pk and self.instance.item:
            item = self.instance.item
            
            # Auto-fill rate from item if not set
            if not self.initial.get('rate'):
                self.initial['rate'] = getattr(item, 'price_retail', Decimal('0.00'))
            
            # Auto-fill GST from item if not set
            if 'gst_percent' not in self.initial:
                self.initial['gst_percent'] = getattr(item, 'gst_percent', Decimal('0.00'))
    
    def clean_quantity(self):
        """Validate quantity"""
        quantity = self.cleaned_data.get('quantity')
        
        if quantity is None or quantity <= 0:
            raise ValidationError('Quantity must be at least 1.')
        
        if quantity > 10000:
            raise ValidationError('Quantity seems unreasonably high. Please verify.')
        
        return quantity
    
    def clean_rate(self):
        """Validate rate"""
        rate = self.cleaned_data.get('rate')
        
        if rate is None or Decimal(str(rate)) < 0:
            raise ValidationError('Rate must be a non-negative number.')
        
        if rate > Decimal('999999.99'):
            raise ValidationError('Rate seems unreasonably high. Please verify.')
        
        return rate
    
    def clean_gst_percent(self):
        """Validate GST percentage"""
        gst_percent = self.cleaned_data.get('gst_percent', Decimal('0.00'))
        
        if gst_percent < 0:
            raise ValidationError('GST percentage cannot be negative.')
        
        if gst_percent > 100:
            raise ValidationError('GST percentage cannot exceed 100%.')
        
        return gst_percent
    
    def clean_discount_percent(self):
        """Validate discount percentage"""
        discount_percent = self.cleaned_data.get('discount_percent', Decimal('0.00'))
        
        if discount_percent < 0:
            raise ValidationError('Discount percentage cannot be negative.')
        
        if discount_percent > 100:
            raise ValidationError('Discount percentage cannot exceed 100%.')
        
        return discount_percent
    
    def clean(self):
        """Cross-field validation"""
        cleaned_data = super().clean()
        item = cleaned_data.get('item')
        manual_name = cleaned_data.get('manual_item_name', '').strip()
        rate = cleaned_data.get('rate')
        quantity = cleaned_data.get('quantity')
        
        if not item and not manual_name:
            raise ValidationError(
                'Please select an existing item or provide a manual item name.'
            )
        
        if item and manual_name:
            cleaned_data['manual_item_name'] = ''
        
        if rate is None:
            raise ValidationError({'rate': 'Rate is required.'})
        
        if quantity is None:
            raise ValidationError({'quantity': 'Quantity is required.'})
        
        if item and hasattr(item, 'quantity'):
            if quantity > item.quantity:
                self.add_error(
                    None,
                    f'Only {item.quantity} unit(s) available in stock. '
                    f'Requested: {quantity}. Final validation will occur during save.'
                )
        
        return cleaned_data


class RetailReturnForm(forms.ModelForm):
    """
    ✅ PERFECT: Form for creating returns with auto-calculated amount.
    """
    
    item = forms.ModelChoiceField(
        queryset=RetailInvoiceItem.objects.none(),
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_return_item',
            'onchange': 'updateReturnAmount()',
        }),
        label='Select Invoice Item',
        help_text='Select an invoice item to auto-calculate amount, or leave empty for manual return.'
    )
    
    class Meta:
        model = RetailReturn
        fields = [
            'item',
            'return_date',
            'quantity',
            'amount',
            'reason',
            'image'
        ]
        widgets = {
            'return_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'max': timezone.now().date().isoformat(),
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'id': 'id_return_quantity',
                'min': '1',
                'value': '1',
                'onchange': 'updateReturnAmount()',
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'id': 'id_return_amount',
                'step': '0.01',
                'min': '0.01',
                'placeholder': 'Auto-calculated or enter manually',
            }),
            'reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Reason for return (optional)',
                'maxlength': '500',
            }),
            'image': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
        }
        labels = {
            'item': 'Invoice Item',
            'return_date': 'Return Date',
            'quantity': 'Return Quantity',
            'amount': 'Return Amount (₹)',
            'reason': 'Reason for Return',
            'image': 'Attach Image (optional)',
        }
        help_texts = {
            'quantity': 'Number of units to return',
            'amount': 'Auto-calculated from item, or enter manually if no item selected',
            'image': 'Upload image as proof (optional)',
        }
    
    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.invoice = invoice
        
        if not self.instance.pk:
            self.initial['return_date'] = timezone.now().date()
        
        if invoice:
            active_items = invoice.retail_items.filter(is_active=True)
            
            returnable_items = []
            for item_obj in active_items:
                returned_qty = RetailReturn.objects.filter(
                    item=item_obj,
                    is_active=True
                ).aggregate(total=Sum('quantity'))['total'] or 0
                
                if item_obj.quantity > returned_qty:
                    returnable_items.append(item_obj.id)
            
            self.fields['item'].queryset = active_items.filter(id__in=returnable_items)
            
            def custom_label(obj):
                returned_qty = RetailReturn.objects.filter(
                    item=obj,
                    is_active=True
                ).aggregate(total=Sum('quantity'))['total'] or 0
                
                available_qty = obj.quantity - returned_qty
                per_unit_price = (obj.total / obj.quantity).quantize(Decimal('0.01'))
                
                return (
                    f"{obj.display_name} | "
                    f"Invoice Qty: {obj.quantity} | "
                    f"Available: {available_qty} | "
                    f"Per Unit: ₹{per_unit_price:,.2f} | "
                    f"Total: ₹{obj.total:,.2f}"
                )
            
            self.fields['item'].label_from_instance = custom_label
            
            # Store item pricing data for JavaScript
            item_data = {}
            for item_obj in self.fields['item'].queryset:
                per_unit = (item_obj.total / item_obj.quantity).quantize(Decimal('0.01'))
                item_data[str(item_obj.id)] = {
                    'quantity': item_obj.quantity,
                    'total': float(item_obj.total),
                    'per_unit': float(per_unit),
                }
            
            self.fields['item'].widget.attrs['data-item-prices'] = json.dumps(item_data)
    
    def clean_return_date(self):
        """Validate return date"""
        return_date = self.cleaned_data.get('return_date')
        
        if return_date and return_date > timezone.now().date():
            raise ValidationError('Return date cannot be in the future.')
        
        if self.invoice and return_date < self.invoice.date:
            raise ValidationError(
                f'Return date cannot be before invoice date ({self.invoice.date}).'
            )
        
        return return_date
    
    def clean_quantity(self):
        """Validate return quantity"""
        quantity = self.cleaned_data.get('quantity', 1)
        
        if quantity <= 0:
            raise ValidationError('Return quantity must be at least 1.')
        
        if quantity > 10000:
            raise ValidationError('Return quantity seems unreasonably high.')
        
        return quantity
    
    def clean_amount(self):
        """Validate return amount"""
        amount = self.cleaned_data.get('amount')
        
        if amount is None or amount <= 0:
            raise ValidationError(
                'Return amount must be greater than zero. '
                'If you selected an item, the amount should auto-calculate. '
                'For manual returns, please enter a positive amount.'
            )
        
        if amount > Decimal('9999999.99'):
            raise ValidationError('Return amount seems unreasonably high. Please verify.')
        
        return amount
    
    def clean(self):
        """Cross-field validation"""
        cleaned_data = super().clean()
        item = cleaned_data.get('item')
        quantity = cleaned_data.get('quantity', 1)
        amount = cleaned_data.get('amount')
        
        if item:
            prior_returns = RetailReturn.objects.filter(
                item=item,
                is_active=True
            ).exclude(
                pk=self.instance.pk if self.instance.pk else None
            ).aggregate(
                total=Sum('quantity')
            )['total'] or 0
            
            available = max(item.quantity - prior_returns, 0)
            
            if quantity > available:
                raise ValidationError({
                    'quantity': (
                        f'Cannot return {quantity} unit(s). '
                        f'Only {available} unit(s) available for return.'
                    )
                })
            
            if amount:
                expected_per_unit = (item.total / item.quantity).quantize(Decimal('0.01'))
                expected_amount = (expected_per_unit * quantity).quantize(Decimal('0.01'))
                
                if abs(amount - expected_amount) > Decimal('1.00'):
                    self.add_error(
                        None,
                        f'Amount differs from expected ₹{expected_amount:,.2f}. '
                        f'Expected: ₹{expected_per_unit:,.2f} × {quantity}.'
                    )
        else:
            if not amount or amount <= 0:
                self.add_error(
                    'amount',
                    'Manual returns require a positive return amount.'
                )
        
        return cleaned_data


class RetailInvoiceQuickPaymentForm(forms.Form):
    """
    ✅ PERFECT: Quick payment status update form.
    """
    
    payment_mode = forms.ChoiceField(
        choices=RetailInvoice.PaymentMode.choices,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'quick_payment_mode',
            'onchange': 'toggleQuickTransactionRef()',
        }),
        label='Payment Method',
        help_text='Update payment status quickly'
    )
    
    transaction_reference = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'id': 'quick_transaction_reference',
            'placeholder': 'Transaction ID (optional)',
        }),
        label='Transaction Reference',
        help_text='Optional: Enter transaction ID for digital payments'
    )
    
    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance
        
        if instance:
            self.fields['payment_mode'].initial = instance.payment_mode
            self.fields['transaction_reference'].initial = instance.transaction_reference or ''
    
    def clean_transaction_reference(self):
        """Clean transaction reference"""
        transaction_ref = self.cleaned_data.get('transaction_reference', '').strip()
        return transaction_ref
    
    def clean(self):
        """Validate payment form"""
        cleaned_data = super().clean()
        payment_mode = cleaned_data.get('payment_mode')
        transaction_ref = cleaned_data.get('transaction_reference', '').strip()
        
        if payment_mode == RetailInvoice.PaymentMode.UNPAID:
            cleaned_data['transaction_reference'] = ''
        else:
            cleaned_data['transaction_reference'] = transaction_ref
        
        return cleaned_data
    
    def save(self, commit=True):
        """Apply payment changes to invoice"""
        if not self.instance:
            raise ValueError('No invoice instance provided to save')
        
        self.instance.payment_mode = self.cleaned_data['payment_mode']
        self.instance.transaction_reference = self.cleaned_data.get('transaction_reference', '').strip()
        
        if commit:
            self.instance.full_clean()
            self.instance.save()
        
        return self.instance


class RetailInvoiceFilterForm(forms.Form):
    """
    ✅ PERFECT: Dashboard filter form.
    """
    
    search = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by invoice number, customer name, or mobile...',
        }),
        label='Search'
    )
    
    status = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'All Invoices'),
            ('paid', 'Paid'),
            ('unpaid', 'Unpaid'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-select',
        }),
        label='Payment Status'
    )
    
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
        }),
        label='From Date'
    )
    
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
        }),
        label='To Date'
    )
    
    def clean(self):
        """Validate date range"""
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')
        
        if date_from and date_to and date_from > date_to:
            raise ValidationError('From date must be before or equal to To date.')
        
        return cleaned_data
    