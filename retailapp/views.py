# retailapp/views.py
from django.views import View
from django.views.generic import ListView, DetailView
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db.models import Sum, Count, Q
from decimal import Decimal, InvalidOperation
import logging

# PDF Generation
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from datetime import datetime, timedelta

from .models import RetailInvoice, RetailInvoiceItem, RetailReturn
from .forms import RetailInvoiceForm, RetailReturnForm, RetailInvoiceQuickPaymentForm
from items.models import Item

logger = logging.getLogger(__name__)


# ================================================================
# DECORATORS
# ================================================================

def login_required_class(cls):
    """Decorator for class-based views to require login"""
    return method_decorator(login_required, name='dispatch')(cls)


# ================================================================
# HELPER FUNCTIONS
# ================================================================

def safe_decimal(value, default='0'):
    """Safely convert value to Decimal"""
    try:
        if value is None or str(value).strip() == '':
            return Decimal(default)
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def safe_int(value, default=0):
    """Safely convert value to integer"""
    try:
        if value is None or str(value).strip() == '':
            return default
        return int(float(value))
    except (ValueError, TypeError):
        return default


def get_dashboard_stats():
    """Calculate dashboard statistics with optimized queries"""
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Base queryset
    active_invoices = RetailInvoice.objects.filter(is_active=True)
    
    # Aggregate all stats in fewer queries
    total_stats = active_invoices.aggregate(
        total_count=Count('id'),
        total_revenue=Sum('final_amount'),
        paid_count=Count('id', filter=~Q(payment_mode='UNPAID')),
        unpaid_count=Count('id', filter=Q(payment_mode='UNPAID')),
    )
    
    today_stats = active_invoices.filter(date=today).aggregate(
        today_count=Count('id'),
        today_revenue=Sum('final_amount'),
    )
    
    week_stats = active_invoices.filter(date__gte=week_ago).aggregate(
        week_count=Count('id'),
    )
    
    month_stats = active_invoices.filter(date__gte=month_ago).aggregate(
        month_revenue=Sum('final_amount'),
    )
    
    # Returns stats
    returns_stats = RetailReturn.objects.filter(is_active=True).aggregate(
        returns_count=Count('id'),
        returns_amount=Sum('amount'),
    )
    
    return {
        'total_invoices': total_stats['total_count'] or 0,
        'today_invoices': today_stats['today_count'] or 0,
        'week_invoices': week_stats['week_count'] or 0,
        'total_revenue': total_stats['total_revenue'] or Decimal('0.00'),
        'today_revenue': today_stats['today_revenue'] or Decimal('0.00'),
        'month_revenue': month_stats['month_revenue'] or Decimal('0.00'),
        'paid_invoices': total_stats['paid_count'] or 0,
        'unpaid_invoices': total_stats['unpaid_count'] or 0,
        'total_returns_count': returns_stats['returns_count'] or 0,
        'total_returns_amount': returns_stats['returns_amount'] or Decimal('0.00'),
    }


def extract_item_indices(post_data):
    """Extract unique item indices from POST data"""
    indices = set()
    for key in post_data.keys():
        if key.startswith('item_id_'):
            try:
                idx = key.split('_')[-1]
                if idx.isdigit():
                    indices.add(idx)
            except (IndexError, ValueError):
                continue
    return sorted(indices, key=lambda x: int(x))


def parse_invoice_item_data(post_data, idx):
    """Parse and validate invoice item data from POST"""
    item_id = post_data.get(f'item_id_{idx}', '').strip()
    manual_name = post_data.get(f'manual_item_name_{idx}', '').strip()
    quantity_str = post_data.get(f'quantity_{idx}', '').strip()
    rate_str = post_data.get(f'rate_{idx}', '').strip()
    gst_percent_str = post_data.get(f'gst_percent_{idx}', '0').strip()
    discount_percent_str = post_data.get(f'discount_percent_{idx}', '0').strip()
    
    # Validate required fields
    if not quantity_str or not rate_str:
        return None
    
    quantity = safe_int(quantity_str, 0)
    rate = safe_decimal(rate_str, '0')
    
    # Must have either item_id or manual_name
    if not item_id and not manual_name:
        return None
    
    if quantity <= 0 or rate <= 0:
        return None
    
    return {
        'item_id': item_id if item_id else None,
        'manual_name': manual_name,
        'quantity': quantity,
        'rate': rate,
        'gst_percent': safe_decimal(gst_percent_str, '0'),
        'discount_percent': safe_decimal(discount_percent_str, '0'),
    }


