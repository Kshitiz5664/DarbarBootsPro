import logging
from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Invoice, InvoiceItem, Payment
from party.models import Party

logger = logging.getLogger(__name__)


def recalc_invoice_payment_status(invoice):
    """Recalculate invoice payment status based on items and payments."""
    if not invoice:
        return
    invoice.is_paid = invoice.total_paid >= invoice.total_amount
    invoice.save(update_fields=['is_paid', 'updated_at'])
    logger.info(f"Invoice {invoice.invoice_number} payment status updated: is_paid={invoice.is_paid}")


def recalc_party_balance(party):
    """Recalculate party's total pending balance."""
    if not party:
        return
    total_invoiced = sum(inv.total_amount for inv in party.invoices.all())
    total_paid = sum(pay.amount for pay in party.payments.all())
    party.total_pending = total_invoiced - total_paid
    party.save(update_fields=['total_pending', 'updated_at'])
    logger.info(f"Party {party.name} balance updated: invoiced={total_invoiced}, paid={total_paid}, pending={party.total_pending}")


# -----------------------
# INVOICE ITEM SIGNALS
# -----------------------
@receiver([post_save, post_delete], sender=InvoiceItem)
def invoice_item_changed(sender, instance, **kwargs):
    invoice = instance.invoice
    if not invoice:
        return
    try:
        with transaction.atomic():
            # Update invoice base_amount
            invoice.recalculate_base_amount()
            # Update invoice payment status
            recalc_invoice_payment_status(invoice)
            # Update party balance
            recalc_party_balance(invoice.party)
    except Exception as e:
        logger.error(f"Transaction failed for InvoiceItem change (invoice {invoice.id}): {e}")


# -----------------------
# PAYMENT SIGNALS
# -----------------------
@receiver([post_save, post_delete], sender=Payment)
def payment_changed(sender, instance, **kwargs):
    invoice = getattr(instance, 'invoice', None)
    party = getattr(instance, 'party', None)
    try:
        with transaction.atomic():
            recalc_invoice_payment_status(invoice)
            recalc_party_balance(party)
    except Exception as e:
        logger.error(f"Transaction failed for Payment change (id={instance.id}): {e}")


# -----------------------
# INVOICE SIGNALS
# -----------------------
@receiver([post_save, post_delete], sender=Invoice)
def invoice_changed(sender, instance, **kwargs):
    party = getattr(instance, 'party', None)
    try:
        with transaction.atomic():
            recalc_party_balance(party)
    except Exception as e:
        logger.error(f"Transaction failed for Invoice change (id={instance.id}): {e}")
