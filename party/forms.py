from django import forms
from django.core.exceptions import ValidationError
from .models import Party
import re


class PartyForm(forms.ModelForm):
    """
    Form for creating and updating Party records.
    Includes validation for name uniqueness, phone format, and email.
    """
    
    class Meta:
        model = Party
        fields = ['name', 'contact_person', 'phone', 'email', 'address']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Party Name',
                'required': True
            }),
            'contact_person': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Contact Person'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+91XXXXXXXXXX'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'email@example.com'
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Complete Address'
            }),
        }

    def clean_name(self):
        """Validate party name uniqueness (case-insensitive)."""
        name = self.cleaned_data.get('name')
        
        # Handle None
        if not name:
            raise ValidationError("Party name is required.")
        
        # Strip whitespace
        name = name.strip()
        
        if not name:
            raise ValidationError("Party name is required.")
        
        if len(name) < 2:
            raise ValidationError("Party name must be at least 2 characters long.")
        
        # Check uniqueness (excluding current instance in edit mode)
        if self.instance and self.instance.pk:
            # Editing existing party
            if Party.all_objects.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
                raise ValidationError("A party with this name already exists.")
        else:
            # Creating new party
            if Party.all_objects.filter(name__iexact=name).exists():
                raise ValidationError("A party with this name already exists.")
        
        return name

    def clean_phone(self):
        """Validate and format phone number."""
        phone = self.cleaned_data.get('phone')
        
        # Handle None or empty string
        if not phone:
            return ''
        
        # Strip whitespace
        phone = phone.strip()
        
        if not phone:
            return ''
        
        # Remove spaces, hyphens, and special characters except +
        phone_cleaned = ''.join(c for c in phone if c.isdigit() or c == '+')
        
        # Extract only digits for validation
        phone_digits = ''.join(filter(str.isdigit, phone_cleaned))
        
        # Validate minimum length
        if len(phone_digits) < 10:
            raise ValidationError("Phone number must be at least 10 digits.")
        
        # Validate maximum length
        if len(phone_digits) > 15:
            raise ValidationError("Phone number cannot exceed 15 digits.")
        
        # Return cleaned phone number
        return phone_cleaned

    def clean_email(self):
        """Validate email format."""
        email = self.cleaned_data.get('email')
        
        # Handle None or empty string
        if not email:
            return ''
        
        # Strip whitespace
        email = email.strip()
        
        if not email:
            return ''
        
        # Additional email validation
        if len(email) > 254:
            raise ValidationError("Email address is too long.")
        
        # Check for valid email pattern
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            raise ValidationError("Enter a valid email address.")
        
        return email.lower()

    def clean_contact_person(self):
        """Validate and sanitize contact person name."""
        contact_person = self.cleaned_data.get('contact_person')
        
        # Handle None or empty string
        if not contact_person:
            return ''
        
        # Strip whitespace
        contact_person = contact_person.strip()
        
        if not contact_person:
            return ''
        
        if len(contact_person) < 2:
            raise ValidationError("Contact person name must be at least 2 characters long.")
        
        return contact_person

    def clean_address(self):
        """Validate and sanitize address."""
        address = self.cleaned_data.get('address')
        
        # Handle None or empty string
        if not address:
            return ''
        
        # Strip whitespace
        address = address.strip()
        
        if not address:
            return ''
        
        if len(address) < 5:
            raise ValidationError("Address must be at least 5 characters long.")
        
        return address