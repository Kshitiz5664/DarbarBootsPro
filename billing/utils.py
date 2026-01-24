# billing/utils.py
"""
Billing Utilities
=================
Helper functions for billing operations, notifications, and data processing.
"""

import logging
import requests
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from django.conf import settings
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.db.models import Sum, F, DecimalField, ExpressionWrapper, Q
from django.db import models

from party.models import Party
from .models import Payment, Invoice, InvoiceItem, Return

logger = logging.getLogger(__name__)


# ================================================================
# NOTIFICATION FUNCTIONS
# ================================================================

def send_payment_receipt(party: Party, payment: Payment) -> bool:
    """
    Send payment receipt to party via WhatsApp or Email.
    
    Args:
        party: Party instance
        payment: Payment instance
        
    Returns:
        bool: True if sent successfully via any method
        
    Raises:
        Exception: Only if both WhatsApp and Email fail
    """
    if not party:
        logger.warning("❌ No party provided for receipt")
        return False
    
    if not payment:
        logger.warning("❌ No payment provided for receipt")
        return False
    
    # Generate message
    message = generate_payment_message(party, payment)
    
    success = False
    
    # 1️⃣ Try WhatsApp first
    if party.phone:
        whatsapp_success = send_whatsapp_message(
            phone=party.phone,
            message=message,
            context={
                'payment': payment,
                'party': party
            }
        )
        if whatsapp_success:
            logger.info(f"✅ WhatsApp receipt sent to {party.name} ({party.phone})")
            success = True
    
    # 2️⃣ Try Email (always attempt as backup or primary)
    if party.email:
        email_success = send_payment_email(party, payment, message)
        if email_success:
            logger.info(f"✅ Email receipt sent to {party.email}")
            success = True
    
    if not success:
        logger.warning(
            f"⚠️ Could not send receipt to {party.name} "
            f"(Phone: {party.phone or 'N/A'}, Email: {party.email or 'N/A'})"
        )
    
    return success


def send_whatsapp_message(phone: str, message: str, context: Optional[Dict] = None) -> bool:
    """
    Send WhatsApp message via configured API.
    
    Args:
        phone: Phone number (with country code)
        message: Message text
        context: Optional context for template rendering
        
    Returns:
        bool: True if sent successfully
    """
    whatsapp_api_url = getattr(settings, 'WHATSAPP_API_URL', None)
    whatsapp_api_key = getattr(settings, 'WHATSAPP_API_KEY', None)
    
    if not whatsapp_api_url:
        logger.debug("WhatsApp API not configured")
        return False
    
    try:
        # Clean phone number
        clean_phone = ''.join(filter(str.isdigit, phone))
        
        # ✅ FIXED: Get country code from settings
        default_country_code = getattr(settings, 'WHATSAPP_COUNTRY_CODE', '91')
        
        # Ensure country code
        if not clean_phone.startswith(default_country_code):
            clean_phone = f'{default_country_code}{clean_phone}'
        
        
        
        # API payload (adjust based on your WhatsApp provider)
        payload = {
            'phone': clean_phone,
            'message': message,
            'type': 'text'
        }
        
        headers = {}
        if whatsapp_api_key:
            headers['Authorization'] = f'Bearer {whatsapp_api_key}'
        
        # Send request
        response = requests.post(
            whatsapp_api_url,
            json=payload,
            headers=headers,
            timeout=10
        )
        
        if response.status_code in [200, 201]:
            logger.info(f"✅ WhatsApp message sent to {clean_phone}")
            return True
        else:
            logger.warning(
                f"⚠️ WhatsApp API error {response.status_code}: {response.text[:200]}"
            )
            return False
            
    except requests.exceptions.Timeout:
        logger.error("❌ WhatsApp API timeout")
        return False
    except Exception as e:
        logger.error(f"❌ WhatsApp send failed: {e}", exc_info=True)
        return False


def send_payment_email(party: Party, payment: Payment, plain_message: str) -> bool:
    """
    Send payment receipt via email (with HTML template).
    
    Args:
        party: Party instance
        payment: Payment instance
        plain_message: Plain text message (fallback)
        
    Returns:
        bool: True if sent successfully
    """
    if not party.email:
        return False
    
    try:
        subject = f'Payment Receipt - {payment.payment_number or f"PAY-{payment.id}"}'
        
        # Try to render HTML template
        try:
            html_message = render_to_string('billing/emails/payment_receipt.html', {
                'party': party,
                'payment': payment,
                'invoice': payment.invoice,
            })
        except Exception:
            html_message = None
        
        # Create email
        if html_message:
            email = EmailMultiAlternatives(
                subject=subject,
                body=plain_message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
                to=[party.email]
            )
            email.attach_alternative(html_message, "text/html")
            email.send(fail_silently=False)
        else:
            # Fallback to plain text
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
                recipient_list=[party.email],
                fail_silently=False
            )
        
        logger.info(f"✅ Email sent to {party.email}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Email send failed for {party.email}: {e}", exc_info=True)
        return False


