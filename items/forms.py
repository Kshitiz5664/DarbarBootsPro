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
            'name', 'hns_code', 'price_retail', 'price_wholesale', 'quantity',
            'gst_percent', 'discount', 'image', 'is_active', 'is_featured'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter item name'
            }),
            'hns_code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'HNS Code'
            }),
            'price_retail': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Retail price (₹)'
            }),
            'price_wholesale': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Wholesale price (₹)'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Available stock'
            }),
            'gst_percent': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'GST %'
            }),
            'discount': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Discount %'
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
        Checks: file type, size, and extension.
        """
        image = self.cleaned_data.get('image')
        
        if image:
            # Allowed MIME types
            valid_mime_types = ['image/jpeg', 'image/png', 'image/gif']
            
            # Check content type
            if image.content_type not in valid_mime_types:
                raise forms.ValidationError('Only JPEG, PNG, and GIF images are allowed.')

            # Check file size (5MB limit)
            if image.size > 5 * 1024 * 1024:  # 5MB
                raise forms.ValidationError('Image file size cannot exceed 5MB.')

            # Extension-based safety check
            valid_extensions = ['.jpg', '.jpeg', '.png', '.gif']
            ext = image.name.lower().rsplit('.', 1)[-1]
            if f".{ext}" not in valid_extensions:
                raise forms.ValidationError('Invalid image file extension.')

        return image