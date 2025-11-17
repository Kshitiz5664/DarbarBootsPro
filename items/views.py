from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.shortcuts import redirect
from .models import Item
from .forms import ItemForm
from .models import generate_hns_no_migration
from django.apps import apps



class ItemListView(LoginRequiredMixin, ListView):
    model = Item
    template_name = 'items/item_list.html'
    context_object_name = 'items'

    def get_queryset(self):
        # Filter only active (not deleted) items
        return Item.objects.filter(is_deleted=False).order_by('-id')


class ItemCreateView(LoginRequiredMixin, CreateView):
    model = Item
    form_class = ItemForm
    template_name = 'items/item_form.html'
    success_url = reverse_lazy('items:item_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        if not form.instance.hns_code:
            form.instance.hns_code = generate_hns_no_migration()
        messages.success(self.request, "Item added successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = 'Add'
        return context


class ItemUpdateView(LoginRequiredMixin, UpdateView):
    model = Item
    form_class = ItemForm
    template_name = 'items/item_form.html'
    success_url = reverse_lazy('items:item_list')

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        messages.success(self.request, "Item updated successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = 'Edit'
        return context


class ItemDeleteView(LoginRequiredMixin, DeleteView):
    model = Item
    template_name = 'items/item_confirm_delete.html'
    success_url = reverse_lazy('items:item_list')

    def post(self, request, *args, **kwargs):
        """Soft delete item instead of actual delete."""
        item = self.get_object()
        item.is_deleted = True
        item.save()
        messages.warning(request, f"Item '{item.name}' marked as deleted.")
        return redirect(self.success_url)
