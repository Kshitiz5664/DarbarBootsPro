"""
Centralized Inventory Management System - PART 1 OF 3
D:\Clients Projects\Darbar_Boot_house\DarbarBootsPro\core\inventory_manager.py

✅ COMPLETE AND ERROR-FREE VERSION
Copy all 3 parts into one file: inventory_manager.py

Features:
- Thread-safe stock operations using select_for_update()
- Automatic stock movement logging
- Support for retail and wholesale invoices
- Handle returns and restocks
- Invoice update support with differential calculations
- Comprehensive error handling
"""

from django.db import transaction
from django.core.exceptions import ValidationError
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class InventoryManager:
    """
    Centralized manager for handling inventory operations.
    Thread-safe for concurrent users.
    """
    
    @staticmethod
    def deduct_stock_for_invoice(invoice_items, invoice_type='retail', invoice_id=None, created_by=None):
        """
        ✅ Deduct stock when creating retail/wholesale invoice.
        
        Args:
            invoice_items: List of dicts [{'item_id': int, 'quantity': int}, ...]
            invoice_type: str - 'retail' or 'wholesale'
            invoice_id: int - ID of the invoice
            created_by: User object - User creating the invoice
        
        Returns:
            dict: {
                'success': bool,
                'items_processed': list of item names,
                'errors': list of error messages,
                'message': str
            }
        """
        from items.models import Item, StockMovement
        
        if not invoice_items:
            return {
                'success': False,
                'items_processed': [],
                'errors': ['No items provided'],
                'message': 'No items to process'
            }
        
        errors = []
        items_processed = []
        
        try:
            with transaction.atomic():
                # PHASE 1: Validate all items BEFORE making changes
                items_to_process = []
                
                for item_data in invoice_items:
                    item_id = item_data.get('item_id')
                    quantity = item_data.get('quantity', 0)
                    
                    if not item_id:
                        errors.append("Missing item_id in invoice item data")
                        continue
                    
                    if quantity <= 0:
                        errors.append(f"Invalid quantity ({quantity}) for item ID {item_id}")
                        continue
                    
                    try:
                        # Lock row for thread-safe update
                        item = Item.objects.select_for_update().get(
                            id=item_id,
                            is_deleted=False
                        )
                        
                        # Check if item is active
                        if not item.is_active:
                            errors.append(
                                f"{item.name} (HSN: {item.hns_code}) is not active"
                            )
                            continue
                        
                        # Check stock availability
                        if item.quantity < quantity:
                            errors.append(
                                f"Insufficient stock for {item.name} (HSN: {item.hns_code}). "
                                f"Available: {item.quantity}, Requested: {quantity}"
                            )
                            continue
                        
                        # Add to processing queue
                        items_to_process.append({
                            'item': item,
                            'quantity': quantity
                        })
                        
                    except Item.DoesNotExist:
                        errors.append(f"Item with ID {item_id} not found or deleted")
                        continue
                
                # If validation errors, stop here
                if errors:
                    raise ValidationError(errors)
                
                # PHASE 2: Perform actual deductions (all validations passed)
                for process_data in items_to_process:
                    item = process_data['item']
                    quantity = process_data['quantity']
                    
                    try:
                        # Deduct stock
                        item.quantity -= quantity
                        item.save(update_fields=['quantity', 'updated_at'])
                        
                        # Log stock movement
                        StockMovement.objects.create(
                            item=item,
                            quantity=-quantity,
                            movement_type=f'{invoice_type}_sale',
                            invoice_id=invoice_id,
                            invoice_type=invoice_type,
                            created_by=created_by,
                            notes=f"Stock deducted for {invoice_type} invoice #{invoice_id}"
                        )
                        
                        items_processed.append(item.name)
                        
                        logger.info(
                            f"✅ Stock deducted: {item.name} (HSN: {item.hns_code}) - "
                            f"Quantity: {quantity}, New Stock: {item.quantity}, "
                            f"Invoice: {invoice_type} #{invoice_id}"
                        )
                        
                    except Exception as e:
                        errors.append(f"Error processing {item.name}: {str(e)}")
                        logger.error(f"Error processing item {item.id}: {e}", exc_info=True)
                        raise  # Trigger rollback
                
        except ValidationError:
            return {
                'success': False,
                'items_processed': [],
                'errors': errors,
                'message': 'Stock deduction failed. Transaction rolled back.'
            }
        except Exception as e:
            logger.error(f"Unexpected error in deduct_stock_for_invoice: {e}", exc_info=True)
            return {
                'success': False,
                'items_processed': [],
                'errors': [str(e)],
                'message': 'An unexpected error occurred'
            }
        
        return {
            'success': True,
            'items_processed': items_processed,
            'errors': [],
            'message': f'Successfully deducted stock for {len(items_processed)} item(s)'
        }
    
    @staticmethod
    def add_stock_for_return(return_items, invoice_type='retail', invoice_id=None, return_id=None, created_by=None):
        """
        ✅ Add stock back when processing returns.
        
        Args:
            return_items: List of dicts [{'item_id': int, 'quantity': int}, ...]
            invoice_type: str - 'retail' or 'wholesale'
            invoice_id: int - ID of the original invoice
            return_id: int - ID of the return record
            created_by: User object - User processing the return
        
        Returns:
            dict: {
                'success': bool,
                'items_processed': list of item names,
                'errors': list of error messages,
                'message': str
            }
        """
        from items.models import Item, StockMovement
        
        if not return_items:
            return {
                'success': False,
                'items_processed': [],
                'errors': ['No items provided for return'],
                'message': 'No items to process'
            }
        
        errors = []
        items_processed = []
        
        try:
            with transaction.atomic():
                # PHASE 1: Validate all items
                items_to_process = []
                
                for item_data in return_items:
                    item_id = item_data.get('item_id')
                    quantity = item_data.get('quantity', 0)
                    
                    if not item_id:
                        errors.append("Missing item_id in return item data")
                        continue
                    
                    if quantity <= 0:
                        errors.append(f"Invalid quantity ({quantity}) for item ID {item_id}")
                        continue
                    
                    try:
                        # Lock row for update
                        item = Item.objects.select_for_update().get(
                            id=item_id,
                            is_deleted=False
                        )
                        
                        items_to_process.append({
                            'item': item,
                            'quantity': quantity
                        })
                        
                    except Item.DoesNotExist:
                        errors.append(f"Item with ID {item_id} not found or deleted")
                        continue
                
                # If validation errors, stop
                if errors:
                    raise ValidationError(errors)
                
                # PHASE 2: Perform actual stock additions
                for process_data in items_to_process:
                    item = process_data['item']
                    quantity = process_data['quantity']
                    
                    try:
                        # Add stock back
                        item.quantity += quantity
                        item.save(update_fields=['quantity', 'updated_at'])
                        
                        # Log stock movement
                        StockMovement.objects.create(
                            item=item,
                            quantity=quantity,
                            movement_type='return',
                            invoice_id=invoice_id,
                            invoice_type=invoice_type,
                            created_by=created_by,
                            notes=f"Stock returned from {invoice_type} invoice #{invoice_id} (Return #{return_id})"
                        )
                        
                        items_processed.append(item.name)
                        
                        logger.info(
                            f"✅ Stock returned: {item.name} (HSN: {item.hns_code}) - "
                            f"Quantity: {quantity}, New Stock: {item.quantity}, "
                            f"Return: {invoice_type} #{return_id}"
                        )
                        
                    except Exception as e:
                        errors.append(f"Error processing {item.name}: {str(e)}")
                        logger.error(f"Error processing return for item {item.id}: {e}", exc_info=True)
                        raise  # Trigger rollback
                
        except ValidationError:
            return {
                'success': False,
                'items_processed': [],
                'errors': errors,
                'message': 'Stock return failed. Transaction rolled back.'
            }
        except Exception as e:
            logger.error(f"Unexpected error in add_stock_for_return: {e}", exc_info=True)
            return {
                'success': False,
                'items_processed': [],
                'errors': [str(e)],
                'message': 'An unexpected error occurred'
            }
        
        return {
            'success': True,
            'items_processed': items_processed,
            'errors': [],
            'message': f'Successfully returned stock for {len(items_processed)} item(s)'
        }
