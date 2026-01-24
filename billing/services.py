"""
Billing Services Layer
======================
Centralized business logic for invoice, payment, return, and stock operations.

PRINCIPLES:
- Single source of truth for calculations
- Transaction-safe operations
- Explicit error handling
- No view logic here
"""

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple
from django.db import transaction, models
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Invoice, InvoiceItem, Payment, Return, ReturnItem
from items.models import Item
from party.models import Party
from core.inventory_manager import (
    check_stock_availability,
    deduct_items_for_invoice,
    add_items_for_return,
    update_items_for_invoice,
    restore_items_for_invoice_deletion
)

logger = logging.getLogger(__name__)


# ================================================================
# INVOICE SERVICES
# ================================================================

class InvoiceService:
    """Handles all invoice-related business logic"""
    
    @staticmethod
    def calculate_item_totals(
        quantity: int,
        rate: Decimal,
        gst_percent: Decimal,
        discount_amount: Decimal = Decimal('0.00')
    ) -> Dict[str, Decimal]:
        """
        Calculate line item totals with proper rounding.
        
        Args:
            quantity: Item quantity
            rate: Per-unit rate
            gst_percent: GST percentage (e.g., 18 for 18%)
            discount_amount: Flat discount amount
            
        Returns:
            dict with keys: base_amount, gst_amount, discount_amount, total
            
        Raises:
            ValidationError: If calculations fail
        """
        try:
            qty = Decimal(str(quantity))
            rate = Decimal(str(rate))
            gst_pct = Decimal(str(gst_percent))
            discount = Decimal(str(discount_amount))
            
            base = (qty * rate).quantize(Decimal('0.01'), ROUND_HALF_UP)
            gst = (base * gst_pct / Decimal('100')).quantize(Decimal('0.01'), ROUND_HALF_UP)
            total = (base + gst - discount).quantize(Decimal('0.01'), ROUND_HALF_UP)
            
            return {
                'base_amount': base,
                'gst_amount': gst,
                'discount_amount': discount,
                'total': total
            }
        except Exception as e:
            logger.error(f"❌ Item calculation failed: {e}")
            raise ValidationError(f"Invalid calculation parameters: {e}")
    
    @staticmethod
    def validate_stock_availability(items: List[Dict]) -> Tuple[bool, List[str]]:
        """
        Check if sufficient stock exists for invoice items.
        
        Args:
            items: List of {'item_id': int, 'quantity': int}
            
        Returns:
            (success: bool, errors: List[str])
        """
        if not items:
            return True, []
        
        result = check_stock_availability(items)
        
        if not result['available']:
            errors = []
            for item in result.get('unavailable_items', []):
                errors.append(
                    f"{item['name']} - Available: {item['available']}, "
                    f"Requested: {item['requested']}"
                )
            return False, errors
        
        return True, []
    
    @staticmethod
    @transaction.atomic
    def create_invoice_with_items(
        invoice_data: Dict,
        items_data: List[Dict],
        user
    ) -> Invoice:
        """
        Create invoice with items and deduct stock atomically.
        
        Args:
            invoice_data: Invoice fields (party, date, etc.)
            items_data: List of item dicts with quantity, rate, etc.
            user: User creating the invoice
            
        Returns:
            Created Invoice instance
            
        Raises:
            ValidationError: If validation fails
            Exception: If stock deduction fails
        """
        # Step 1: Create invoice
        invoice = Invoice.objects.create(
            **invoice_data,
            created_by=user,
            updated_by=user
        )
        
        logger.info(f"✅ Invoice created: {invoice.invoice_number}")
        
        # Step 2: Create invoice items and calculate total
        total_amount = Decimal('0.00')
        items_for_inventory = []
        
        for item_data in items_data:
            item_obj = item_data['item']
            
            # Calculate totals
            gst_percent = item_obj.gst_percent or Decimal('0.00')
            calculated = InvoiceService.calculate_item_totals(
                quantity=item_data['quantity'],
                rate=item_data['rate'],
                gst_percent=gst_percent,
                discount_amount=item_data.get('discount_amount', Decimal('0.00'))
            )
            
            # Create invoice item
            inv_item = InvoiceItem.objects.create(
                invoice=invoice,
                item=item_obj,
                quantity=item_data['quantity'],
                rate=item_data['rate'],
                gst_amount=calculated['gst_amount'],
                discount_amount=calculated['discount_amount'],
                total=calculated['total'],
                created_by=user,
                updated_by=user
            )
            
            total_amount += calculated['total']
            
            # Track for inventory deduction
            if item_obj:
                items_for_inventory.append({
                    'item_id': item_obj.id,
                    'quantity': int(item_data['quantity'])
                })
        
        # Step 3: Update invoice total
        invoice.base_amount = total_amount
        invoice.save(update_fields=['base_amount'])
        
        # Step 4: Deduct stock
        if items_for_inventory:
            stock_result = deduct_items_for_invoice(
                invoice_items=items_for_inventory,
                invoice_type='wholesale',
                invoice_id=invoice.id,
                created_by=user
            )
            
            if not stock_result['success']:
                raise Exception(
                    f"Stock deduction failed: {', '.join(stock_result['errors'])}"
                )
            
            logger.info(
                f"✅ Stock deducted for {len(stock_result['items_processed'])} items"
            )
        
        return invoice
    
    @staticmethod
    @transaction.atomic
    def update_invoice_items(
        invoice: Invoice,
        original_items: List[Dict],
        updated_items: List[Dict],
        user
    ) -> bool:
        """
        Update invoice items and adjust stock accordingly.
        
        Args:
            invoice: Invoice instance
            original_items: List of {'item_id': int, 'quantity': int} before update
            updated_items: List of {'item_id': int, 'quantity': int} after update
            user: User making the update
            
        Returns:
            bool: Success status
            
        Raises:
            Exception: If stock adjustment fails
        """
        if not (original_items or updated_items):
            return True
        
        stock_result = update_items_for_invoice(
            original_items=original_items,
            updated_items=updated_items,
            invoice_type='wholesale',
            invoice_id=invoice.id,
            created_by=user
        )
        
        if not stock_result['success']:
            raise Exception(
                f"Stock adjustment failed: {', '.join(stock_result['errors'])}"
            )
        
        logger.info(f"✅ Stock adjusted for invoice {invoice.invoice_number}")
        return True
    
    @staticmethod
    def check_and_close_invoice(invoice: Invoice) -> bool:
        """
        Check if invoice should be marked as paid and update status.
        
        Args:
            invoice: Invoice instance
            
        Returns:
            bool: True if invoice was closed, False otherwise
        """
        try:
            total_amount = invoice.total_amount or Decimal('0.00')
            total_paid = invoice.total_paid or Decimal('0.00')
            
            balance = total_amount - total_paid
            
            if balance <= Decimal('0.00') and not invoice.is_paid:
                invoice.is_paid = True
                invoice.save(update_fields=['is_paid'])
                logger.info(f"✅ Invoice {invoice.invoice_number} auto-closed")
                return True
            
            return False
        except Exception as e:
            logger.error(f"❌ Error checking invoice closure: {e}")
            return False


