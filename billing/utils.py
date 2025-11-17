import logging
import requests
from django.conf import settings
from django.core.mail import send_mail
from party.models import Party
from .models import Payment

logger = logging.getLogger(__name__)


def send_payment_receipt(party: Party, payment: Payment):
    """
    Send a payment receipt to the party via WhatsApp or Email.

    Args:
        party (Party): The party who made the payment.
        payment (Payment): The payment instance.

    Raises:
        Exception: If sending fails.
    """
    if not party:
        logger.warning("No party provided for receipt.")
        return

    if not payment:
        logger.warning("No payment provided for receipt.")
        return

    message = generate_payment_message(party, payment)

    # 1️⃣ WhatsApp via API (example)
    if party.phone and getattr(settings, 'WHATSAPP_API_URL', None):
        try:
            payload = {
                'phone': party.phone,
                'message': message
            }
            response = requests.post(settings.WHATSAPP_API_URL, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info(f"WhatsApp receipt sent to {party.name} ({party.phone}) for payment ₹{payment.amount}")
            else:
                logger.warning(f"WhatsApp API response {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Failed to send WhatsApp receipt to {party.name}: {e}")

    # 2️⃣ Email as fallback
    if party.email:
        try:
            send_mail(
                subject=f'Payment Receipt - Invoice {payment.invoice.invoice_number}',
                message=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
                recipient_list=[party.email],
                fail_silently=False
            )
            logger.info(f"Email receipt sent to {party.email} for payment ₹{payment.amount}")
        except Exception as e:
            logger.error(f"Failed to send email receipt to {party.email}: {e}")


def generate_payment_message(party: Party, payment: Payment) -> str:
    """
    Generate a detailed payment receipt message.

    Args:
        party (Party): The party who made the payment.
        payment (Payment): Payment instance.

    Returns:
        str: Formatted receipt message.
    """
    invoice_number = payment.invoice.invoice_number if payment.invoice else 'N/A'
    total_paid = payment.invoice.total_paid if payment.invoice else payment.amount
    balance_due = payment.invoice.balance_due if payment.invoice else 0

    message = (
        f"Hello {party.name},\n\n"
        f"We have received your payment of ₹{payment.amount}.\n"
        f"Invoice Number: {invoice_number}\n"
        f"Total Paid So Far: ₹{total_paid}\n"
        f"Remaining Balance: ₹{balance_due}\n\n"
        "Thank you for your payment.\n"
        "Regards,\n"
        "Your Company Name"
    )
    return message


from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from decimal import Decimal
from .models import Invoice


def get_invoice_queryset_with_total():
    """
    Returns Invoice queryset annotated with computed total_amount =
    base_amount - total_return_sum (handles null/zero gracefully).
    """
    return (
        Invoice.objects.annotate(
            total_return_sum=Sum('returns__amount', default=Decimal('0.00'))
        )
        .annotate(
            total_amount=ExpressionWrapper(
                F('base_amount') - F('total_return_sum'),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
    )