# PART 2 OF 3 - APPEND THIS AFTER PART 1
# Continue the InventoryManager class methods

    @staticmethod
    def update_stock_for_invoice_update(original_items, updated_items, invoice_type='retail', invoice_id=None, created_by=None):
        """
        ✅ Handle stock adjustments when invoice is updated.
        
        Automatically calculates differences:
        - Item removed: add stock back
        - Item added: deduct stock
        - Quantity decreased: add difference back
        - Quantity increased: deduct difference
        
        Args:
            original_items: List [{'item_id': int, 'quantity': int}, ...]
            updated_items: List [{'item_id': int, 'quantity': int}, ...]
            invoice_type: str - 'retail' or 'wholesale'
            invoice_id: int - ID of the invoice
            created_by: User object
        
        Returns:
            dict with success, items_added, items_removed, items_increased, items_decreased
        """
        from items.models import Item, StockMovement
        
        # Build lookup dictionaries
        original_dict = {item['item_id']: item['quantity'] for item in original_items}
        updated_dict = {item['item_id']: item['quantity'] for item in updated_items}
        
        # Calculate differences
        items_to_add_stock = []      # Removed items or decreased quantity
        items_to_deduct_stock = []   # Added items or increased quantity
        
        # Find removed items or decreased quantities
        for item_id, orig_qty in original_dict.items():
            if item_id not in updated_dict:
                # Item removed - add all stock back
                items_to_add_stock.append({
                    'item_id': item_id,
                    'quantity': orig_qty,
                    'reason': 'removed_from_invoice'
                })
            else:
                # Check for quantity change
                updated_qty = updated_dict[item_id]
                diff = orig_qty - updated_qty
                
                if diff > 0:
                    # Quantity decreased - add difference back
                    items_to_add_stock.append({
                        'item_id': item_id,
                        'quantity': diff,
                        'reason': 'quantity_decreased'
                    })
                elif diff < 0:
                    # Quantity increased - deduct difference
                    items_to_deduct_stock.append({
                        'item_id': item_id,
                        'quantity': abs(diff),
                        'reason': 'quantity_increased'
                    })
        
        # Find new items
        for item_id, updated_qty in updated_dict.items():
            if item_id not in original_dict:
                # New item - deduct stock
                items_to_deduct_stock.append({
                    'item_id': item_id,
                    'quantity': updated_qty,
                    'reason': 'added_to_invoice'
                })
        
        errors = []
        results = {
            'items_added': [],
            'items_removed': [],
            'items_increased': [],
            'items_decreased': []
        }
        
        try:
            with transaction.atomic():
                # PHASE 1: Validate all deductions are possible
                for item_data in items_to_deduct_stock:
                    item_id = item_data['item_id']
                    quantity = item_data['quantity']
                    
                    try:
                        item = Item.objects.select_for_update().get(
                            id=item_id,
                            is_deleted=False
                        )
                        
                        if not item.is_active:
                            errors.append(
                                f"{item.name} (HSN: {item.hns_code}) is not active"
                            )
                            continue
                        
                        if item.quantity < quantity:
                            errors.append(
                                f"Insufficient stock for {item.name} (HSN: {item.hns_code}). "
                                f"Available: {item.quantity}, Required: {quantity}"
                            )
                            continue
                        
                        item_data['item'] = item
                        
                    except Item.DoesNotExist:
                        errors.append(f"Item with ID {item_id} not found")
                
                # Validate items for stock addition
                for item_data in items_to_add_stock:
                    item_id = item_data['item_id']
                    
                    try:
                        item = Item.objects.select_for_update().get(
                            id=item_id,
                            is_deleted=False
                        )
                        item_data['item'] = item
                        
                    except Item.DoesNotExist:
                        errors.append(f"Item with ID {item_id} not found")
                
                if errors:
                    raise ValidationError(errors)
                
                # PHASE 2: Process stock additions
                for item_data in items_to_add_stock:
                    item = item_data['item']
                    quantity = item_data['quantity']
                    reason = item_data['reason']
                    
                    item.quantity += quantity
                    item.save(update_fields=['quantity', 'updated_at'])
                    
                    # Determine movement type
                    if reason == 'removed_from_invoice':
                        movement_type = 'adjustment'
                        notes = f"Item removed from {invoice_type} invoice #{invoice_id}"
                        results['items_removed'].append(item.name)
                    else:
                        movement_type = 'adjustment'
                        notes = f"Quantity decreased in {invoice_type} invoice #{invoice_id}"
                        results['items_decreased'].append(item.name)
                    
                    StockMovement.objects.create(
                        item=item,
                        quantity=quantity,
                        movement_type=movement_type,
                        invoice_id=invoice_id,
                        invoice_type=invoice_type,
                        created_by=created_by,
                        notes=notes
                    )
                    
                    logger.info(
                        f"✅ Stock adjusted: {item.name} - Added {quantity}, "
                        f"New Stock: {item.quantity}, Reason: {reason}"
                    )
                
                # PHASE 3: Process stock deductions
                for item_data in items_to_deduct_stock:
                    item = item_data['item']
                    quantity = item_data['quantity']
                    reason = item_data['reason']
                    
                    item.quantity -= quantity
                    item.save(update_fields=['quantity', 'updated_at'])
                    
                    # Determine movement type
                    if reason == 'added_to_invoice':
                        movement_type = f'{invoice_type}_sale'
                        notes = f"Item added to {invoice_type} invoice #{invoice_id}"
                        results['items_added'].append(item.name)
                    else:
                        movement_type = 'adjustment'
                        notes = f"Quantity increased in {invoice_type} invoice #{invoice_id}"
                        results['items_increased'].append(item.name)
                    
                    StockMovement.objects.create(
                        item=item,
                        quantity=-quantity,
                        movement_type=movement_type,
                        invoice_id=invoice_id,
                        invoice_type=invoice_type,
                        created_by=created_by,
                        notes=notes
                    )
                    
                    logger.info(
                        f"✅ Stock adjusted: {item.name} - Deducted {quantity}, "
                        f"New Stock: {item.quantity}, Reason: {reason}"
                    )
                
        except ValidationError:
            return {
                'success': False,
                'items_added': [],
                'items_removed': [],
                'items_increased': [],
                'items_decreased': [],
                'errors': errors,
                'message': 'Invoice update failed. Transaction rolled back.'
            }
        except Exception as e:
            logger.error(f"Unexpected error in update_stock_for_invoice_update: {e}", exc_info=True)
            return {
                'success': False,
                'items_added': [],
                'items_removed': [],
                'items_increased': [],
                'items_decreased': [],
                'errors': [str(e)],
                'message': 'An unexpected error occurred'
            }
        
        total_changes = (
            len(results['items_added']) + 
            len(results['items_removed']) + 
            len(results['items_increased']) + 
            len(results['items_decreased'])
        )
        
        return {
            'success': True,
            **results,
            'errors': [],
            'message': f'Successfully processed {total_changes} stock adjustment(s)'
        }
    
    @staticmethod
    def restore_stock_for_invoice_deletion(invoice_items, invoice_type='retail', invoice_id=None, created_by=None):
        """
        ✅ Restore all stock when invoice is deleted/cancelled.
        
        Args:
            invoice_items: List [{'item_id': int, 'quantity': int}, ...]
            invoice_type: str - 'retail' or 'wholesale'
            invoice_id: int - ID of the invoice being deleted
            created_by: User object
        
        Returns:
            dict with success, items_processed, errors, message
        """
        from items.models import Item, StockMovement
        
        if not invoice_items:
            return {
                'success': True,
                'items_processed': [],
                'errors': [],
                'message': 'No items to restore'
            }
        
        errors = []
        items_processed = []
        
        try:
            with transaction.atomic():
                for item_data in invoice_items:
                    item_id = item_data.get('item_id')
                    quantity = item_data.get('quantity', 0)
                    
                    if not item_id or quantity <= 0:
                        continue
                    
                    try:
                        item = Item.objects.select_for_update().get(
                            id=item_id,
                            is_deleted=False
                        )
                        
                        # Restore stock
                        item.quantity += quantity
                        item.save(update_fields=['quantity', 'updated_at'])
                        
                        # Log stock movement
                        StockMovement.objects.create(
                            item=item,
                            quantity=quantity,
                            movement_type='return',
                            invoice_id=invoice_id,
                            invoice_type=invoice_type,
                            created_by=created_by,
                            notes=f"Stock restored due to {invoice_type} invoice #{invoice_id} deletion"
                        )
                        
                        items_processed.append(item.name)
                        
                        logger.info(
                            f"✅ Stock restored: {item.name} - Quantity: {quantity}, "
                            f"New Stock: {item.quantity}"
                        )
                        
                    except Item.DoesNotExist:
                        errors.append(f"Item with ID {item_id} not found")
                        continue
                
                if errors:
                    logger.warning(f"Some items could not be restored: {errors}")
                    
        except Exception as e:
            logger.error(f"Unexpected error in restore_stock_for_invoice_deletion: {e}", exc_info=True)
            return {
                'success': False,
                'items_processed': [],
                'errors': [str(e)],
                'message': 'An unexpected error occurred'
            }
        
        return {
            'success': True,
            'items_processed': items_processed,
            'errors': errors,
            'message': f'Successfully restored stock for {len(items_processed)} item(s)'
        }

