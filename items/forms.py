from django.core.files.uploadedfile import UploadedFile
from django import forms
from django.core.exceptions import ValidationError
from .models import Item
import os



class ItemForm(forms.ModelForm):
    """
    Form for creating and updating inventory items.
    Includes comprehensive validation for prices, percentages, and images.
    """
    
    image = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*'
        }),
        help_text='Upload an image (JPEG, PNG, or GIF only, max 5MB).'
    )

    class Meta:
        model = Item
        fields = [
            'name', 'price_retail', 'price_wholesale', 'quantity',
            'gst_percent', 'discount', 'image', 'is_active', 'is_featured'
        ]
        # ✅ FIXED: Removed 'hns_code' from fields - it's auto-generated and non-editable
        
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter item name',
                'required': True
            }),
            'price_retail': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Retail price (₹)',
                'step': '0.01',
                'min': '0'
            }),
            'price_wholesale': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Wholesale price (₹)',
                'step': '0.01',
                'min': '0'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Available stock',
                'min': '0'
            }),
            'gst_percent': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'GST %',
                'step': '0.01',
                'min': '0',
                'max': '50'
            }),
            'discount': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Discount %',
                'step': '0.01',
                'min': '0',
                'max': '100'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'is_featured': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def clean(self):
        """Validate form-level business logic."""
        cleaned_data = super().clean()
        price_retail = cleaned_data.get('price_retail')
        price_wholesale = cleaned_data.get('price_wholesale')
        discount = cleaned_data.get('discount')
        gst = cleaned_data.get('gst_percent')

        # Price validation
        if price_retail and price_wholesale and price_wholesale > price_retail:
            self.add_error('price_wholesale', 'Wholesale price cannot exceed retail price.')

        # Discount validation
        if discount and (discount < 0 or discount > 100):
            self.add_error('discount', 'Discount must be between 0% and 100%.')

        # GST validation
        if gst and (gst < 0 or gst > 50):
            self.add_error('gst_percent', 'GST must be between 0% and 50%.')

        return cleaned_data

    def clean_image(self):
        """
        Validate uploaded image file.
        Handles BOTH:
        - New uploads (UploadedFile)
        - Existing images on edit (ImageFieldFile)
        """
        image = self.cleaned_data.get('image')

        # Case 1: No image provided
        if not image:
            return image

        # Case 2: Editing existing item WITHOUT uploading a new image
        # image is ImageFieldFile → already stored → skip upload validations
        if not isinstance(image, UploadedFile):
            return image

        # Case 3: New image upload → full validation applies
        valid_mime_types = ['image/jpeg', 'image/png', 'image/gif']
        if image.content_type not in valid_mime_types:
            raise ValidationError('Only JPEG, PNG, and GIF images are allowed.')

        # Size check (5MB)
        if image.size > 5 * 1024 * 1024:
            raise ValidationError('Image file size cannot exceed 5MB.')

        # Extension check
        valid_extensions = ['.jpg', '.jpeg', '.png', '.gif']
        ext = os.path.splitext(image.name)[1].lower()
        if ext not in valid_extensions:
            raise ValidationError('Invalid image file extension.')

        return image


class StockAdjustmentForm(forms.Form):
    """
    Form for manual stock adjustments (add/remove inventory).
    """
    ADJUSTMENT_TYPES = [
        ('add', 'Add Stock'),
        ('remove', 'Remove Stock'),
    ]
    
    adjustment_type = forms.ChoiceField(
        choices=ADJUSTMENT_TYPES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label='Adjustment Type'
    )
    quantity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter quantity',
            'min': '1'
        }),
        label='Quantity'
    )
    reason = forms.ChoiceField(
        choices=[
            ('restock', 'Restock/Purchase'),
            ('return', 'Customer Return'),
            ('damaged', 'Damaged/Lost'),
            ('adjustment', 'Manual Adjustment'),
        ],
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Reason'
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Additional notes (optional)'
        }),
        label='Notes'
    )