# ================================================================
# RETURN SERVICES
# ================================================================

class ReturnService:
    """Handles all return-related business logic"""
    
    @staticmethod
    def calculate_returnable_quantity(invoice_item: InvoiceItem) -> int:
        """
        Calculate remaining returnable quantity for an invoice item.
        
        Args:
            invoice_item: InvoiceItem instance
            
        Returns:
            int: Remaining returnable quantity
        """
        already_returned = ReturnItem.objects.filter(
            invoice_item=invoice_item,
            return_instance__is_active=True
        ).aggregate(total=models.Sum('quantity'))['total'] or 0
        
        return invoice_item.quantity - already_returned
    
    @staticmethod
    def calculate_return_amount(
        invoice_item: InvoiceItem,
        return_quantity: int
    ) -> Decimal:
        """
        Calculate return amount for given quantity.
        
        Args:
            invoice_item: InvoiceItem instance
            return_quantity: Quantity being returned
            
        Returns:
            Decimal: Calculated return amount
            
        Raises:
            ValidationError: If calculation fails
        """
        if return_quantity <= 0:
            raise ValidationError("Return quantity must be greater than zero")
        
        max_returnable = ReturnService.calculate_returnable_quantity(invoice_item)
        
        if return_quantity > max_returnable:
            raise ValidationError(
                f"Cannot return {return_quantity} units. "
                f"Maximum returnable: {max_returnable}"
            )
        
        # Calculate per-unit price
        if invoice_item.total and invoice_item.quantity > 0:
            per_unit_price = (
                invoice_item.total / invoice_item.quantity
            ).quantize(Decimal('0.01'), ROUND_HALF_UP)
        else:
            per_unit_price = Decimal('0.00')
        
        return (per_unit_price * return_quantity).quantize(
            Decimal('0.01'), ROUND_HALF_UP
        )
    
    @staticmethod
    @transaction.atomic
    def create_return_with_items(
        invoice: Invoice,
        return_items_data: List[Dict],
        return_date,
        reason: str,
        image,
        user
    ) -> Return:
        """
        Create return with items and restore stock atomically.
        
        Args:
            invoice: Invoice being returned against
            return_items_data: List of {'invoice_item': obj, 'quantity': int, 'amount': Decimal}
            return_date: Date of return
            reason: Return reason
            image: Optional image
            user: User creating the return
            
        Returns:
            Created Return instance
            
        Raises:
            ValidationError: If validation fails
            Exception: If stock restoration fails
        """
        # Step 1: Calculate total return amount
        total_amount = sum(item['amount'] for item in return_items_data)
        
        # Step 2: Validate against invoice
        existing_returns = Return.objects.filter(
            invoice=invoice,
            is_active=True
        ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
        
        max_returnable = invoice.base_amount - existing_returns
        
        if total_amount > max_returnable:
            raise ValidationError(
                f"Return amount ₹{total_amount} exceeds maximum "
                f"returnable ₹{max_returnable:.2f}"
            )
        
        # Step 3: Create Return record
        return_obj = Return.objects.create(
            invoice=invoice,
            party=invoice.party,
            return_date=return_date,
            amount=total_amount,
            reason=reason,
            image=image,
            created_by=user,
            updated_by=user
        )
        
        logger.info(f"✅ Return created: {return_obj.return_number}")
        
        # Step 4: Create ReturnItem records
        items_for_inventory = []
        
        for item_data in return_items_data:
            return_item = ReturnItem.objects.create(
                return_instance=return_obj,
                invoice_item=item_data['invoice_item'],
                quantity=item_data['quantity'],
                amount=item_data['amount'],
                created_by=user,
                updated_by=user
            )
            
            # Track for stock restoration
            if item_data['invoice_item'].item:
                items_for_inventory.append({
                    'item_id': item_data['invoice_item'].item.id,
                    'quantity': int(item_data['quantity'])
                })
        
        # Step 5: Restore stock
        if items_for_inventory:
            stock_result = add_items_for_return(
                return_items=items_for_inventory,
                invoice_type='wholesale',
                invoice_id=invoice.id,
                return_id=return_obj.id,
                created_by=user
            )
            
            if not stock_result['success']:
                raise Exception(
                    f"Stock restoration failed: {', '.join(stock_result['errors'])}"
                )
            
            logger.info(
                f"✅ Stock restored for {len(stock_result['items_processed'])} items"
            )
        
        # Step 6: Check if invoice should be closed
        InvoiceService.check_and_close_invoice(invoice)
        
        return return_obj


# ================================================================
# PAYMENT SERVICES
# ================================================================

class PaymentService:
    """Handles all payment-related business logic"""
    
    @staticmethod
    @transaction.atomic
    def create_payment(
        party: Party,
        amount: Decimal,
        date,
        mode: str,
        invoice: Optional[Invoice],
        notes: str,
        user
    ) -> Payment:
        """
        Create payment and update invoice status.
        
        Args:
            party: Party making payment
            amount: Payment amount
            date: Payment date
            mode: Payment mode
            invoice: Optional invoice to link
            notes: Payment notes
            user: User creating payment
            
        Returns:
            Created Payment instance
            
        Raises:
            ValidationError: If validation fails
        """
        # Validate amount
        if amount <= Decimal('0.00'):
            raise ValidationError("Payment amount must be greater than zero")
        
        # Validate against invoice if linked
        if invoice:
            balance = invoice.balance_due or Decimal('0.00')
            
            if amount > balance:
                raise ValidationError(
                    f"Payment ₹{amount} exceeds balance due ₹{balance:.2f}"
                )
        
        # Create payment
        payment = Payment.objects.create(
            party=party,
            invoice=invoice,
            date=date,
            amount=amount,
            mode=mode,
            notes=notes,
            created_by=user,
            updated_by=user
        )
        
        logger.info(f"✅ Payment created: {payment.payment_number}")
        
        # Update invoice status if linked
        if invoice:
            InvoiceService.check_and_close_invoice(invoice)
        
        return payment