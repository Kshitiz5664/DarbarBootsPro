from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView, FormView
from django.shortcuts import redirect, get_object_or_404, render
from django.db.models import Q
from django.core.exceptions import ValidationError
from .models import Item, StockMovement
from .forms import ItemForm, StockAdjustmentForm
from .models import generate_hns_no_migration


class ItemListView(LoginRequiredMixin, ListView):
    """
    Display list of all active inventory items.
    Supports search and filtering functionality.
    """
    model = Item
    template_name = 'items/item_list.html'
    context_object_name = 'items'
    paginate_by = 50  # ✅ Added pagination

    def get_queryset(self):
        """
        Filter active items and apply search/filters if provided.
        Optimized query with select_related for user fields.
        """
        queryset = (
            Item.objects
            .filter(is_deleted=False)
            .select_related('created_by', 'updated_by')
            .order_by('-id')
        )
        
        # Search functionality
        search_query = self.request.GET.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(hns_code__icontains=search_query)
            )
        
        # ✅ NEW: Filter by active status
        status_filter = self.request.GET.get('status', '')
        if status_filter == 'active':
            queryset = queryset.filter(is_active=True)
        elif status_filter == 'inactive':
            queryset = queryset.filter(is_active=False)
        
        # ✅ NEW: Filter by stock status
        stock_filter = self.request.GET.get('stock', '')
        if stock_filter == 'low':
            queryset = queryset.filter(quantity__lte=10, quantity__gt=0)
        elif stock_filter == 'out':
            queryset = queryset.filter(quantity=0)
        
        # ✅ NEW: Filter featured items
        if self.request.GET.get('featured') == 'true':
            queryset = queryset.filter(is_featured=True)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        """Add search query and filters to context for template."""
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('search', '')
        context['status_filter'] = self.request.GET.get('status', '')
        context['stock_filter'] = self.request.GET.get('stock', '')
        context['featured_filter'] = self.request.GET.get('featured', '')
        
        # ✅ NEW: Add statistics
        all_items = Item.objects.filter(is_deleted=False)
        context['stats'] = {
            'total_items': all_items.count(),
            'active_items': all_items.filter(is_active=True).count(),
            'low_stock_items': all_items.filter(quantity__lte=10, quantity__gt=0).count(),
            'out_of_stock_items': all_items.filter(quantity=0).count(),
            'featured_items': all_items.filter(is_featured=True).count(),
        }
        
        return context


