# billing/signals.py
"""
Billing Signals
===============
Automatic calculations and side-effects for billing operations.

SIGNAL FLOW:
1. InvoiceItem save/delete → Recalculate Invoice totals
2. Payment save/delete → Update Invoice payment status + Party balance
3. Return save/delete → Update Invoice totals + Touch timestamp
4. Invoice save/delete → Update Party balance
"""

import logging
from django.db import models 
from decimal import Decimal
from django.db import transaction
from django.db.models.signals import post_save, post_delete, pre_save, pre_delete
from django.dispatch import receiver
from django.core.exceptions import ValidationError

from .models import Invoice, InvoiceItem, Payment, Return, ReturnItem

logger = logging.getLogger(__name__)


# ================================================================
# HELPER FUNCTIONS
# ================================================================

def safe_decimal(value):
    """Safely convert value to Decimal, handling None"""
    if value is None:
        return Decimal('0.00')
    return Decimal(str(value))


def recalculate_invoice_totals(invoice):
    """
    Recalculate invoice base_amount and payment status.
    
    Args:
        invoice: Invoice instance
    """
    if not invoice or not invoice.pk:
        return
    
    try:
        with transaction.atomic():
            # Recalculate base amount from items
            invoice.recalculate_base_amount()
            
            # Update payment status
            total_amount = invoice.total_amount or Decimal('0.00')
            total_paid = invoice.total_paid or Decimal('0.00')
            
            # Auto-close if fully paid
            if total_paid >= total_amount and total_amount > 0:
                if not invoice.is_paid:
                    invoice.is_paid = True
                    invoice.save(update_fields=['is_paid'])
                    logger.info(f"✅ Invoice {invoice.invoice_number} auto-closed (fully paid)")
            elif invoice.is_paid and total_paid < total_amount:
                # Reopen if balance due exists (e.g., after return)
                invoice.is_paid = False
                invoice.save(update_fields=['is_paid'])
                logger.info(f"🔄 Invoice {invoice.invoice_number} reopened (balance due: ₹{total_amount - total_paid:.2f})")
                
    except Exception as e:
        logger.error(f"❌ Error recalculating invoice {invoice.id}: {e}", exc_info=True)


def update_party_balance(party):
    """
    Recalculate party's total outstanding balance.
    
    Args:
        party: Party instance
    """
    if not party or not party.pk:
        return
    
    try:
        from party.models import Party  # Import here to avoid circular imports
        
        # Calculate total invoiced
        total_invoiced = sum(
            inv.total_amount for inv in party.invoices.filter(is_active=True)
        )
        
        # Calculate total paid
        total_paid = sum(
            pay.amount for pay in party.payments.filter(is_active=True)
        )
        
        # Update party balance if field exists
        if hasattr(party, 'total_pending'):
            old_balance = party.total_pending or Decimal('0.00')
            new_balance = total_invoiced - total_paid
            
            if old_balance != new_balance:
                party.total_pending = new_balance
                party.save(update_fields=['total_pending', 'updated_at'])
                logger.info(
                    f"💰 Party {party.name} balance updated: "
                    f"₹{old_balance:.2f} → ₹{new_balance:.2f}"
                )
                
    except Exception as e:
        logger.error(f"❌ Error updating party balance for {party.id}: {e}", exc_info=True)


# ================================================================
# INVOICE ITEM SIGNALS
# ================================================================

@receiver([post_save, post_delete], sender=InvoiceItem)
def handle_invoice_item_change(sender, instance, **kwargs):
    """
    Recalculate invoice totals when items are added/updated/deleted.
    
    Triggers:
    - InvoiceItem created
    - InvoiceItem updated
    - InvoiceItem deleted (soft or hard)
    """
    invoice = instance.invoice
    
    if not invoice:
        logger.warning(f"⚠️ InvoiceItem {instance.id} has no invoice")
        return
    
    signal_type = "deleted" if kwargs.get('signal') == post_delete else "changed"
    logger.info(f"📝 InvoiceItem {signal_type} for Invoice {invoice.invoice_number}")
    
    # Recalculate invoice totals
    recalculate_invoice_totals(invoice)
    
    # Update party balance
    if invoice.party:
        update_party_balance(invoice.party)


# ================================================================
# PAYMENT SIGNALS
# ================================================================

@receiver([post_save, post_delete], sender=Payment)
def handle_payment_change(sender, instance, **kwargs):
    """
    Update invoice and party when payment is added/updated/deleted.
    
    Triggers:
    - Payment created
    - Payment updated
    - Payment deleted (soft or hard)
    """
    invoice = instance.invoice
    party = instance.party
    
    signal_type = "deleted" if kwargs.get('signal') == post_delete else "saved"
    logger.info(
        f"💳 Payment {instance.payment_number or instance.id} {signal_type} "
        f"(Amount: ₹{instance.amount:.2f})"
    )
    
    # Update invoice if linked
    if invoice:
        recalculate_invoice_totals(invoice)
    
    # Update party balance
    if party:
        update_party_balance(party)