def get_item_object(item_id):
    """Get Item object by ID, return None if not found"""
    if not item_id:
        return None
    try:
        return Item.objects.get(id=int(item_id), is_active=True, is_deleted=False)
    except (Item.DoesNotExist, ValueError, TypeError):
        return None


def get_available_items():
    """Get all available items for selection"""
    return Item.objects.filter(
        is_active=True,
        is_deleted=False
    ).order_by('name')


# ================================================================
# PDF GENERATION
# ================================================================

def generate_retail_invoice_pdf(invoice):
    """Generate professional PDF for retail invoice"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch
    )
    elements = []
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=28,
        textColor=colors.HexColor('#ff6b6b'),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#ee5a6f'),
        spaceAfter=8,
        fontName='Helvetica-Bold'
    )
    
    right_align_style = ParagraphStyle(
        'RightAlign',
        parent=styles['Normal'],
        alignment=TA_RIGHT
    )
    
    # Title
    elements.append(Paragraph("RETAIL INVOICE", title_style))
    elements.append(Spacer(1, 0.3 * inch))
    
    # Invoice Info Table - Updated with payment mode
    payment_status = invoice.get_payment_mode_display()  # Shows "Unpaid", "Cash", "UPI", etc.
    invoice_date = invoice.date.strftime('%d %b %Y') if invoice.date else 'N/A'
    
    invoice_info = [
        ['Invoice No:', invoice.invoice_number or 'N/A', 'Date:', invoice_date],
        ['Payment:', payment_status, '', '']
    ]
    
    # Add transaction reference if available
    if invoice.transaction_reference:
        invoice_info.append(['Transaction Ref:', invoice.transaction_reference, '', ''])
    
    invoice_table = Table(invoice_info, colWidths=[1.5 * inch, 2.5 * inch, 1 * inch, 1.5 * inch])
    invoice_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#666666')),
        ('TEXTCOLOR', (2, 0), (2, -1), colors.HexColor('#666666')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(invoice_table)
    elements.append(Spacer(1, 0.3 * inch))
    
    # Customer Details
    elements.append(Paragraph("CUSTOMER DETAILS", heading_style))
    customer_data = [
        ['Customer Name:', invoice.customer_name or 'N/A'],
        ['Mobile:', invoice.customer_mobile or 'N/A'],
    ]
    
    customer_table = Table(customer_data, colWidths=[1.5 * inch, 5 * inch])
    customer_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#666666')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(customer_table)
    elements.append(Spacer(1, 0.3 * inch))
    
    # Items Table
    elements.append(Paragraph("ITEMS", heading_style))
    items_header = ['#', 'Item', 'Qty', 'Rate', 'GST', 'Discount', 'Total']
    items_data = [items_header]
    
    invoice_items = invoice.retail_items.filter(is_active=True).select_related('item')
    
    for idx, line_item in enumerate(invoice_items, 1):
        display_name = line_item.display_name or 'Unknown Item'
        if len(display_name) > 30:
            display_name = display_name[:27] + '...'
        
        items_data.append([
            str(idx),
            display_name,
            str(line_item.quantity),
            f'Rs {line_item.rate:,.2f}',
            f'Rs {line_item.gst_amount:,.2f}',
            f'Rs {line_item.discount_amount:,.2f}',
            f'Rs {line_item.total:,.2f}'
        ])
    
    # Add totals rows
    items_data.extend([
        ['', '', '', '', '', 'SUBTOTAL:', f'Rs {invoice.base_amount:,.2f}'],
        ['', '', '', '', '', 'GST:', f'Rs {invoice.total_gst:,.2f}'],
        ['', '', '', '', '', 'DISCOUNT:', f'Rs {invoice.total_discount:,.2f}'],
        ['', '', '', '', '', 'TOTAL:', f'Rs {invoice.final_amount:,.2f}'],
    ])
    
    col_widths = [0.4 * inch, 2.3 * inch, 0.6 * inch, 0.9 * inch, 0.9 * inch, 0.9 * inch, 1 * inch]
    items_table = Table(items_data, colWidths=col_widths)
    
    num_items = len(invoice_items)
    totals_start_row = num_items + 1
    
    table_style = [
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ff6b6b')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        
        # Body
        ('FONTNAME', (0, 1), (-1, num_items), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, num_items), 9),
        ('ALIGN', (2, 1), (-1, num_items), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        
        # Totals styling
        ('FONTNAME', (0, totals_start_row), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, totals_start_row), (-1, -1), 10),
        ('ALIGN', (0, totals_start_row), (-1, -1), 'RIGHT'),
        ('BACKGROUND', (0, totals_start_row), (-1, -2), colors.HexColor('#f8f9fa')),
        
        # Final total highlight
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#ff6b6b')),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.whitesmoke),
        ('FONTSIZE', (0, -1), (-1, -1), 12),
    ]
    
    # Add grid only if there are items
    if num_items > 0:
        table_style.append(('BACKGROUND', (0, 1), (-1, num_items), colors.beige))
        table_style.append(('GRID', (0, 0), (-1, num_items), 1, colors.grey))
    
    items_table.setStyle(TableStyle(table_style))
    elements.append(items_table)
    elements.append(Spacer(1, 0.3 * inch))
    
    # Returns (if any)
    returns_qs = invoice.retail_returns.filter(is_active=True)
    if returns_qs.exists():
        elements.append(Paragraph("RETURNS", heading_style))
        returns_data = [['Date', 'Quantity', 'Amount', 'Reason']]
        
        for ret in returns_qs:
            return_date = ret.return_date.strftime('%d %b %Y') if ret.return_date else 'N/A'
            reason = ret.reason or 'N/A'
            if len(reason) > 30:
                reason = reason[:27] + '...'
            
            returns_data.append([
                return_date,
                str(ret.quantity),
                f'Rs {ret.amount:,.2f}',
                reason
            ])
        
        returns_table = Table(returns_data, colWidths=[1.5 * inch, 1 * inch, 1.5 * inch, 2.5 * inch])
        returns_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ffc107')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(returns_table)
        elements.append(Spacer(1, 0.3 * inch))
    
    # Notes
    if invoice.notes:
        elements.append(Paragraph("NOTES", heading_style))
        elements.append(Paragraph(str(invoice.notes), styles['Normal']))
        elements.append(Spacer(1, 0.3 * inch))
    
    # Footer
    footer_text = f"Generated on {datetime.now().strftime('%d %b %Y at %I:%M %p')}"
    elements.append(Paragraph(footer_text, right_align_style))
    elements.append(Paragraph("Thank you for your business!", styles['Normal']))
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    # Prepare response
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    
    # Clean filename
    invoice_num = (invoice.invoice_number or 'unknown').replace('/', '-').replace('\\', '-')
    customer = (invoice.customer_name or 'customer').replace(' ', '_').replace('/', '-')
    filename = f'Retail_Invoice_{invoice_num}_{customer}.pdf'
    
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


# ================================================================
# DASHBOARD VIEW
# ================================================================

@login_required_class
class RetailDashboardView(ListView):
    """Dashboard showing all retail invoices with statistics"""
    model = RetailInvoice
    template_name = 'retailapp/dashboard.html'
    context_object_name = 'invoices'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = RetailInvoice.objects.filter(
            is_active=True
        ).select_related(
            'created_by'
        ).prefetch_related(
            'retail_items',
            'retail_returns'
        )
        
        # Search functionality
        search_query = self.request.GET.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(invoice_number__icontains=search_query) |
                Q(customer_name__icontains=search_query) |
                Q(customer_mobile__icontains=search_query)
            )
        
        # Filter by payment status - Updated for payment_mode
        status_filter = self.request.GET.get('status', '').strip()
        if status_filter == 'paid':
            queryset = queryset.exclude(payment_mode='UNPAID')
        elif status_filter == 'unpaid':
            queryset = queryset.filter(payment_mode='UNPAID')
        
        # Filter by date range
        date_from = self.request.GET.get('date_from', '').strip()
        date_to = self.request.GET.get('date_to', '').strip()
        
        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)
        
        return queryset.order_by('-date', '-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['stats'] = get_dashboard_stats()
        context['search_query'] = self.request.GET.get('search', '')
        context['status_filter'] = self.request.GET.get('status', '')
        context['date_from'] = self.request.GET.get('date_from', '')
        context['date_to'] = self.request.GET.get('date_to', '')
        return context


# ================================================================
# INVOICE DETAIL VIEW
# ================================================================

@login_required_class
class RetailInvoiceDetailView(DetailView):
    """View details of a single retail invoice"""
    model = RetailInvoice
    template_name = 'retailapp/invoice_detail.html'
    context_object_name = 'invoice'
    pk_url_kwarg = 'invoice_id'
    
    def get_queryset(self):
        return RetailInvoice.objects.filter(
            is_active=True
        ).select_related(
            'created_by',
            'updated_by'
        ).prefetch_related(
            'retail_items__item',
            'retail_returns'
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = self.object
        
        # Use 'items' to match template
        items = invoice.retail_items.filter(is_active=True).select_related('item')
        returns = invoice.retail_returns.filter(is_active=True)
        
        context['items'] = items
        context['returns'] = returns
        context['items_count'] = items.count()
        context['returns_count'] = returns.count()
        
        # Add quick payment form for easy status updates
        context['quick_payment_form'] = RetailInvoiceQuickPaymentForm(instance=invoice)
        
        return context


# ================================================================
# INVOICE CREATE VIEW
# ================================================================

@login_required_class
class RetailInvoiceCreateView(View):
    """Create a new retail invoice"""
    template_name = 'retailapp/create_invoice.html'
    
    def get(self, request):
        form = RetailInvoiceForm()
        items = get_available_items()
        
        context = {
            'form': form,
            'items': items,
        }
        return render(request, self.template_name, context)
    
    @transaction.atomic
    def post(self, request):
        form = RetailInvoiceForm(request.POST)
        download_pdf = request.POST.get('download_pdf') == 'on'
        
        if not form.is_valid():
            messages.error(request, 'Please correct the form errors.')
            items = get_available_items()
            return render(request, self.template_name, {
                'form': form,
                'items': items,
            })
        
        try:
            # Create invoice
            invoice = form.save(commit=False)
            invoice.created_by = request.user
            invoice.updated_by = request.user
            invoice.save()
            
            # Process invoice items from POST data
            item_indices = extract_item_indices(request.POST)
            
            if not item_indices:
                messages.error(request, 'Please add at least one item to the invoice.')
                invoice.delete()
                items = get_available_items()
                return render(request, self.template_name, {
                    'form': form,
                    'items': items,
                })
            
            # Create invoice items (signals will handle recalculation)
            items_created = 0
            for idx in item_indices:
                item_data = parse_invoice_item_data(request.POST, idx)
                
                if item_data is None:
                    continue
                
                item_obj = get_item_object(item_data['item_id'])
                
                # Create the invoice item - model's save() handles calculations
                RetailInvoiceItem.objects.create(
                    invoice=invoice,
                    item=item_obj,
                    manual_item_name=item_data['manual_name'] if not item_obj else '',
                    quantity=item_data['quantity'],
                    rate=item_data['rate'],
                    gst_percent=item_data['gst_percent'],
                    discount_percent=item_data['discount_percent'],
                    created_by=request.user,
                    updated_by=request.user
                )
                items_created += 1
            
            if items_created == 0:
                messages.error(request, 'No valid items were added. Please check item details.')
                invoice.delete()
                items = get_available_items()
                return render(request, self.template_name, {
                    'form': form,
                    'items': items,
                })
            
            # Refresh invoice from DB to get updated totals
            invoice.refresh_from_db()
            
            # Success message with payment status
            payment_status = invoice.get_payment_mode_display()
            messages.success(
                request,
                f'Invoice {invoice.invoice_number} created successfully with {items_created} item(s)! Payment Status: {payment_status}'
            )
            
            # Handle PDF download
            if download_pdf:
                return generate_retail_invoice_pdf(invoice)
            
            return redirect('retailapp:invoice_detail', invoice_id=invoice.id)
            
        except Exception as e:
            logger.error(f"Error creating retail invoice: {e}", exc_info=True)
            messages.error(request, f'Error creating invoice: {str(e)}')
            items = get_available_items()
            return render(request, self.template_name, {
                'form': form,
                'items': items,
            })


# ================================================================
# INVOICE UPDATE VIEW
# ================================================================

@login_required_class
class RetailInvoiceUpdateView(View):
    """Update an existing retail invoice"""
    template_name = 'retailapp/update_invoice.html'
    
    def get_invoice(self, invoice_id):
        """Get invoice or 404"""
        return get_object_or_404(
            RetailInvoice.objects.select_related('created_by', 'updated_by'),
            id=invoice_id,
            is_active=True
        )
    
    def get(self, request, invoice_id):
        invoice = self.get_invoice(invoice_id)
        form = RetailInvoiceForm(instance=invoice)
        items = get_available_items()
        invoice_items = invoice.retail_items.filter(is_active=True).select_related('item')
        
        context = {
            'form': form,
            'invoice': invoice,
            'items': items,
            'invoice_items': invoice_items,
        }
        return render(request, self.template_name, context)
    
    @transaction.atomic
    def post(self, request, invoice_id):
        invoice = self.get_invoice(invoice_id)
        form = RetailInvoiceForm(request.POST, instance=invoice)
        
        if not form.is_valid():
            messages.error(request, 'Please correct the form errors.')
            items = get_available_items()
            invoice_items = invoice.retail_items.filter(is_active=True).select_related('item')
            return render(request, self.template_name, {
                'form': form,
                'invoice': invoice,
                'items': items,
                'invoice_items': invoice_items,
            })
        
        try:
            # Update invoice
            invoice = form.save(commit=False)
            invoice.updated_by = request.user
            invoice.save()
            
            # Mark all existing items as inactive (soft delete)
            invoice.retail_items.filter(is_active=True).update(is_active=False)
            
            # Process updated items
            item_indices = extract_item_indices(request.POST)
            
            # Create new invoice items
            items_created = 0
            for idx in item_indices:
                item_data = parse_invoice_item_data(request.POST, idx)
                
                if item_data is None:
                    continue
                
                item_obj = get_item_object(item_data['item_id'])
                
                RetailInvoiceItem.objects.create(
                    invoice=invoice,
                    item=item_obj,
                    manual_item_name=item_data['manual_name'] if not item_obj else '',
                    quantity=item_data['quantity'],
                    rate=item_data['rate'],
                    gst_percent=item_data['gst_percent'],
                    discount_percent=item_data['discount_percent'],
                    created_by=request.user,
                    updated_by=request.user,
                    is_active=True
                )
                items_created += 1
            
            # Force recalculate totals
            invoice.recalculate_totals()
            
            payment_status = invoice.get_payment_mode_display()
            messages.success(
                request,
                f'Invoice {invoice.invoice_number} updated successfully! Payment Status: {payment_status}'
            )
            return redirect('retailapp:invoice_detail', invoice_id=invoice.id)
            
        except Exception as e:
            logger.error(f"Error updating retail invoice: {e}", exc_info=True)
            messages.error(request, f'Error updating invoice: {str(e)}')
            items = get_available_items()
            invoice_items = invoice.retail_items.filter(is_active=True).select_related('item')
            return render(request, self.template_name, {
                'form': form,
                'invoice': invoice,
                'items': items,
                'invoice_items': invoice_items,
            })


# ================================================================
# INVOICE DELETE VIEW
# ================================================================

@login_required
def retail_invoice_delete(request, invoice_id):
    """Soft delete a retail invoice"""
    invoice = get_object_or_404(RetailInvoice, id=invoice_id, is_active=True)
    
    if request.method == 'POST':
        invoice.is_active = False
        invoice.updated_by = request.user
        invoice.save(update_fields=['is_active', 'updated_by', 'updated_at'])
        
        messages.success(request, f'Invoice {invoice.invoice_number} deleted successfully!')
        return redirect('retailapp:dashboard')
    
    return render(request, 'retailapp/confirm_delete.html', {'invoice': invoice})


# ================================================================
# RETURN CREATE VIEW
# ================================================================

@login_required_class
class RetailReturnCreateView(View):
    """Create a return for a retail invoice"""
    template_name = 'retailapp/create_return.html'
    
    def get_invoice(self, invoice_id):
        """Get invoice or 404"""
        return get_object_or_404(
            RetailInvoice.objects.prefetch_related('retail_items__item'),
            id=invoice_id,
            is_active=True
        )
    
    def get(self, request, invoice_id):
        invoice = self.get_invoice(invoice_id)
        form = RetailReturnForm(invoice=invoice)
        
        context = {
            'form': form,
            'invoice': invoice,
        }
        return render(request, self.template_name, context)
    
    @transaction.atomic
    def post(self, request, invoice_id):
        invoice = self.get_invoice(invoice_id)
        form = RetailReturnForm(request.POST, request.FILES, invoice=invoice)
        
        if not form.is_valid():
            messages.error(request, 'Please correct the form errors.')
            return render(request, self.template_name, {
                'form': form,
                'invoice': invoice,
            })
        
        try:
            retail_return = form.save(commit=False)
            retail_return.invoice = invoice
            retail_return.created_by = request.user
            retail_return.updated_by = request.user
            retail_return.save()  # Model save handles amount calculation, signal handles invoice recalc
            
            messages.success(
                request,
                f'Return of ₹{retail_return.amount:,.2f} recorded successfully!'
            )
            return redirect('retailapp:invoice_detail', invoice_id=invoice.id)
            
        except Exception as e:
            logger.error(f"Error creating return: {e}", exc_info=True)
            messages.error(request, f'Error creating return: {str(e)}')
            return render(request, self.template_name, {
                'form': form,
                'invoice': invoice,
            })


# ================================================================
# PDF DOWNLOAD VIEW
# ================================================================

@login_required
def retail_invoice_pdf(request, invoice_id):
    """Generate and download PDF for retail invoice"""
    invoice = get_object_or_404(
        RetailInvoice.objects.prefetch_related(
            'retail_items__item',
            'retail_returns'
        ),
        id=invoice_id,
        is_active=True
    )
    return generate_retail_invoice_pdf(invoice)


# ================================================================
# AJAX ENDPOINTS
# ================================================================

@login_required
def ajax_get_item_details(request, item_id):
    """AJAX endpoint to get item details"""
    try:
        item = get_object_or_404(
            Item,
            id=item_id,
            is_active=True,
            is_deleted=False
        )
        
        return JsonResponse({
            'success': True,
            'id': item.id,
            'name': item.name,
            'retail_price': float(item.price_retail or 0),
            'wholesale_price': float(item.price_wholesale or 0),
            'gst_percent': float(item.gst_percent or 0),
        })
        
    except Exception as e:
        logger.error(f"Error fetching item details: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Item not found'
        }, status=404)


@login_required
def ajax_calculate_item_total(request):
    """AJAX endpoint to calculate item total"""
    try:
        quantity = safe_decimal(request.GET.get('quantity', '1'), '1')
        rate = safe_decimal(request.GET.get('rate', '0'), '0')
        gst_percent = safe_decimal(request.GET.get('gst_percent', '0'), '0')
        discount_percent = safe_decimal(request.GET.get('discount_percent', '0'), '0')
        
        # Validate inputs
        if quantity <= 0:
            quantity = Decimal('1')
        if rate < 0:
            rate = Decimal('0')
        if gst_percent < 0:
            gst_percent = Decimal('0')
        if discount_percent < 0:
            discount_percent = Decimal('0')
        
        # Calculate amounts (same logic as model)
        base_amount = (quantity * rate).quantize(Decimal('0.01'))
        gst_amount = (quantity * rate * gst_percent / Decimal('100')).quantize(Decimal('0.01'))
        discount_amount = (quantity * rate * discount_percent / Decimal('100')).quantize(Decimal('0.01'))
        total = (base_amount + gst_amount - discount_amount).quantize(Decimal('0.01'))
        
        return JsonResponse({
            'success': True,
            'base_amount': float(base_amount),
            'gst_amount': float(gst_amount),
            'discount_amount': float(discount_amount),
            'total': float(total),
        })
        
    except Exception as e:
        logger.error(f"Error calculating item total: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Calculation error'
        }, status=400)


@login_required
def ajax_toggle_payment_status(request, invoice_id):
    """
    AJAX endpoint to toggle invoice payment status.
    Updated to work with payment_mode instead of is_paid boolean.
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Invalid request method'
        }, status=405)
    
    try:
        invoice = get_object_or_404(RetailInvoice, id=invoice_id, is_active=True)
        
        # Toggle logic: if UNPAID, set to CASH; if paid (any other mode), set to UNPAID
        if invoice.payment_mode == RetailInvoice.PaymentMode.UNPAID:
            # Mark as paid with default CASH
            invoice.payment_mode = RetailInvoice.PaymentMode.CASH
            status_text = 'Paid (Cash)'
        else:
            # Mark as unpaid
            invoice.payment_mode = RetailInvoice.PaymentMode.UNPAID
            status_text = 'Unpaid'
        
        invoice.updated_by = request.user
        invoice.save()
        
        return JsonResponse({
            'success': True,
            'is_paid': invoice.is_paid,  # This uses the @property
            'payment_mode': invoice.payment_mode,
            'status_text': status_text,
            'message': f'Invoice marked as {status_text}'
        })
        
    except Exception as e:
        logger.error(f"Error toggling payment status: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to update payment status'
        }, status=500)