class ItemDetailView(LoginRequiredMixin, DetailView):
    """
    ✅ NEW: Display detailed item information with stock movement history.
    """
    model = Item
    template_name = 'items/item_detail.html'
    context_object_name = 'item'
    
    def get_object(self, queryset=None):
        """Get item object with related data."""
        return get_object_or_404(
            Item.objects.select_related('created_by', 'updated_by'),
            pk=self.kwargs['pk']
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Get recent stock movements
        context['stock_movements'] = (
            self.object.stock_movements
            .select_related('created_by')
            .order_by('-created_at')[:20]
        )
        return context


class ItemCreateView(LoginRequiredMixin, CreateView):
    """
    Create new inventory item with automatic HNS code generation.
    """
    model = Item
    form_class = ItemForm
    template_name = 'items/item_form.html'
    success_url = reverse_lazy('items:item_list')

    def form_valid(self, form):
        """
        Set created_by and updated_by fields.
        Auto-generate HNS code if not provided.
        """
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        
        # ✅ FIXED: Always auto-generate HNS code (field is non-editable)
        form.instance.hns_code = generate_hns_no_migration()
        
        messages.success(self.request, f"Item '{form.instance.name}' added successfully with HNS Code: {form.instance.hns_code}")
        return super().form_valid(form)
    
    def form_invalid(self, form):
        """Show error message when form validation fails."""
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        """Add form action type to context."""
        context = super().get_context_data(**kwargs)
        context['action'] = 'Add'
        return context


class ItemUpdateView(LoginRequiredMixin, UpdateView):
    """
    Update existing inventory item.
    HNS code is protected and cannot be edited.
    """
    model = Item
    form_class = ItemForm
    template_name = 'items/item_form.html'
    success_url = reverse_lazy('items:item_list')

    def get_object(self, queryset=None):
        """Get item object with optimization."""
        obj = get_object_or_404(
            Item.objects.select_related('created_by', 'updated_by'),
            pk=self.kwargs['pk']
        )
        return obj

    def form_valid(self, form):
        """
        ✅ FIXED: Preserve HNS code during update.
        Update the updated_by field on save.
        """
        # Get the original item from database
        original_item = self.get_object()
        
        # Preserve the HNS code (it should never change)
        form.instance.hns_code = original_item.hns_code
        form.instance.updated_by = self.request.user
        
        messages.success(self.request, f"Item '{form.instance.name}' updated successfully.")
        return super().form_valid(form)
    
    def form_invalid(self, form):
        """Show error message when form validation fails."""
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        """Add form action type and HNS code to context."""
        context = super().get_context_data(**kwargs)
        context['action'] = 'Edit'
        context['hns_code'] = self.object.hns_code  # ✅ Pass HNS code to template
        return context


class ItemDeleteView(LoginRequiredMixin, DeleteView):
    """
    Soft delete inventory item (marks as deleted instead of removing).
    """
    model = Item
    template_name = 'items/item_confirm_delete.html'
    success_url = reverse_lazy('items:item_list')

    def get_object(self, queryset=None):
        """Get item object."""
        obj = get_object_or_404(Item, pk=self.kwargs['pk'])
        return obj

    def post(self, request, *args, **kwargs):
        """Soft delete item instead of actual delete."""
        item = self.get_object()
        item.is_deleted = True
        item.updated_by = request.user
        item.save()
        
        messages.warning(request, f"Item '{item.name}' (HNS: {item.hns_code}) marked as deleted.")
        return redirect(self.success_url)
    
    def get_context_data(self, **kwargs):
        """Add item details to context for confirmation page."""
        context = super().get_context_data(**kwargs)
        context['item'] = self.get_object()
        return context


class StockAdjustmentView(LoginRequiredMixin, FormView):
    """
    ✅ NEW: Manual stock adjustment view (add/remove inventory).
    """
    template_name = 'items/stock_adjustment.html'
    form_class = StockAdjustmentForm
    
    def get_success_url(self):
        return reverse_lazy('items:item_detail', kwargs={'pk': self.kwargs['pk']})
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['item'] = get_object_or_404(Item, pk=self.kwargs['pk'])
        return context
    
    def form_valid(self, form):
        item = get_object_or_404(Item, pk=self.kwargs['pk'])
        adjustment_type = form.cleaned_data['adjustment_type']
        quantity = form.cleaned_data['quantity']
        reason = form.cleaned_data['reason']
        notes = form.cleaned_data['notes']
        
        try:
            if adjustment_type == 'add':
                item.add_stock(quantity, reason=reason)
                messages.success(
                    self.request,
                    f"Added {quantity} units to {item.name}. New stock: {item.quantity}"
                )
            else:  # remove
                item.deduct_stock(quantity, invoice_type='adjustment')
                messages.success(
                    self.request,
                    f"Removed {quantity} units from {item.name}. New stock: {item.quantity}"
                )
            
            # Update the stock movement with user info
            last_movement = item.stock_movements.first()
            if last_movement:
                last_movement.created_by = self.request.user
                last_movement.notes = notes or last_movement.notes
                last_movement.save()
                
        except ValidationError as e:
            messages.error(self.request, str(e))
            return self.form_invalid(form)
        
        return super().form_valid(form)


# ✅ NEW: Helper function for invoice creation (to be used in retail/wholesale apps)
def deduct_items_for_invoice(invoice_items, invoice_type='retail', invoice_id=None):
    """
    Deduct stock for multiple items when creating an invoice.
    
    Args:
        invoice_items: List of dicts with 'item_id' and 'quantity'
        invoice_type: 'retail' or 'wholesale'
        invoice_id: ID of the invoice (for tracking)
    
    Returns:
        dict: Success status and any error messages
    
    Example usage in your retail/wholesale views:
        result = deduct_items_for_invoice([
            {'item_id': 1, 'quantity': 5},
            {'item_id': 2, 'quantity': 3},
        ], invoice_type='retail', invoice_id=invoice.id)
    """
    from django.db import transaction
    
    errors = []
    success_items = []
    
    try:
        with transaction.atomic():
            for item_data in invoice_items:
                item = Item.objects.select_for_update().get(
                    id=item_data['item_id'],
                    is_deleted=False
                )
                
                # Check if item is active
                if not item.is_active:
                    errors.append(f"{item.name} is not active")
                    continue
                
                # Deduct stock
                try:
                    item.deduct_stock(
                        quantity=item_data['quantity'],
                        invoice_type=invoice_type
                    )
                    
                    # Update stock movement with invoice reference
                    last_movement = item.stock_movements.first()
                    if last_movement and invoice_id:
                        last_movement.invoice_id = invoice_id
                        last_movement.invoice_type = invoice_type
                        last_movement.save()
                    
                    success_items.append(item.name)
                    
                except ValidationError as e:
                    errors.append(f"{item.name}: {str(e)}")
            
            # If any errors, rollback transaction
            if errors:
                raise ValidationError(errors)
    
    except ValidationError:
        return {
            'success': False,
            'errors': errors,
            'message': 'Stock deduction failed. Please check item availability.'
        }
    except Item.DoesNotExist as e:
        return {
            'success': False,
            'errors': [f"Item not found: {str(e)}"],
            'message': 'One or more items not found.'
        }
    
    return {
        'success': True,
        'items': success_items,
        'message': f'Stock deducted successfully for {len(success_items)} items.'
    }


def add_items_for_return(return_items, invoice_type='retail', invoice_id=None):
    """
    Add stock back when items are returned.
    
    Args:
        return_items: List of dicts with 'item_id' and 'quantity'
        invoice_type: 'retail' or 'wholesale'
        invoice_id: ID of the original invoice
    
    Returns:
        dict: Success status and any messages
    
    Example usage:
        result = add_items_for_return([
            {'item_id': 1, 'quantity': 2},
        ], invoice_type='retail', invoice_id=invoice.id)
    """
    from django.db import transaction
    
    errors = []
    success_items = []
    
    try:
        with transaction.atomic():
            for item_data in return_items:
                item = Item.objects.select_for_update().get(
                    id=item_data['item_id'],
                    is_deleted=False
                )
                
                # Add stock back
                try:
                    item.add_stock(
                        quantity=item_data['quantity'],
                        reason='return'
                    )
                    
                    # Update stock movement with invoice reference
                    last_movement = item.stock_movements.first()
                    if last_movement and invoice_id:
                        last_movement.invoice_id = invoice_id
                        last_movement.invoice_type = invoice_type
                        last_movement.save()
                    
                    success_items.append(item.name)
                    
                except ValidationError as e:
                    errors.append(f"{item.name}: {str(e)}")
            
            if errors:
                raise ValidationError(errors)
    
    except ValidationError:
        return {
            'success': False,
            'errors': errors,
            'message': 'Stock return failed.'
        }
    except Item.DoesNotExist as e:
        return {
            'success': False,
            'errors': [f"Item not found: {str(e)}"],
            'message': 'One or more items not found.'
        }
    
    return {
        'success': True,
        'items': success_items,
        'message': f'Stock returned successfully for {len(success_items)} items.'
    }