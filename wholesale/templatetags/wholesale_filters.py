# wholesale/templatetags/wholesale_filters.py
from django import template

register = template.Library()


@register.filter(name='format_kpi_label')
def format_kpi_label(value):
    """
    Format KPI key to human-readable label.
    Example: 'total_invoices' -> 'Invoices'
             'recent_payments' -> 'Payments'
    """
    if value is None:
        return value
    
    # Replace underscores with spaces
    formatted = str(value).replace('_', ' ')
    
    # Remove common prefixes
    prefixes_to_remove = ['total ', 'recent ', 'all ']
    formatted_lower = formatted.lower()
    
    for prefix in prefixes_to_remove:
        if formatted_lower.startswith(prefix):
            formatted = formatted[len(prefix):]
            break
    
    # Title case the result
    return formatted.strip().title()


@register.filter(name='is_currency_field')
def is_currency_field(key):
    """
    Check if the KPI key represents a currency value.
    Returns True if key contains currency-related words.
    """
    if key is None:
        return False
    
    currency_keywords = [
        'amount', 'pending', 'invoiced', 'received', 
        'paid', 'balance', 'revenue', 'total', 'price',
        'cost', 'payment', 'due'
    ]
    key_lower = str(key).lower()
    return any(keyword in key_lower for keyword in currency_keywords)


@register.filter(name='replace_str')
def replace_str(value, arg):
    """
    Replace occurrences in string.
    Usage: {{ value|replace_str:"old_string,new_string" }}
    """
    if value is None:
        return value
    
    if ',' in arg:
        old, new = arg.split(',', 1)
    else:
        old = arg
        new = ''
    
    return str(value).replace(old, new)