def generate_payment_message(party: Party, payment: Payment) -> str:
    """
    Generate payment receipt message text.
    
    Args:
        party: Party instance
        payment: Payment instance
        
    Returns:
        str: Formatted receipt message
    """
    invoice_number = payment.invoice.invoice_number if payment.invoice else 'N/A'
    
    # Get invoice details if linked
    if payment.invoice:
        total_amount = payment.invoice.total_amount or Decimal('0.00')
        total_paid = payment.invoice.total_paid or Decimal('0.00')
        balance_due = payment.invoice.balance_due or Decimal('0.00')
        status = "PAID IN FULL ✅" if payment.invoice.is_paid else f"Balance Due: ₹{balance_due:,.2f}"
    else:
        total_amount = payment.amount
        total_paid = payment.amount
        balance_due = Decimal('0.00')
        status = "General Payment"
    
    message = f"""
🧾 PAYMENT RECEIPT

Dear {party.name},

We have received your payment.

Payment Details:
━━━━━━━━━━━━━━━━
💰 Amount Paid: ₹{payment.amount:,.2f}
📅 Date: {payment.date.strftime('%d %b %Y')}
💳 Mode: {payment.get_mode_display()}
📋 Invoice: {invoice_number}

Invoice Summary:
━━━━━━━━━━━━━━━━
💵 Total Amount: ₹{total_amount:,.2f}
✅ Paid So Far: ₹{total_paid:,.2f}
📊 Status: {status}

Payment Reference: {payment.payment_number or f'PAY-{payment.id}'}

Thank you for your payment! 🙏

---
{getattr(settings, 'COMPANY_NAME', 'Your Company')}
{getattr(settings, 'COMPANY_PHONE', '')}
    """.strip()
    
    return message


# ================================================================
# INVOICE HELPER FUNCTIONS
# ================================================================

def get_invoice_queryset_with_totals():
    """
    Get Invoice queryset annotated with computed totals.
    
    Returns:
        QuerySet: Annotated with total_return_sum and total_amount
    """
    return (
        Invoice.objects
        .filter(is_active=True)
        .annotate(
            total_return_sum=Sum(
                'returns__amount',
                filter=Q(returns__is_active=True),
                default=Decimal('0.00')
            )
        )
        .annotate(
            total_paid_sum=Sum(
                'payments__amount',
                filter=Q(payments__is_active=True),
                default=Decimal('0.00')
            )
        )
        .annotate(
            computed_total=ExpressionWrapper(
                F('base_amount') - F('total_return_sum'),
                output_field=DecimalField(max_digits=14, decimal_places=2)
            )
        )
        .annotate(
            computed_balance=ExpressionWrapper(
                F('computed_total') - F('total_paid_sum'),
                output_field=DecimalField(max_digits=14, decimal_places=2)
            )
        )
    )


def get_pending_invoices_for_party(party: Party) -> List[Invoice]:
    """
    Get all pending (unpaid) invoices for a party.
    
    Args:
        party: Party instance
        
    Returns:
        List of Invoice instances with balance due
    """
    invoices = Invoice.objects.filter(
        party=party,
        is_paid=False,
        is_active=True
    ).prefetch_related('payments', 'returns').order_by('-date')
    
    # Filter to only those with actual balance
    pending = []
    for inv in invoices:
        if inv.balance_due > Decimal('0.00'):
            pending.append(inv)
    
    return pending


def calculate_party_outstanding(party: Party) -> Dict[str, Decimal]:
    """
    Calculate party's total outstanding balance.
    
    Args:
        party: Party instance
        
    Returns:
        Dict with 'total_invoiced', 'total_paid', 'outstanding'
    """
    total_invoiced = sum(
        inv.total_amount for inv in party.invoices.filter(is_active=True)
    )
    
    total_paid = sum(
        pay.amount for pay in party.payments.filter(is_active=True)
    )
    
    outstanding = total_invoiced - total_paid
    
    return {
        'total_invoiced': total_invoiced,
        'total_paid': total_paid,
        'outstanding': max(outstanding, Decimal('0.00'))
    }


# ================================================================
# RETURN HELPER FUNCTIONS
# ================================================================

