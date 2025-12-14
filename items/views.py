from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.shortcuts import redirect, get_object_or_404
from django.db.models import Q
from .models import Item
from .forms import ItemForm
from .models import generate_hns_no_migration


class ItemListView(LoginRequiredMixin, ListView):
    """
    Display list of all active inventory items.
    Supports search and filtering functionality.
    """
    model = Item
    template_name = 'items/item_list.html'
    context_object_name = 'items'

    def get_queryset(self):
        """
        Filter active items and apply search if provided.
        Optimized query with select_related for user fields.
        """
        queryset = (
            Item.objects
            .filter(is_deleted=False)
            .select_related('created_by', 'updated_by')
            .order_by('-id')
        )
        
        # Search functionality (optional enhancement)
        search_query = self.request.GET.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(hns_code__icontains=search_query)
            )
        
        return queryset
    
    def get_context_data(self, **kwargs):
        """Add search query to context for template."""
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('search', '')
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
        
        # Auto-generate HNS code if not provided
        if not form.instance.hns_code:
            form.instance.hns_code = generate_hns_no_migration()
        
        messages.success(self.request, "Item added successfully.")
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
    """
    model = Item
    form_class = ItemForm
    template_name = 'items/item_form.html'
    success_url = reverse_lazy('items:item_list')

    def get_object(self, queryset=None):
        """
        Get item object with optimization.
        """
        obj = get_object_or_404(
            Item.objects.select_related('created_by', 'updated_by'),
            pk=self.kwargs['pk']
        )
        return obj

    def form_valid(self, form):
        """Update the updated_by field on save."""
        form.instance.updated_by = self.request.user
        messages.success(self.request, "Item updated successfully.")
        return super().form_valid(form)
    
    def form_invalid(self, form):
        """Show error message when form validation fails."""
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        """Add form action type to context."""
        context = super().get_context_data(**kwargs)
        context['action'] = 'Edit'
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
        """
        Soft delete item instead of actual delete.
        """
        item = self.get_object()
        item.is_deleted = True
        item.save()
        
        messages.warning(request, f"Item '{item.name}' marked as deleted.")
        return redirect(self.success_url)
    
    def get_context_data(self, **kwargs):
        """Add item details to context for confirmation page."""
        context = super().get_context_data(**kwargs)
        context['item'] = self.get_object()
        return context