# PART 3 OF 3 (FINAL) - APPEND THIS AFTER PART 2
# Helper methods and convenience functions

    @staticmethod
    def check_stock_availability(items_to_check):
        """
        ✅ Check stock availability before creating invoice.
        
        Args:
            items_to_check: List [{'item_id': int, 'quantity': int}, ...]
        
        Returns:
            dict: {
                'available': bool,
                'unavailable_items': list of dicts,
                'message': str
            }
        """
        from items.models import Item
        
        unavailable_items = []
        
        try:
            for item_data in items_to_check:
                item_id = item_data.get('item_id')
                requested_qty = item_data.get('quantity', 0)
                
                if not item_id or requested_qty <= 0:
                    continue
                
                try:
                    item = Item.objects.get(
                        id=item_id,
                        is_deleted=False
                    )
                    
                    if not item.is_active:
                        unavailable_items.append({
                            'item_id': item.id,
                            'name': item.name,
                            'hns_code': item.hns_code,
                            'available': item.quantity,
                            'requested': requested_qty,
                            'reason': 'Item is not active'
                        })
                    elif item.quantity < requested_qty:
                        unavailable_items.append({
                            'item_id': item.id,
                            'name': item.name,
                            'hns_code': item.hns_code,
                            'available': item.quantity,
                            'requested': requested_qty,
                            'reason': 'Insufficient stock'
                        })
                
                except Item.DoesNotExist:
                    unavailable_items.append({
                        'item_id': item_id,
                        'name': 'Unknown',
                        'hns_code': 'N/A',
                        'available': 0,
                        'requested': requested_qty,
                        'reason': 'Item not found'
                    })
        
        except Exception as e:
            logger.error(f"Error checking stock availability: {e}", exc_info=True)
            return {
                'available': False,
                'unavailable_items': [],
                'message': f'Error checking availability: {str(e)}'
            }
        
        if unavailable_items:
            return {
                'available': False,
                'unavailable_items': unavailable_items,
                'message': f'{len(unavailable_items)} item(s) unavailable or insufficient stock'
            }
        
        return {
            'available': True,
            'unavailable_items': [],
            'message': 'All items available'
        }
    
    @staticmethod
    def check_stock_for_invoice_update(original_items, updated_items):
        """
        ✅ Check stock for invoice update.
        Only validates increased quantities and new items.
        
        Args:
            original_items: List with original quantities
            updated_items: List with updated quantities
        
        Returns:
            dict: {
                'available': bool,
                'unavailable_items': list,
                'message': str
            }
        """
        from items.models import Item
        
        original_dict = {item['item_id']: item['quantity'] for item in original_items}
        unavailable_items = []
        
        for item_data in updated_items:
            item_id = item_data['item_id']
            requested_qty = item_data['quantity']
            
            # Calculate additional quantity needed
            original_qty = original_dict.get(item_id, 0)
            additional_needed = requested_qty - original_qty
            
            # Only check if we need more stock
            if additional_needed > 0:
                try:
                    item = Item.objects.get(id=item_id, is_deleted=False)
                    
                    if not item.is_active:
                        unavailable_items.append({
                            'item_id': item.id,
                            'name': item.name,
                            'hns_code': item.hns_code,
                            'available': item.quantity,
                            'additional_needed': additional_needed,
                            'reason': 'Item is not active'
                        })
                    elif item.quantity < additional_needed:
                        unavailable_items.append({
                            'item_id': item.id,
                            'name': item.name,
                            'hns_code': item.hns_code,
                            'available': item.quantity,
                            'additional_needed': additional_needed,
                            'reason': f'Insufficient stock (need {additional_needed} more)'
                        })
                        
                except Item.DoesNotExist:
                    unavailable_items.append({
                        'item_id': item_id,
                        'name': 'Unknown',
                        'hns_code': 'N/A',
                        'available': 0,
                        'additional_needed': additional_needed,
                        'reason': 'Item not found'
                    })
        
        if unavailable_items:
            return {
                'available': False,
                'unavailable_items': unavailable_items,
                'message': f'{len(unavailable_items)} item(s) have insufficient stock for update'
            }
        
        return {
            'available': True,
            'unavailable_items': [],
            'message': 'Stock available for update'
        }
    
    @staticmethod
    def get_item_stock_info(item_id):
        """
        ✅ Get current stock info for AJAX calls.
        
        Args:
            item_id: int - ID of the item
        
        Returns:
            dict: Complete item stock information
        """
        from items.models import Item
        
        try:
            item = Item.objects.get(id=item_id, is_deleted=False)
            
            return {
                'success': True,
                'item_id': item.id,
                'name': item.name,
                'hns_code': item.hns_code,
                'current_stock': item.quantity,
                'is_active': item.is_active,
                'is_low_stock': item.is_low_stock,
                'is_out_of_stock': item.is_out_of_stock,
                'price_retail': str(item.price_retail),
                'price_wholesale': str(item.price_wholesale),
                'gst_percent': str(item.gst_percent),
                'discount': str(item.discount),
                'error': None
            }
            
        except Item.DoesNotExist:
            return {
                'success': False,
                'item_id': item_id,
                'name': 'Unknown',
                'hns_code': 'N/A',
                'current_stock': 0,
                'is_active': False,
                'is_low_stock': False,
                'is_out_of_stock': True,
                'price_retail': '0.00',
                'price_wholesale': '0.00',
                'gst_percent': '0.00',
                'discount': '0.00',
                'error': 'Item not found'
            }