def get_returnable_items_for_invoice(invoice: Invoice) -> List[Dict]:
    """
    Get all items from invoice that can still be returned.
    
    Args:
        invoice: Invoice instance
        
    Returns:
        List of dicts with item details and returnable quantities
    """
    from .models import ReturnItem
    
    returnable_items = []
    
    for inv_item in invoice.invoice_items.filter(is_active=True):
        # Skip items without Item reference
        if not inv_item.item:
            continue
        
        # Calculate already returned
        already_returned = ReturnItem.objects.filter(
            invoice_item=inv_item,
            return_instance__is_active=True
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        remaining = inv_item.quantity - already_returned
        
        if remaining > 0:
            returnable_items.append({
                'invoice_item_id': inv_item.id,
                'item_id': inv_item.item.id,
                'item_name': inv_item.item.name,
                'sold_quantity': inv_item.quantity,
                'already_returned': already_returned,
                'remaining_returnable': remaining,
                'rate': inv_item.rate,
                'total': inv_item.total
            })
    
    return returnable_items


def validate_return_quantity(invoice_item: InvoiceItem, quantity: int) -> Tuple[bool, Optional[str]]:
    """
    Validate if quantity can be returned for an invoice item.
    
    Args:
        invoice_item: InvoiceItem instance
        quantity: Quantity to return
        
    Returns:
        Tuple of (is_valid: bool, error_message: Optional[str])
    """
    from .models import ReturnItem
    
    if quantity <= 0:
        return False, "Return quantity must be greater than zero"
    
    # Calculate already returned
    already_returned = ReturnItem.objects.filter(
        invoice_item=invoice_item,
        return_instance__is_active=True
    ).aggregate(total=Sum('quantity'))['total'] or 0
    
    max_returnable = invoice_item.quantity - already_returned
    
    if quantity > max_returnable:
        return False, (
            f"Cannot return {quantity} units. "
            f"Maximum returnable: {max_returnable} "
            f"(Sold: {invoice_item.quantity}, Already Returned: {already_returned})"
        )
    
    return True, None


# ================================================================
# REPORTING HELPER FUNCTIONS
# ================================================================

def get_invoice_summary_stats(start_date=None, end_date=None) -> Dict:
    """
    Get summary statistics for invoices.
    
    Args:
        start_date: Optional start date filter
        end_date: Optional end date filter
        
    Returns:
        Dict with count, total, paid, pending stats
    """
    queryset = Invoice.objects.filter(is_active=True)
    
    if start_date:
        queryset = queryset.filter(date__gte=start_date)
    
    if end_date:
        queryset = queryset.filter(date__lte=end_date)
    
    total_invoices = queryset.count()
    paid_invoices = queryset.filter(is_paid=True).count()
    pending_invoices = total_invoices - paid_invoices
    
    total_amount = sum(inv.total_amount for inv in queryset)
    total_paid = sum(inv.total_paid for inv in queryset)
    total_pending = total_amount - total_paid
    
    return {
        'total_invoices': total_invoices,
        'paid_invoices': paid_invoices,
        'pending_invoices': pending_invoices,
        'total_amount': total_amount,
        'total_paid': total_paid,
        'total_pending': max(total_pending, Decimal('0.00')),
        'collection_rate': (total_paid / total_amount * 100) if total_amount > 0 else 0
    }


def get_top_debtors(limit: int = 10) -> List[Dict]:
    """
    Get parties with highest outstanding balances.
    
    Args:
        limit: Number of results to return
        
    Returns:
        List of dicts with party info and outstanding amount
    """
    from party.models import Party
    
    debtors = []
    
    for party in Party.objects.filter(is_active=True):
        stats = calculate_party_outstanding(party)
        
        if stats['outstanding'] > Decimal('0.00'):
            debtors.append({
                'party_id': party.id,
                'party_name': party.name,
                'party_phone': party.phone,
                'outstanding': stats['outstanding'],
                'total_invoiced': stats['total_invoiced'],
                'total_paid': stats['total_paid']
            })
    
    # Sort by outstanding (descending)
    debtors.sort(key=lambda x: x['outstanding'], reverse=True)
    
    return debtors[:limit]


# ================================================================
# VALIDATION HELPERS
# ================================================================

def validate_invoice_amount(invoice: Invoice, raise_error: bool = False) -> bool:
    """
    Validate invoice amount matches sum of items.
    
    Args:
        invoice: Invoice instance
        raise_error: If True, raise ValidationError on mismatch
        
    Returns:
        bool: True if valid
        
    Raises:
        ValidationError: If raise_error=True and validation fails
    """
    calculated_total = invoice.invoice_items.filter(
        is_active=True
    ).aggregate(total=Sum('total'))['total'] or Decimal('0.00')
    
    if invoice.base_amount != calculated_total:
        error_msg = (
            f"Invoice {invoice.invoice_number} amount mismatch: "
            f"Stored: ₹{invoice.base_amount:.2f}, "
            f"Calculated: ₹{calculated_total:.2f}"
        )
        
        if raise_error:
            from django.core.exceptions import ValidationError
            raise ValidationError(error_msg)
        
        logger.warning(f"⚠️ {error_msg}")
        return False
    
    return True


# ================================================================
# FORMATTING HELPERS
# ================================================================

def format_currency(amount: Decimal, symbol: str = '₹') -> str:
    """Format decimal amount as currency string"""
    return f"{symbol}{amount:,.2f}"


def format_invoice_number(invoice: Invoice) -> str:
    """Format invoice number with status indicator"""
    status = "🟢" if invoice.is_paid else "🔴"
    return f"{status} {invoice.invoice_number}"


def format_payment_mode(mode: str) -> str:
    """Get emoji for payment mode"""
    mode_icons = {
        'cash': '💵',
        'upi': '📱',
        'bank': '🏦',
        'cheque': '📝'
    }
    return f"{mode_icons.get(mode, '💰')} {mode.upper()}"

