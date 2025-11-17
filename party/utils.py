# utils.py
import logging
import asyncio
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_WHATSAPP_NUMBER = getattr(settings, 'TWILIO_WHATSAPP_NUMBER', 'whatsapp:+14155238886')


def normalize_phone(phone: str) -> str:
    """Normalize phone number to E.164 format with WhatsApp prefix"""
    if not phone:
        return None
    phone_digits = ''.join(filter(str.isdigit, phone))
    if len(phone_digits) < 10:
        return None
    if not phone_digits.startswith('91') and len(phone_digits) == 10:
        phone_digits = f'91{phone_digits}'
    return f'whatsapp:+{phone_digits}'


async def _send_whatsapp_async(to_number: str, message: str):
    """Send WhatsApp message asynchronously via Twilio"""
    try:
        from twilio.rest import Client
        account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', None)
        auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', None)

        if not account_sid or not auth_token:
            logger.warning("Twilio not configured. Dev mode - message not sent.")
            print(f"[DEV MODE] Message to {to_number}:\n{message}")
            return True

        client = Client(account_sid, auth_token)
        response = client.messages.create(
            body=message,
            from_=DEFAULT_WHATSAPP_NUMBER,
            to=to_number
        )
        logger.info(f"WhatsApp message sent to {to_number}: {response.sid}")
        return True
    except ImportError:
        logger.warning("Twilio library not installed. Install with: pip install twilio")
        print(f"[DEV MODE] Message to {to_number}:\n{message}")
        return True
    except Exception as e:
        logger.error(f"Error sending WhatsApp message to {to_number}: {e}")
        return False


def send_whatsapp_reminder(party):
    """Send pending balance reminder to a party"""
    to_number = normalize_phone(party.phone)
    if not to_number:
        logger.warning(f"No valid phone for party {party.name}")
        return False

    pending = getattr(party, 'pending_amount', 0)
    if pending <= 0:
        logger.info(f"No pending balance for {party.name}")
        return False

    message = (
        f"Hello {party.name},\n\n"
        f"This is a friendly reminder from {getattr(settings, 'COMPANY_NAME', 'our shop')}.\n"
        f"Your pending balance is ₹{pending:.2f}.\n"
        f"Please clear your dues at your earliest convenience.\n\nThank you!"
    )

    # Run async send
    return asyncio.run(_send_whatsapp_async(to_number, message))


def send_payment_receipt(party, payment):
    """Send payment receipt to a party"""
    to_number = normalize_phone(party.phone)
    if not to_number:
        logger.warning(f"No valid phone for party {party.name}")
        return False

    message = (
        f"Hello {party.name},\n\n"
        f"Thank you for your payment!\n\n"
        f"Amount: ₹{payment.amount:.2f}\n"
        f"Date: {payment.date.strftime('%d-%m-%Y')}\n"
        f"Mode: {payment.get_mode_display()}\n"
    )

    if getattr(payment, 'invoice', None):
        message += f"Invoice: {payment.invoice.invoice_number}\n"

    remaining = getattr(party, 'pending_amount', 0)
    message += f"\nRemaining Balance: ₹{remaining:.2f}\n"
    message += f"\nThank you for your business!\n{getattr(settings, 'COMPANY_NAME', 'Our Shop')}"

    return asyncio.run(_send_whatsapp_async(to_number, message))