# =============================================================================
# ✅ CONVENIENCE FUNCTIONS - For easy imports in your views
# These are at MODULE LEVEL (outside the class)
# =============================================================================

def deduct_items_for_invoice(invoice_items, invoice_type='retail', invoice_id=None, created_by=None):
    """
    ✅ Use this in retail/wholesale views when creating invoices.
    
    Example:
        from core.inventory_manager import deduct_items_for_invoice
        
        result = deduct_items_for_invoice(
            invoice_items=[
                {'item_id': 1, 'quantity': 5},
                {'item_id': 2, 'quantity': 3},
            ],
            invoice_type='retail',
            invoice_id=invoice.id,
            created_by=request.user
        )
        
        if not result['success']:
            for error in result['errors']:
                messages.error(request, error)
    """
    return InventoryManager.deduct_stock_for_invoice(
        invoice_items=invoice_items,
        invoice_type=invoice_type,
        invoice_id=invoice_id,
        created_by=created_by
    )


def add_items_for_return(return_items, invoice_type='retail', invoice_id=None, return_id=None, created_by=None):
    """
    ✅ Use this in retail/wholesale views when processing returns.
    
    Example:
        from core.inventory_manager import add_items_for_return
        
        result = add_items_for_return(
            return_items=[
                {'item_id': 1, 'quantity': 2},
            ],
            invoice_type='retail',
            invoice_id=invoice.id,
            return_id=return_record.id,
            created_by=request.user
        )
    """
    return InventoryManager.add_stock_for_return(
        return_items=return_items,
        invoice_type=invoice_type,
        invoice_id=invoice_id,
        return_id=return_id,
        created_by=created_by
    )


