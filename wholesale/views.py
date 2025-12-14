"""
Wholesale dashboard and reporting views.
Provides analytics, KPIs, and financial reports for the wholesale business.
"""
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum, Count, F, DecimalField, ExpressionWrapper, Q
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from party.models import Party
from billing.models import Invoice, Payment, InvoiceItem
from items.models import Item


class DashboardHomeView(LoginRequiredMixin, TemplateView):
    """
    Main dashboard view with key performance indicators and recent activity.
    Shows financial overview, pending amounts, and recent transactions.
    """
    template_name = 'wholesale/dashboard_home.html'
    login_url = '/login/'

    def get_context_data(self, **kwargs):
        """Build dashboard context with KPIs and recent data."""
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()
        last_30_days = today - timedelta(days=30)

        # Annotate invoices with calculated total_amount (base_amount - returns)
        invoices = self._get_annotated_invoices()

        # Calculate core KPIs
        kpi = self._calculate_kpis(invoices, last_30_days)
        
        # Get top parties by pending amount
        top_pending_parties = self._get_top_pending_parties()

        # Get recent activity lists
        recent_invoice_list = (
            invoices
            .select_related('party', 'created_by')
            .order_by('-date')[:10]
        )
        
        recent_payment_list = (
            Payment.objects
            .select_related('party', 'invoice')
            .order_by('-date')[:10]
        )

        # Payment mode distribution
        payment_modes = (
            Payment.objects
            .values('mode')
            .annotate(total=Sum('amount'), count=Count('id'))
            .order_by('-total')
        )

        # Update context
        context.update({
            'kpi': kpi,
            'top_pending_parties': top_pending_parties,
            'recent_invoices': recent_invoice_list,
            'recent_payments': recent_payment_list,
            'payment_modes': payment_modes,
            'today': today,
        })
        
        return context

    def _get_annotated_invoices(self):
        """
        Get invoices annotated with total_amount = base_amount - returns.
        Cached for reuse within the view.
        """
        return (
            Invoice.objects
            .annotate(
                total_return_sum=Sum('returns__amount', default=Decimal('0.00'))
            )
            .annotate(
                total_amount=ExpressionWrapper(
                    F('base_amount') - F('total_return_sum'),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )
        )

    def _calculate_kpis(self, invoices, last_30_days):
        """Calculate key performance indicators."""
        total_invoiced = invoices.aggregate(
            total=Sum('total_amount')
        )['total'] or Decimal('0.00')
        
        total_received = Payment.objects.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        
        total_pending = total_invoiced - total_received

        # Recent activity (last 30 days)
        recent_invoices = invoices.filter(date__gte=last_30_days).aggregate(
            total=Sum('total_amount'),
            count=Count('id')
        )
        
        recent_payments = Payment.objects.filter(date__gte=last_30_days).aggregate(
            total=Sum('amount'),
            count=Count('id')
        )

        return {
            'total_parties': Party.objects.count(),
            'total_invoices': invoices.count(),
            'total_open_invoices': invoices.filter(is_paid=False).count(),
            'total_closed_invoices': invoices.filter(is_paid=True).count(),
            'total_invoiced': total_invoiced,
            'total_received': total_received,
            'total_pending': total_pending,
            'recent_invoices_total': recent_invoices['total'] or Decimal('0.00'),
            'recent_invoices_count': recent_invoices['count'] or 0,
            'recent_payments_total': recent_payments['total'] or Decimal('0.00'),
            'recent_payments_count': recent_payments['count'] or 0,
        }

    def _get_top_pending_parties(self, limit=10):
        """
        Get top parties by pending amount.
        Uses property method on Party model for pending calculation.
        """
        parties = Party.objects.prefetch_related('invoices', 'payments').all()
        
        parties_with_pending = [
            {
                'party': party,
                'pending': party.pending_amount,
                'total_invoiced': party.total_invoiced,
                'total_paid': party.total_paid,
            }
            for party in parties
            if party.pending_amount > 0
        ]
        
        # Sort by pending amount (highest first)
        parties_with_pending.sort(key=lambda x: x['pending'], reverse=True)
        
        return parties_with_pending[:limit]


class AnalyticsReportView(LoginRequiredMixin, TemplateView):
    """
    Comprehensive analytics dashboard with monthly trends and party summaries.
    Provides insights into sales patterns and customer behavior.
    """
    template_name = 'wholesale/analytics_report.html'
    login_url = '/login/'

    def get_context_data(self, **kwargs):
        """Build analytics context with monthly data and summaries."""
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()

        # Get annotated invoices
        invoices = self._get_annotated_invoices()

        # Calculate monthly analytics (last 12 months)
        monthly_data = self._calculate_monthly_analytics(invoices, today)

        # Generate party summary
        party_summary = self._generate_party_summary()

        # Get item-wise sales analysis
        item_sales = self._get_item_sales_analysis()

        # Update context
        context.update({
            'monthly_data': monthly_data,
            'party_summary': party_summary,
            'item_sales': item_sales,
            'today': today,
        })
        
        return context

    def _get_annotated_invoices(self):
        """Get invoices with calculated total_amount."""
        return (
            Invoice.objects
            .annotate(
                total_return_sum=Sum('returns__amount', default=Decimal('0.00'))
            )
            .annotate(
                total_amount=ExpressionWrapper(
                    F('base_amount') - F('total_return_sum'),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )
        )

    def _calculate_monthly_analytics(self, invoices, today):
        """Calculate monthly invoice and payment totals for last 12 months."""
        monthly_data = []
        
        for i in range(11, -1, -1):  # Reverse for chronological order
            # Calculate month boundaries
            month_start = (today.replace(day=1) - timedelta(days=30 * i)).replace(day=1)
            next_month = (month_start.replace(day=28) + timedelta(days=4))
            month_end = next_month - timedelta(days=next_month.day)

            # Filter data for this month
            month_invoices = invoices.filter(
                date__range=[month_start, month_end]
            )
            
            month_payments = Payment.objects.filter(
                date__range=[month_start, month_end]
            )

            # Aggregate totals
            invoiced_total = month_invoices.aggregate(
                total=Sum('total_amount')
            )['total'] or Decimal('0.00')
            
            received_total = month_payments.aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0.00')

            monthly_data.append({
                'month': month_start.strftime('%B %Y'),
                'invoiced': invoiced_total,
                'received': received_total,
                'invoice_count': month_invoices.count(),
                'payment_count': month_payments.count(),
            })

        return monthly_data

    def _generate_party_summary(self):
        """Generate comprehensive party summary sorted by pending amount."""
        parties = Party.objects.prefetch_related('invoices', 'payments').all()
        
        party_summary = [
            {
                'party': party,
                'total_invoiced': party.total_invoiced,
                'total_paid': party.total_paid,
                'pending': party.pending_amount,
                'invoice_count': party.invoices.count(),
                'payment_count': party.payments.count(),
            }
            for party in parties
        ]
        
        # Sort by pending amount (highest first)
        party_summary.sort(key=lambda x: x['pending'], reverse=True)
        
        return party_summary

    def _get_item_sales_analysis(self, limit=20):
        """Get top-selling items by quantity and revenue."""
        return (
            InvoiceItem.objects
            .values('item__id', 'item__name')
            .annotate(
                total_quantity=Sum('quantity'),
                total_amount=Sum('total')
            )
            .filter(total_quantity__gt=0)
            .order_by('-total_amount')[:limit]
        )


class PendingInvoicesReportView(LoginRequiredMixin, TemplateView):
    """
    Detailed report of all pending (unpaid) invoices.
    Shows balance due and days pending for each invoice.
    """
    template_name = 'wholesale/pending_invoices_report.html'
    login_url = '/login/'

    def get_context_data(self, **kwargs):
        """Build pending invoices report with payment details."""
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()

        # Get all unpaid invoices with related data
        pending_invoices = (
            Invoice.objects
            .filter(is_paid=False)
            .select_related('party', 'created_by')
            .prefetch_related('payments')
            .order_by('-date')
        )

        # Build detailed invoice list
        invoice_details = [
            {
                'invoice': inv,
                'paid': inv.total_paid,
                'balance': inv.balance_due,
                'days_pending': (today - inv.date).days,
            }
            for inv in pending_invoices
        ]

        # Sort by days pending (oldest first)
        invoice_details.sort(key=lambda x: x['days_pending'], reverse=True)

        # Calculate totals
        total_pending = sum(i['balance'] for i in invoice_details)

        # Update context
        context.update({
            'invoice_details': invoice_details,
            'total_pending_amount': total_pending,
            'total_count': len(invoice_details),
            'today': today,
        })
        
        return context


class PaymentHistoryReportView(LoginRequiredMixin, TemplateView):
    """
    Complete payment history with breakdown by payment mode.
    Shows all received payments and categorizes by payment method.
    """
    template_name = 'wholesale/payment_history_report.html'
    login_url = '/login/'

    def get_context_data(self, **kwargs):
        """Build payment history report with mode breakdown."""
        context = super().get_context_data(**kwargs)

        # Get all payments with related data
        payments = (
            Payment.objects
            .select_related('party', 'invoice', 'invoice__party')
            .order_by('-date')
        )

        # Group payments by mode
        payment_by_mode = self._group_payments_by_mode(payments)

        # Calculate total received
        total_received = sum(p.amount for p in payments)

        # Update context
        context.update({
            'payments': payments,
            'payment_by_mode': payment_by_mode,
            'total_received': total_received,
            'today': timezone.now().date(),
        })
        
        return context

    def _group_payments_by_mode(self, payments):
        """Group payments by payment mode with totals."""
        payment_by_mode = {}
        
        for payment in payments:
            mode_display = payment.get_mode_display()
            
            if mode_display not in payment_by_mode:
                payment_by_mode[mode_display] = {
                    'payments': [],
                    'total': Decimal('0.00'),
                    'count': 0
                }
            
            payment_by_mode[mode_display]['payments'].append(payment)
            payment_by_mode[mode_display]['total'] += payment.amount
            payment_by_mode[mode_display]['count'] += 1

        return payment_by_mode