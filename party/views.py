from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView, View
from django.urls import reverse_lazy
from django.shortcuts import redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from .models import Party
from .forms import PartyForm
from .utils import send_whatsapp_reminder
import logging

logger = logging.getLogger(__name__)


class PartyListView(LoginRequiredMixin, ListView):
    """
    List all active parties with their balance summaries.
    Includes search functionality and optimized queries.
    """
    model = Party
    template_name = 'party/party_list.html'
    context_object_name = 'party_data'
    ordering = ['name']

    def get_queryset(self):
        """
        Get parties with calculated balances.
        Optimized with select_related and prefetch_related.
        """
        parties = (
            Party.objects
            .select_related('created_by', 'updated_by')
            .prefetch_related('invoices', 'payments')
            .order_by('name')
        )
        
        # Search functionality
        search_query = self.request.GET.get('search', '').strip()
        if search_query:
            parties = parties.filter(
                Q(name__icontains=search_query) |
                Q(contact_person__icontains=search_query) |
                Q(phone__icontains=search_query) |
                Q(email__icontains=search_query)
            )
        
        # Build party data with calculated fields
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
    
    def get_context_data(self, **kwargs):
        """Add search query to context."""
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('search', '')
        return context


class PartyCreateView(LoginRequiredMixin, CreateView):
    """Create a new party with user tracking."""
    model = Party
    form_class = PartyForm
    template_name = 'party/party_form.html'
    success_url = reverse_lazy('party:party_list')

    def form_valid(self, form):
        """Set created_by and updated_by fields."""
        party = form.save(commit=False)
        party.created_by = self.request.user
        party.updated_by = self.request.user
        party.save()
        messages.success(self.request, f'Party "{party.name}" created successfully.')
        return super().form_valid(form)

    def form_invalid(self, form):
        """Show error message when form validation fails."""
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        """Add form action type to context."""
        context = super().get_context_data(**kwargs)
        context['action'] = 'Add'
        context['title'] = 'Add New Party'
        return context


class PartyUpdateView(LoginRequiredMixin, UpdateView):
    """Edit existing party with user tracking."""
    model = Party
    form_class = PartyForm
    template_name = 'party/party_form.html'
    success_url = reverse_lazy('party:party_list')

    def get_object(self, queryset=None):
        """Get party object with optimization."""
        obj = get_object_or_404(
            Party.objects.select_related('created_by', 'updated_by'),
            pk=self.kwargs['pk']
        )
        return obj

    def form_valid(self, form):
        """Update the updated_by field on save."""
        party = form.save(commit=False)
        party.updated_by = self.request.user
        party.save()
        messages.success(self.request, f'Party "{party.name}" updated successfully.')
        return super().form_valid(form)

    def form_invalid(self, form):
        """Show error message when form validation fails."""
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        """Add form action type to context."""
        context = super().get_context_data(**kwargs)
        context['action'] = 'Edit'
        context['title'] = f'Edit Party: {self.object.name}'
        return context


class PartyDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a party with confirmation."""
    model = Party
    template_name = 'party/party_confirm_delete.html'
    success_url = reverse_lazy('party:party_list')

    def get_object(self, queryset=None):
        """Get party object."""
        obj = get_object_or_404(Party, pk=self.kwargs['pk'])
        return obj

    def delete(self, request, *args, **kwargs):
        """Delete party and show success message."""
        party = self.get_object()
        party_name = party.name
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f'Party "{party_name}" deleted successfully.')
        return response
    
    def get_context_data(self, **kwargs):
        """Add party details to context for confirmation page."""
        context = super().get_context_data(**kwargs)
        party = self.get_object()
        context['party'] = party
        context['has_invoices'] = party.invoices.exists()
        context['has_payments'] = party.payments.exists()
        return context


class PartyDetailView(LoginRequiredMixin, DetailView):
    """
    Detailed view of a party with invoices and payments.
    Optimized queries with prefetch_related.
    """
    model = Party
    template_name = 'party/party_detail.html'
    context_object_name = 'party'

    def get_object(self, queryset=None):
        """Get party with optimized related data queries."""
        return get_object_or_404(
            Party.objects.select_related('created_by', 'updated_by')
                         .prefetch_related('invoices__invoice_items__item',
                                         'invoices__payments',
                                         'payments__invoice'),
            pk=self.kwargs['pk']
        )

    def get_context_data(self, **kwargs):
        """Add invoice details, payments, and KPIs to context."""
        context = super().get_context_data(**kwargs)
        party = self.object
        
        # Get invoices ordered by date (most recent first)
        invoices = party.invoices.select_related('created_by').order_by('-date')
        
        # Get all payments ordered by date (most recent first)
        payments = party.payments.select_related('invoice').order_by('-date')

        # Build invoice details with payment info
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

        # Calculate KPIs
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
    """Send WhatsApp reminder to party for pending payments."""
    
    def get(self, request, pk, *args, **kwargs):
        """Handle reminder sending with validation and error handling."""
        party = get_object_or_404(Party, pk=pk)
        
        # Check if there's pending balance
        if party.pending_amount <= 0:
            messages.info(request, f"No pending balance for {party.name}.")
            return redirect('party:party_detail', pk=party.id)
        
        # Check if phone number exists
        if not party.phone:
            messages.warning(request, f"Phone number not found for {party.name}.")
            return redirect('party:party_detail', pk=party.id)

        try:
            success = send_whatsapp_reminder(party)
            if success:
                messages.success(request, f"WhatsApp reminder sent to {party.name} successfully.")
            else:
                messages.warning(request, f"Could not send reminder. Please check phone number.")
        except Exception as e:
            logger.error(f"Error sending reminder to party {party.id}: {e}")
            messages.error(request, "Failed to send reminder. Please try again.")

        return redirect('party:party_detail', pk=party.id)
    
    def post(self, request, pk, *args, **kwargs):
        """Handle POST request (same as GET for compatibility)."""
        return self.get(request, pk, *args, **kwargs)