def update_items_for_invoice(original_items, updated_items, invoice_type='retail', invoice_id=None, created_by=None):
    """
    ✅ Use this in retail/wholesale views when updating invoices.
    
    Example:
        from core.inventory_manager import update_items_for_invoice
        
        result = update_items_for_invoice(
            original_items=[{'item_id': 1, 'quantity': 5}],
            updated_items=[{'item_id': 1, 'quantity': 10}],
            invoice_type='retail',
            invoice_id=invoice.id,
            created_by=request.user
        )
    """
    return InventoryManager.update_stock_for_invoice_update(
        original_items=original_items,
        updated_items=updated_items,
        invoice_type=invoice_type,
        invoice_id=invoice_id,
        created_by=created_by
    )


def restore_items_for_invoice_deletion(invoice_items, invoice_type='retail', invoice_id=None, created_by=None):
    """
    ✅ Use this in retail/wholesale views when deleting invoices.
    
    Example:
        from core.inventory_manager import restore_items_for_invoice_deletion
        
        result = restore_items_for_invoice_deletion(
            invoice_items=[{'item_id': 1, 'quantity': 5}],
            invoice_type='retail',
            invoice_id=invoice.id,
            created_by=request.user
        )
    """
    return InventoryManager.restore_stock_for_invoice_deletion(
        invoice_items=invoice_items,
        invoice_type=invoice_type,
        invoice_id=invoice_id,
        created_by=created_by
    )