# ================================================================
# RETURN SIGNALS
# ================================================================

@receiver(pre_save, sender=Return)
def validate_return_before_save(sender, instance, **kwargs):
    """
    Validate return amount doesn't exceed invoice balance.
    Only runs on creation (not updates).
    """
    # Skip validation on updates (when pk exists)
    if instance.pk:
        return
    
    invoice = instance.invoice
    
    if not invoice:
        logger.error("❌ Return created without invoice")
        raise ValidationError("Return must be linked to an invoice")
    
    # Calculate existing returns
    existing_returns_total = Return.objects.filter(
        invoice=invoice,
        is_active=True
    ).exclude(pk=instance.pk).aggregate(
        total=models.Sum('amount')
    )['total'] or Decimal('0.00')
    
    # Check if new return exceeds allowable
    max_returnable = invoice.base_amount - existing_returns_total
    
    if instance.amount > max_returnable:
        error_msg = (
            f"Return amount ₹{instance.amount:.2f} exceeds maximum returnable "
            f"₹{max_returnable:.2f} (Invoice: ₹{invoice.base_amount:.2f}, "
            f"Already Returned: ₹{existing_returns_total:.2f})"
        )
        logger.error(f"❌ {error_msg}")
        raise ValidationError({'amount': error_msg})
    
    logger.info(f"✅ Return validation passed for Invoice {invoice.invoice_number}")


@receiver([post_save, post_delete], sender=Return)
def handle_return_change(sender, instance, **kwargs):
    """
    Update invoice when return is added/updated/deleted.
    
    Triggers:
    - Return created
    - Return updated
    - Return deleted (soft or hard)
    """
    invoice = instance.invoice
    
    if not invoice:
        logger.warning(f"⚠️ Return {instance.return_number} has no invoice")
        return
    
    signal_type = "deleted" if kwargs.get('signal') == post_delete else "saved"
    logger.info(
        f"🔄 Return {instance.return_number or instance.id} {signal_type} "
        f"(Amount: ₹{instance.amount:.2f})"
    )
    
    # Touch invoice timestamp
    from django.utils import timezone
    invoice.updated_at = timezone.now()
    invoice.save(update_fields=['updated_at'])
    
    # Recalculate invoice totals
    recalculate_invoice_totals(invoice)
    
    # Update party balance
    if invoice.party:
        update_party_balance(invoice.party)


@receiver([post_save, post_delete], sender=ReturnItem)
def handle_return_item_change(sender, instance, **kwargs):
    """
    Touch return timestamp when return items change.
    Useful for audit trails.
    """
    return_instance = instance.return_instance
    
    if not return_instance:
        return
    
    signal_type = "deleted" if kwargs.get('signal') == post_delete else "saved"
    logger.info(
        f"📦 ReturnItem {signal_type} for Return {return_instance.return_number} "
        f"(Qty: {instance.quantity})"
    )
    
    # Touch return timestamp
    from django.utils import timezone
    return_instance.updated_at = timezone.now()
    return_instance.save(update_fields=['updated_at'])


# ================================================================
# INVOICE SIGNALS
# ================================================================

@receiver([post_save, post_delete], sender=Invoice)
def handle_invoice_change(sender, instance, **kwargs):
    """
    Update party balance when invoice is added/updated/deleted.
    
    Triggers:
    - Invoice created
    - Invoice updated
    - Invoice deleted (soft or hard)
    """
    party = instance.party
    
    if not party:
        logger.warning(f"⚠️ Invoice {instance.invoice_number} has no party")
        return
    
    signal_type = "deleted" if kwargs.get('signal') == post_delete else "saved"
    logger.info(f"📋 Invoice {instance.invoice_number} {signal_type}")
    
    # Update party balance
    update_party_balance(party)


# ================================================================
# SIGNAL LOGGING (for debugging)
# ================================================================

@receiver(pre_save, sender=Invoice)
def log_invoice_changes(sender, instance, **kwargs):
    """Log invoice changes for audit trail"""
    if instance.pk:  # Only on updates
        try:
            old = Invoice.objects.get(pk=instance.pk)
            changes = []
            
            if old.is_paid != instance.is_paid:
                changes.append(f"is_paid: {old.is_paid} → {instance.is_paid}")
            
            if old.base_amount != instance.base_amount:
                changes.append(f"base_amount: ₹{old.base_amount:.2f} → ₹{instance.base_amount:.2f}")
            
            if changes:
                logger.info(f"📝 Invoice {instance.invoice_number} changes: {', '.join(changes)}")
                
        except Invoice.DoesNotExist:
            pass

