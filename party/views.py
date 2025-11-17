# views.py
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView, View
from django.urls import reverse_lazy
from django.shortcuts import redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Party
from .forms import PartyForm
from .utils import send_whatsapp_reminder
import logging

logger = logging.getLogger(__name__)


class PartyListView(LoginRequiredMixin, ListView):
    """List all parties with balances"""
    model = Party
    template_name = 'party/party_list.html'
    context_object_name = 'party_data'
    ordering = ['name']

    def get_queryset(self):
        parties = super().get_queryset()
        party_data = []
        for party in parties:
            party_data.append({
                'party': party,
                'total_invoiced': party.total_invoiced,
                'total_paid': party.total_paid,
                'pending': party.pending_amount,
                'open_invoices': party.invoices.filter(is_paid=False).count(),
            })
        return party_data


class PartyCreateView(LoginRequiredMixin, CreateView):
    """Create a new party"""
    model = Party
    form_class = PartyForm
    template_name = 'party/party_form.html'
    success_url = reverse_lazy('party:party_list')

    def form_valid(self, form):
        party = form.save(commit=False)
        party.created_by = self.request.user
        party.updated_by = self.request.user
        party.save()
        messages.success(self.request, f'Party "{party.name}" created successfully.')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = 'Add'
        context['title'] = 'Add New Party'
        return context


class PartyUpdateView(LoginRequiredMixin, UpdateView):
    """Edit existing party"""
    model = Party
    form_class = PartyForm
    template_name = 'party/party_form.html'
    success_url = reverse_lazy('party:party_list')

    def form_valid(self, form):
        party = form.save(commit=False)
        party.updated_by = self.request.user
        party.save()
        messages.success(self.request, f'Party "{party.name}" updated successfully.')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = 'Edit'
        context['title'] = f'Edit Party: {self.object.name}'
        return context


class PartyDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a party"""
    model = Party
    template_name = 'party/party_confirm_delete.html'
    success_url = reverse_lazy('party:party_list')

    def delete(self, request, *args, **kwargs):
        party = self.get_object()
        party_name = party.name
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f'Party "{party_name}" deleted successfully.')
        return response


class PartyDetailView(LoginRequiredMixin, DetailView):
    """Detailed view of a party with invoices and payments"""
    model = Party
    template_name = 'party/party_detail.html'
    context_object_name = 'party'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        party = self.object
        invoices = party.invoices.select_related('created_by').prefetch_related('invoice_items__item', 'payments').order_by('-date')
        payments = party.payments.select_related('invoice').order_by('-date')

        invoice_details = []
        for invoice in invoices:
            invoice_paid = sum(p.amount for p in invoice.payments.all())
            invoice_balance = invoice.total_amount - invoice_paid
            invoice_details.append({
                'invoice': invoice,
                'items': invoice.invoice_items.all(),
                'payments': invoice.payments.all(),
                'total_paid': invoice_paid,
                'balance': invoice_balance,
                'status': 'Closed' if invoice.is_paid else 'Open'
            })

        context['invoice_details'] = invoice_details
        context['payments'] = payments
        context['kpi'] = {
            'total_invoiced': party.total_invoiced,
            'total_paid': party.total_paid,
            'pending': party.pending_amount,
            'open_invoices': party.invoices.filter(is_paid=False).count(),
            'closed_invoices': party.invoices.filter(is_paid=True).count(),
        }
        return context


class SendReminderView(LoginRequiredMixin, View):
    """Send WhatsApp reminder to party"""
    def get(self, request, pk, *args, **kwargs):
        party = get_object_or_404(Party, pk=pk)
        if party.pending_amount <= 0:
            messages.info(request, f"No pending balance for {party.name}.")
            return redirect('party:party_detail', pk=party.id)

        try:
            success = send_whatsapp_reminder(party)
            if success:
                messages.success(request, f"WhatsApp reminder sent to {party.name} successfully.")
            else:
                messages.warning(request, f"Could not send reminder. Please check phone number.")
        except Exception as e:
            logger.error(f"Error sending reminder: {e}")
            messages.error(request, "Failed to send reminder. Please try again.")

        return redirect('party:party_detail', pk=party.id)
