# signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from billing.models import Payment
from .utils import send_payment_receipt
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Payment)
def send_payment_receipt_signal(sender, instance, created, **kwargs):
    """
    Automatically send WhatsApp payment receipt when a new payment is recorded.
    """
    if created:
        try:
            success = send_payment_receipt(instance.party, instance)
            if success:
                logger.info(f"Payment receipt sent automatically for Payment ID: {instance.id}")
            else:
                logger.warning(f"Failed to send WhatsApp receipt for Payment ID: {instance.id}")
        except Exception as e:
            logger.error(f"Error in sending payment receipt signal: {e}")