def check_stock_availability(items_to_check):
    """
    ✅ Use this before creating invoices to validate stock.
    
    Example:
        from core.inventory_manager import check_stock_availability
        
        result = check_stock_availability([
            {'item_id': 1, 'quantity': 5},
            {'item_id': 2, 'quantity': 3},
        ])
        
        if not result['available']:
            for item in result['unavailable_items']:
                messages.error(request, f"{item['name']}: {item['reason']}")
    """
    return InventoryManager.check_stock_availability(items_to_check)


def check_stock_for_update(original_items, updated_items):
    """
    ✅ Use this before updating invoices to validate stock.
    
    Example:
        from core.inventory_manager import check_stock_for_update
        
        result = check_stock_for_update(
            original_items=[{'item_id': 1, 'quantity': 5}],
            updated_items=[{'item_id': 1, 'quantity': 10}]
        )
        
        if not result['available']:
            # Handle insufficient stock
            pass
    """
    return InventoryManager.check_stock_for_invoice_update(original_items, updated_items)


def get_item_stock_info(item_id):
    """
    ✅ Use this for AJAX calls to get real-time stock info.
    
    Example:
        from core.inventory_manager import get_item_stock_info
        
        # In your view (for AJAX endpoint)
        from django.http import JsonResponse
        
        def get_stock(request, item_id):
            result = get_item_stock_info(item_id)
            return JsonResponse(result)
    """
    return InventoryManager.get_item_stock_info(item_id)


# END OF PART 3 - FILE COMPLETE
# Copy all 3 parts into: D:\Clients Projects\Darbar_Boot_house\DarbarBootsPro\core\inventory_manager.py