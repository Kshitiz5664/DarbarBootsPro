# wholesale/views.py
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum, Count
from django.utils import timezone
from datetime import timedelta

from party.models import Party
from billing.models import Invoice, Payment, InvoiceItem
from items.models import Item


# ===========================
#  DASHBOARD HOME VIEW
# ===========================
from django.views.generic import TemplateView
from django.utils import timezone
from django.db.models import Sum, Count, F, DecimalField, ExpressionWrapper
from django.contrib.auth.mixins import LoginRequiredMixin
from decimal import Decimal

from billing.models import Invoice, Payment
from party.models import Party


class DashboardHomeView(LoginRequiredMixin, TemplateView):
    template_name = 'wholesale/dashboard_home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()
        last_30_days = today - timezone.timedelta(days=30)

        # Annotate total_amount for each invoice: base_amount - returns
        invoices = (
            Invoice.objects.annotate(
                total_return_sum=Sum('returns__amount', default=Decimal('0.00'))
            )
            .annotate(
                total_amount=ExpressionWrapper(
                    F('base_amount') - F('total_return_sum'),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )
        )

        # Core KPIs
        total_parties = Party.objects.count()
        total_invoices = invoices.count()
        total_open = invoices.filter(is_paid=False).count()
        total_closed = invoices.filter(is_paid=True).count()
        total_invoiced = invoices.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        total_received = Payment.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        total_pending = total_invoiced - total_received

        # Recent activity (last 30 days)
        recent_invoices = invoices.filter(date__gte=last_30_days).aggregate(
            total=Sum('total_amount'), count=Count('id')
        )
        recent_payments = Payment.objects.filter(date__gte=last_30_days).aggregate(
            total=Sum('amount'), count=Count('id')
        )

        # Top parties by pending amount (sorted in Python for now)
        top_pending_parties = sorted(
            (
                {
                    'party': p,
                    'pending': p.pending_amount,
                    'total_invoiced': p.total_invoiced,
                    'total_paid': p.total_paid,
                }
                for p in Party.objects.all()
                if getattr(p, 'pending_amount', 0) > 0
            ),
            key=lambda x: x['pending'],
            reverse=True
        )[:10]

        # Lists for quick display
        recent_invoice_list = invoices.select_related('party').order_by('-date')[:10]
        recent_payment_list = Payment.objects.select_related('party', 'invoice').order_by('-date')[:10]

        # Payment mode distribution
        payment_modes = Payment.objects.values('mode').annotate(
            total=Sum('amount'), count=Count('id')
        ).order_by('-total')

        # Context update
        context.update({
            'kpi': {
                'total_parties': total_parties,
                'total_invoices': total_invoices,
                'total_open_invoices': total_open,
                'total_closed_invoices': total_closed,
                'total_invoiced': total_invoiced,
                'total_received': total_received,
                'total_pending': total_pending,
                'recent_invoices_total': recent_invoices['total'] or 0,
                'recent_invoices_count': recent_invoices['count'] or 0,
                'recent_payments_total': recent_payments['total'] or 0,
                'recent_payments_count': recent_payments['count'] or 0,
            },
            'top_pending_parties': top_pending_parties,
            'recent_invoices': recent_invoice_list,
            'recent_payments': recent_payment_list,
            'payment_modes': payment_modes,
            'today': today,
        })
        return context


# ===========================
#  ANALYTICS REPORT VIEW
# ===========================
class AnalyticsReportView(LoginRequiredMixin, TemplateView):
    template_name = 'wholesale/analytics_report.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()

        # Annotate invoices with total_amount = base_amount - total_returns
        invoices = (
            Invoice.objects.annotate(
                total_return_sum=Sum('returns__amount', default=Decimal('0.00'))
            )
            .annotate(
                total_amount=ExpressionWrapper(
                    F('base_amount') - F('total_return_sum'),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )
        )

        # 1️⃣ Monthly Analytics (last 12 months)
        monthly_data = []
        for i in range(11, -1, -1):  # Reverse loop for proper chronological order
            month_start = (today.replace(day=1) - timedelta(days=30 * i)).replace(day=1)
            next_month = (month_start.replace(day=28) + timedelta(days=4))
            month_end = next_month - timedelta(days=next_month.day)

            month_invoices = invoices.filter(date__range=[month_start, month_end])
            month_payments = Payment.objects.filter(date__range=[month_start, month_end])

            monthly_data.append({
                'month': month_start.strftime('%B %Y'),
                'invoiced': month_invoices.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00'),
                'received': month_payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
                'invoice_count': month_invoices.count(),
                'payment_count': month_payments.count(),
            })

        # 2️⃣ Party Summary (sorted by pending amount)
        party_summary = sorted(
            (
                {
                    'party': p,
                    'total_invoiced': getattr(p, 'total_invoiced', Decimal('0.00')),
                    'total_paid': getattr(p, 'total_paid', Decimal('0.00')),
                    'pending': getattr(p, 'pending_amount', Decimal('0.00')),
                    'invoice_count': p.invoices.count(),
                    'payment_count': p.payments.count(),
                }
                for p in Party.objects.all()
            ),
            key=lambda x: x['pending'],
            reverse=True
        )

        # 3️⃣ Item-wise Sales Analysis
        item_sales = (
            InvoiceItem.objects.values('item__id', 'item__name')
            .annotate(
                total_quantity=Sum('quantity'),
                total_amount=Sum('total')
            )
            .filter(total_quantity__gt=0)
            .order_by('-total_amount')[:20]
        )

        # Final Context
        context.update({
            'monthly_data': monthly_data,
            'party_summary': party_summary,
            'item_sales': item_sales,
            'today': today,
        })
        return context


# ===========================
#  PENDING INVOICES REPORT
# ===========================
class PendingInvoicesReportView(LoginRequiredMixin, TemplateView):
    template_name = 'wholesale/pending_invoices_report.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pending_invoices = Invoice.objects.filter(is_paid=False).select_related('party').prefetch_related('payments')

        invoice_details = [
            {
                'invoice': inv,
                'paid': inv.total_paid,
                'balance': inv.balance_due,
                'days_pending': (timezone.now().date() - inv.date).days,
            }
            for inv in pending_invoices
        ]
        invoice_details.sort(key=lambda x: x['days_pending'], reverse=True)

        total_pending = sum(i['balance'] for i in invoice_details)
        context.update({
            'invoice_details': invoice_details,
            'total_pending_amount': total_pending,
            'total_count': len(invoice_details),
        })
        return context


# ===========================
#  PAYMENT HISTORY REPORT
# ===========================
class PaymentHistoryReportView(LoginRequiredMixin, TemplateView):
    template_name = 'wholesale/payment_history_report.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payments = Payment.objects.select_related('party', 'invoice').order_by('-date')

        payment_by_mode = {}
        for p in payments:
            mode_display = p.get_mode_display()
            payment_by_mode.setdefault(mode_display, {'payments': [], 'total': 0, 'count': 0})
            payment_by_mode[mode_display]['payments'].append(p)
            payment_by_mode[mode_display]['total'] += p.amount
            payment_by_mode[mode_display]['count'] += 1

        context.update({
            'payments': payments,
            'payment_by_mode': payment_by_mode,
            'total_received': sum(p.amount for p in payments),
        })
        return context