@login_required
def ajax_update_payment_mode(request, invoice_id):
    """
    NEW AJAX endpoint to update payment mode with specific value.
    Allows changing to any payment mode (UNPAID, CASH, UPI, etc.)
    """
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Invalid request method'
        }, status=405)
    
    try:
        invoice = get_object_or_404(RetailInvoice, id=invoice_id, is_active=True)
        
        # Get payment mode from POST data
        payment_mode = request.POST.get('payment_mode', '').strip()
        transaction_ref = request.POST.get('transaction_reference', '').strip()
        
        # Validate payment mode
        if payment_mode not in dict(RetailInvoice.PaymentMode.choices):
            return JsonResponse({
                'success': False,
                'error': 'Invalid payment mode'
            }, status=400)
        
        # Update payment mode
        invoice.payment_mode = payment_mode
        if transaction_ref:
            invoice.transaction_reference = transaction_ref
        elif payment_mode == RetailInvoice.PaymentMode.UNPAID:
            invoice.transaction_reference = ''
        
        invoice.updated_by = request.user
        invoice.save()
        
        return JsonResponse({
            'success': True,
            'is_paid': invoice.is_paid,
            'payment_mode': invoice.payment_mode,
            'payment_mode_display': invoice.get_payment_mode_display(),
            'transaction_reference': invoice.transaction_reference or '',
            'message': f'Payment mode updated to {invoice.get_payment_mode_display()}'
        })
        
    except Exception as e:
        logger.error(f"Error updating payment mode: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to update payment mode'
        }, status=500)


@login_required
def ajax_search_items(request):
    """AJAX endpoint to search items by name"""
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return JsonResponse({
            'success': True,
            'results': []
        })
    
    try:
        items_qs = Item.objects.filter(
            is_active=True,
            is_deleted=False
        ).filter(
            Q(name__icontains=query)
        ).values(
            'id',
            'name',
            'price_retail',
            'price_wholesale',
            'gst_percent'
        )[:20]
        
        results = [
            {
                'id': item['id'],
                'name': item['name'],
                'retail_price': float(item['price_retail'] or 0),
                'wholesale_price': float(item['price_wholesale'] or 0),
                'gst_percent': float(item['gst_percent'] or 0),
            }
            for item in items_qs
        ]
        
        return JsonResponse({
            'success': True,
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Error searching items: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Search failed'
        }, status=500)