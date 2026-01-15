# retailapp/views.py - PART 1 of 3
# COMPLETE FIXED VERSION - IMPORTS, DECORATORS & HELPER FUNCTIONS
# Copy this to start your views.py file

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

# Import Inventory Manager
from core.inventory_manager import (
    InventoryManager,
    check_stock_availability,
    check_stock_for_update,
    deduct_items_for_invoice,
    add_items_for_return,
    update_items_for_invoice,
    restore_items_for_invoice_deletion
)

logger = logging.getLogger(__name__)


# ================================================================
# DECORATORS
# ================================================================

def login_required_class(cls):
    """Decorator for class-based views to require login"""
    return method_decorator(login_required, name='dispatch')(cls)


# ================================================================
# HELPER FUNCTIONS - ALL FIXED
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
    
    active_invoices = RetailInvoice.objects.filter(is_active=True)
    
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
    
    if not quantity_str or not rate_str:
        return None
    
    quantity = safe_int(quantity_str, 0)
    rate = safe_decimal(rate_str, '0')
    
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


# ================================================================
# ITEM CACHE (SINGLE-PC SAFE)
# ================================================================

_item_cache = {}

def clear_item_cache():
    """Clear the item cache (call after invoice operations)"""
    global _item_cache
    _item_cache = {}


def get_item_object(item_id):
    """Get Item object by ID with caching to avoid repeated queries"""
    if not item_id:
        return None
    
    try:
        item_id = int(item_id)
        
        if item_id in _item_cache:
            return _item_cache[item_id]
        
        item = Item.objects.get(id=item_id, is_active=True, is_deleted=False)
        _item_cache[item_id] = item
        return item
        
    except (Item.DoesNotExist, ValueError, TypeError):
        _item_cache[item_id] = None
        return None


def get_available_items():
    """Get all available items for selection"""
    return Item.objects.filter(
        is_active=True,
        is_deleted=False
    ).order_by('name')


def prepare_items_for_inventory(post_data):
    """
    Prepare items list for inventory manager from POST data.
    Returns list of dicts with item_id and quantity for inventory operations.
    Only includes items linked to inventory (not manual items).
    """
    items_for_inventory = []
    item_indices = extract_item_indices(post_data)
    
    for idx in item_indices:
        item_data = parse_invoice_item_data(post_data, idx)
        if item_data and item_data['item_id']:
            try:
                item_id = int(item_data['item_id'])
                items_for_inventory.append({
                    'item_id': item_id,
                    'quantity': item_data['quantity']
                })
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid item_id format in POST data: {e}")
                continue
    
    return items_for_inventory

# retailapp/views.py - PART 2 of 3
# PDF GENERATION & MAIN CRUD VIEWS
# Append this after Part 1

# ================================================================
# PDF GENERATION
# ================================================================

def generate_retail_invoice_pdf(invoice):
    """Generate professional PDF for retail invoice"""
    try:
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
        
        elements.append(Paragraph("RETAIL INVOICE", title_style))
        elements.append(Spacer(1, 0.3 * inch))
        
        payment_status = invoice.get_payment_mode_display()
        invoice_date = invoice.date.strftime('%d %b %Y') if invoice.date else 'N/A'
        
        invoice_info = [
            ['Invoice No:', invoice.invoice_number or 'N/A', 'Date:', invoice_date],
            ['Payment:', payment_status, '', '']
        ]
        
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
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ff6b6b')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 1), (-1, num_items), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, num_items), 9),
            ('ALIGN', (2, 1), (-1, num_items), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, totals_start_row), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, totals_start_row), (-1, -1), 10),
            ('ALIGN', (0, totals_start_row), (-1, -1), 'RIGHT'),
            ('BACKGROUND', (0, totals_start_row), (-1, -2), colors.HexColor('#f8f9fa')),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#ff6b6b')),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.whitesmoke),
            ('FONTSIZE', (0, -1), (-1, -1), 12),
        ]
        
        if num_items > 0:
            table_style.append(('BACKGROUND', (0, 1), (-1, num_items), colors.beige))
            table_style.append(('GRID', (0, 0), (-1, num_items), 1, colors.grey))
        
        items_table.setStyle(TableStyle(table_style))
        elements.append(items_table)
        elements.append(Spacer(1, 0.3 * inch))
        
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
        
        if invoice.notes:
            elements.append(Paragraph("NOTES", heading_style))
            elements.append(Paragraph(str(invoice.notes), styles['Normal']))
            elements.append(Spacer(1, 0.3 * inch))
        
        footer_text = f"Generated on {datetime.now().strftime('%d %b %Y at %I:%M %p')}"
        elements.append(Paragraph(footer_text, right_align_style))
        elements.append(Paragraph("Thank you for your business!", styles['Normal']))
        
        doc.build(elements)
        buffer.seek(0)
        
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        
        invoice_num = (invoice.invoice_number or 'unknown').replace('/', '-').replace('\\', '-')
        customer = (invoice.customer_name or 'customer').replace(' ', '_').replace('/', '-')
        filename = f'Retail_Invoice_{invoice_num}_{customer}.pdf'
        
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Exception as e:
        logger.error(f"PDF generation failed for invoice {invoice.id}: {e}", exc_info=True)
        return HttpResponse(
            f"Error generating PDF: {str(e)}",
            status=500,
            content_type='text/plain'
        )


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
            'retail_returns',
            'retail_returns__item',
            'retail_returns__item__item'
        )
        
        search_query = self.request.GET.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(invoice_number__icontains=search_query) |
                Q(customer_name__icontains=search_query) |
                Q(customer_mobile__icontains=search_query)
            )
        
        status_filter = self.request.GET.get('status', '').strip()
        if status_filter == 'paid':
            queryset = queryset.exclude(payment_mode='UNPAID')
        elif status_filter == 'unpaid':
            queryset = queryset.filter(payment_mode='UNPAID')
        
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
    """View details of a single retail invoice with PDF download support"""
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
            'retail_returns__item__item'
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = self.object
        
        items = invoice.retail_items.filter(is_active=True).select_related('item')
        returns = invoice.retail_returns.filter(is_active=True).select_related('item__item')
        
        returns_total = sum(ret.amount for ret in returns)
        
        context['items'] = items
        context['returns'] = returns
        context['items_count'] = items.count()
        context['returns_count'] = returns.count()
        context['returns_total'] = returns_total
        context['quick_payment_form'] = RetailInvoiceQuickPaymentForm(instance=invoice)
        context['trigger_pdf_download'] = self.request.session.pop('download_invoice_pdf', None) == invoice.id
        context['is_fully_settled'] = invoice.final_amount <= 0 and invoice.is_paid
        context['is_no_amount_due'] = invoice.final_amount <= 0
        
        return context


# ================================================================
# INVOICE CREATE VIEW
# ================================================================

@login_required_class
class RetailInvoiceCreateView(View):
    """Create a new retail invoice with automatic inventory deduction"""
    template_name = 'retailapp/create_invoice.html'

    def get(self, request):
        form = RetailInvoiceForm()
        items = get_available_items()
        return render(request, self.template_name, {
            'form': form,
            'items': items,
        })

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
            item_indices = extract_item_indices(request.POST)
            if not item_indices:
                raise ValueError('Please add at least one item to the invoice.')

            parsed_items = []
            for idx in item_indices:
                item_data = parse_invoice_item_data(request.POST, idx)
                if item_data:
                    parsed_items.append(item_data)
            
            if not parsed_items:
                raise ValueError('No valid items found. Please check item details.')

            item_ids = [
                int(item['item_id']) 
                for item in parsed_items 
                if item.get('item_id')
            ]
            
            items_dict = {}
            if item_ids:
                items_qs = Item.objects.filter(
                    id__in=item_ids,
                    is_active=True,
                    is_deleted=False
                )
                items_dict = {item.id: item for item in items_qs}
            
            items_for_inventory = []
            stock_errors = []
            
            for item_data in parsed_items:
                if item_data.get('item_id'):
                    item_id = int(item_data['item_id'])
                    item_obj = items_dict.get(item_id)
                    
                    if not item_obj:
                        stock_errors.append(f"Item ID {item_id} not found or inactive")
                        continue
                    
                    if item_obj.quantity < item_data['quantity']:
                        stock_errors.append(
                            f"{item_obj.name} (HSN: {item_obj.hns_code}): "
                            f"Insufficient stock. Available: {item_obj.quantity}, "
                            f"Requested: {item_data['quantity']}"
                        )
                        continue
                    
                    items_for_inventory.append({
                        'item_id': item_id,
                        'quantity': item_data['quantity']
                    })
            
            if stock_errors:
                raise ValueError(" | ".join(stock_errors))
            
            with transaction.atomic():
                invoice = form.save(commit=False)
                invoice.created_by = request.user
                invoice.updated_by = request.user
                invoice.save()

                items_created = 0
                created_invoice_items = []

                for item_data in parsed_items:
                    item_obj = None
                    if item_data.get('item_id'):
                        item_obj = items_dict.get(int(item_data['item_id']))

                    invoice_item = RetailInvoiceItem.objects.create(
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

                    if item_obj:
                        created_invoice_items.append({
                            'item_id': item_obj.id,
                            'quantity': item_data['quantity'],
                            'invoice_item_id': invoice_item.id
                        })

                    items_created += 1

                if created_invoice_items:
                    logger.info(f"Deducting stock for {len(created_invoice_items)} tracked item(s)")
                    stock_result = deduct_items_for_invoice(
                        invoice_items=created_invoice_items,
                        invoice_type='retail',
                        invoice_id=invoice.id,
                        created_by=request.user
                    )

                    if not stock_result['success']:
                        raise Exception("Stock deduction failed: " + ", ".join(stock_result['errors']))

                invoice.refresh_from_db()

            clear_item_cache()
            
            payment_status = invoice.get_payment_mode_display()
            success_msg = (
                f'✅ Invoice {invoice.invoice_number} created successfully '
                f'with {items_created} item(s)! Payment Status: {payment_status}'
            )

            if created_invoice_items:
                success_msg += f' | Stock deducted for {len(created_invoice_items)} item(s).'

            messages.success(request, success_msg)

            if download_pdf:
                request.session['download_invoice_pdf'] = invoice.id
                request.session.modified = True

            return redirect('retailapp:invoice_detail', invoice_id=invoice.id)

        except ValueError as ve:
            logger.warning(f"Validation error creating retail invoice: {ve}")
            messages.error(request, f'❌ {str(ve)}')
            items = get_available_items()
            clear_item_cache()
            return render(request, self.template_name, {
                'form': form,
                'items': items,
            })
        
        except Exception as e:
            logger.error("Error creating retail invoice", exc_info=True)
            messages.error(request, f'❌ Error creating invoice: {str(e)}')
            items = get_available_items()
            clear_item_cache()
            return render(request, self.template_name, {
                'form': form,
                'items': items,
            })
            
# retailapp/views.py - PART 3 of 3
# UPDATE, DELETE, RETURN VIEWS & AJAX ENDPOINTS
# Append this after Part 2

# ================================================================
# INVOICE UPDATE VIEW
# ================================================================

@login_required_class
class RetailInvoiceUpdateView(View):
    """Update an existing retail invoice with automatic inventory adjustment"""
    template_name = 'retailapp/update_invoice.html'
    
    def get_invoice(self, invoice_id):
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
    
    def post(self, request, invoice_id):
        items = get_available_items()
        
        invoice = self.get_invoice(invoice_id)
        form = RetailInvoiceForm(request.POST, instance=invoice)
        
        if not form.is_valid():
            messages.error(request, 'Please correct the form errors.')
            invoice_items = invoice.retail_items.filter(is_active=True).select_related('item')
            return render(request, self.template_name, {
                'form': form,
                'invoice': invoice,
                'items': items,
                'invoice_items': invoice_items,
            })
        
        try:
            original_map = {}
            for item_obj in invoice.retail_items.filter(is_active=True).select_related('item'):
                if item_obj.item:
                    original_map[item_obj.item.id] = (
                        original_map.get(item_obj.item.id, 0) + item_obj.quantity
                    )

            original_items = [
                {'item_id': k, 'quantity': v} for k, v in original_map.items()
            ]

            item_indices = extract_item_indices(request.POST)
            updated_items_for_inventory = prepare_items_for_inventory(request.POST)
            
            if updated_items_for_inventory or original_items:
                logger.info(
                    f"Stock check: {len(original_items)} original, "
                    f"{len(updated_items_for_inventory)} updated tracked items"
                )
                
                stock_check = check_stock_for_update(
                    original_items=original_items if original_items else [],
                    updated_items=updated_items_for_inventory if updated_items_for_inventory else []
                )
                
                if not stock_check['available']:
                    for unavailable in stock_check['unavailable_items']:
                        messages.error(
                            request,
                            f"❌ {unavailable['name']} (HSN: {unavailable['hns_code']}): "
                            f"{unavailable['reason']}. Current stock: {unavailable['available']}, "
                            f"Additional needed: {unavailable['additional_needed']}"
                        )
                    
                    invoice_items = invoice.retail_items.filter(is_active=True).select_related('item')
                    return render(request, self.template_name, {
                        'form': form,
                        'invoice': invoice,
                        'items': items,
                        'invoice_items': invoice_items,
                    })
            
            with transaction.atomic():
                invoice = form.save(commit=False)
                invoice.updated_by = request.user
                invoice.save()
                
                invoice.retail_items.filter(is_active=True).update(is_active=False)
                
                items_created = 0
                new_invoice_items = []
                
                for idx in item_indices:
                    item_data = parse_invoice_item_data(request.POST, idx)
                    
                    if item_data is None:
                        continue
                    
                    item_obj = get_item_object(item_data['item_id'])
                    
                    invoice_item = RetailInvoiceItem.objects.create(
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
                    
                    if item_obj:
                        new_invoice_items.append({
                            'item_id': item_obj.id,
                            'quantity': item_data['quantity']
                        })
                    
                    items_created += 1
                
                if original_items or new_invoice_items:
                    stock_update_result = update_items_for_invoice(
                        original_items=original_items,
                        updated_items=new_invoice_items,
                        invoice_type='retail',
                        invoice_id=invoice.id,
                        created_by=request.user
                    )
                    
                    if not stock_update_result['success']:
                        logger.error(f"Stock update failed: {stock_update_result['errors']}")
                        for error in stock_update_result['errors']:
                            messages.error(request, f"⚠️ Inventory Error: {error}")
                        raise Exception("Stock adjustment failed: " + ", ".join(stock_update_result['errors']))
                    
                    logger.info(f"✅ Invoice {invoice.invoice_number} updated with stock adjustments")
            
            payment_status = invoice.get_payment_mode_display()
            success_msg = (
                f'✅ Invoice {invoice.invoice_number} updated successfully! '
                f'Payment Status: {payment_status}'
            )
            
            if original_items or new_invoice_items:
                success_msg += ' | Inventory adjusted automatically.'
            
            messages.success(request, success_msg)
            return redirect('retailapp:invoice_detail', invoice_id=invoice.id)
            
        except Exception as e:
            logger.error(f"Error updating retail invoice: {e}", exc_info=True)
            messages.error(request, f'❌ Error updating invoice: {str(e)}')
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
    """Soft delete a retail invoice and restore stock to inventory"""
    invoice = get_object_or_404(RetailInvoice, id=invoice_id, is_active=True)
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                items_to_restore = []
                for item_obj in invoice.retail_items.filter(is_active=True).select_related('item'):
                    if item_obj.item:
                        items_to_restore.append({
                            'item_id': item_obj.item.id,
                            'quantity': item_obj.quantity
                        })
                
                if items_to_restore:
                    restore_result = restore_items_for_invoice_deletion(
                        invoice_items=items_to_restore,
                        invoice_type='retail',
                        invoice_id=invoice.id,
                        created_by=request.user
                    )
                    
                    if not restore_result['success']:
                        logger.warning(f"Some items could not be restored: {restore_result['errors']}")
                    
                    logger.info(
                        f"✅ Invoice {invoice.invoice_number} deleted. "
                        f"Stock restored for {len(restore_result['items_processed'])} item(s)"
                    )
                
                invoice.is_active = False
                invoice.updated_by = request.user
                invoice.save(update_fields=['is_active', 'updated_by', 'updated_at'])
                
                success_msg = f'✅ Invoice {invoice.invoice_number} deleted successfully!'
                if items_to_restore:
                    success_msg += f' Stock restored for {len(items_to_restore)} item(s).'
                
                messages.success(request, success_msg)
                return redirect('retailapp:dashboard')
                
        except Exception as e:
            logger.error(f"Error deleting invoice: {e}", exc_info=True)
            messages.error(request, f'❌ Error deleting invoice: {str(e)}')
            return redirect('retailapp:invoice_detail', invoice_id=invoice.id)
    
    return render(request, 'retailapp/confirm_delete.html', {'invoice': invoice})


# ================================================================
# RETURN CREATE VIEW
# ================================================================

@login_required_class
class RetailReturnCreateView(View):
    """Create a return for a retail invoice with proper amount calculation"""
    template_name = 'retailapp/create_return.html'
    
    def get_invoice(self, invoice_id):
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
    
    # CRITICAL FIX: Replace the RetailReturnCreateView.post() method in views.py Part 3
    # This fixes the "RetailReturn has no invoice" error

    def post(self, request, invoice_id):
        invoice = self.get_invoice(invoice_id)
        
        # ✅ Create mutable copy of POST data
        post_data = request.POST.copy()
        item_id = post_data.get('item')
        quantity_str = post_data.get('quantity', '1')
        amount_str = post_data.get('amount', '0')
        
        try:
            quantity = int(quantity_str) if quantity_str else 1
        except (ValueError, TypeError):
            quantity = 1
        
        try:
            amount = Decimal(amount_str) if amount_str else Decimal('0')
        except (ValueError, TypeError):
            amount = Decimal('0')
        
        # Auto-calculate amount if item selected but amount is zero
        if item_id and (amount <= 0 or not amount_str or amount_str.strip() == ''):
            try:
                invoice_item = RetailInvoiceItem.objects.get(
                    id=int(item_id),
                    invoice=invoice,
                    is_active=True
                )
                
                if invoice_item.quantity > 0 and invoice_item.total:
                    per_unit_price = (invoice_item.total / invoice_item.quantity).quantize(Decimal('0.01'))
                    calculated_amount = (per_unit_price * quantity).quantize(Decimal('0.01'))
                    
                    post_data['amount'] = str(calculated_amount)
                    
                    logger.info(
                        f"✅ Auto-calculated return amount: "
                        f"Item: {invoice_item.display_name}, "
                        f"Per unit: ₹{per_unit_price}, "
                        f"Qty: {quantity}, "
                        f"Total: ₹{calculated_amount}"
                    )
            except Exception as e:
                logger.error(f"Error calculating return amount: {e}", exc_info=True)
        
        # ✅ FIX: Create form with modified data
        form = RetailReturnForm(post_data, request.FILES, invoice=invoice)
        
        # ✅ CRITICAL: Check validity WITHOUT triggering model validation
        # We manually validate to avoid the invoice access error
        if not form.is_bound:
            messages.error(request, 'Form data is invalid.')
            return render(request, self.template_name, {
                'form': form,
                'invoice': invoice,
            })
        
        # ✅ Manual field validation (bypass form.is_valid() which calls model.clean())
        errors = {}
        
        # Validate required fields
        if not post_data.get('return_date'):
            errors['return_date'] = ['Return date is required.']
        
        if not post_data.get('quantity') or int(post_data.get('quantity', 0)) <= 0:
            errors['quantity'] = ['Quantity must be at least 1.']
        
        if not post_data.get('amount') or Decimal(post_data.get('amount', '0')) <= 0:
            errors['amount'] = ['Return amount must be greater than zero.']
        
        # If there are validation errors, show them
        if errors:
            for field, error_list in errors.items():
                for error in error_list:
                    messages.error(request, f"{field.title()}: {error}")
            
            return render(request, self.template_name, {
                'form': form,
                'invoice': invoice,
            })
        
        try:
            with transaction.atomic():
                # ✅ Create instance WITHOUT calling form.save()
                # This avoids triggering model validation
                retail_return = RetailReturn()
                
                # ✅ Set fields from form data
                retail_return.invoice = invoice
                
                # Set item if provided
                if item_id:
                    try:
                        retail_return.item = RetailInvoiceItem.objects.get(
                            id=int(item_id),
                            invoice=invoice,
                            is_active=True
                        )
                    except RetailInvoiceItem.DoesNotExist:
                        raise ValueError(f"Selected invoice item not found")
                
                retail_return.return_date = post_data.get('return_date')
                retail_return.quantity = int(post_data.get('quantity', 1))
                retail_return.amount = Decimal(post_data.get('amount', '0'))
                retail_return.reason = post_data.get('reason', '').strip()
                
                # Handle image upload
                if 'image' in request.FILES:
                    retail_return.image = request.FILES['image']
                
                retail_return.created_by = request.user
                retail_return.updated_by = request.user
                
                # ✅ Validate amount
                if retail_return.amount <= 0:
                    raise ValueError("Return amount must be greater than zero")
                
                # ✅ Manual validation: Check return quantity
                if retail_return.item:
                    remaining_qty = (
                        retail_return.item.quantity -
                        RetailReturn.objects.filter(
                            item=retail_return.item,
                            is_active=True
                        ).aggregate(total=Sum('quantity'))['total'] or 0
                    )

                    if retail_return.quantity > remaining_qty:
                        raise ValueError(
                            f"Return quantity ({retail_return.quantity}) exceeds "
                            f"remaining invoice quantity ({remaining_qty})"
                        )
                
                # ✅ Save with skip_validation flag
                retail_return.save(skip_validation=True)
                
                logger.info(
                    f"✅ Return created: ID={retail_return.id}, "
                    f"Amount=₹{retail_return.amount}, "
                    f"Quantity={retail_return.quantity}"
                )
                
                # Restore stock if linked to inventory item
                if retail_return.item and retail_return.item.item:
                    try:
                        item_exists = Item.objects.filter(
                            id=retail_return.item.item.id,
                            is_active=True,
                            is_deleted=False
                        ).exists()
                        
                        if not item_exists:
                            logger.warning(
                                f"Cannot restore stock for return {retail_return.id}: "
                                f"Item {retail_return.item.item.id} not found or inactive"
                            )
                            messages.warning(
                                request,
                                f"⚠️ Item no longer exists in inventory. "
                                f"Return recorded but stock not restored."
                            )
                        else:
                            return_items = [{
                                'item_id': retail_return.item.item.id,
                                'quantity': retail_return.quantity,
                                'return_item_id': retail_return.id
                            }]
                            
                            stock_return_result = add_items_for_return(
                                return_items=return_items,
                                invoice_type='retail',
                                invoice_id=invoice.id,
                                return_id=retail_return.id,
                                created_by=request.user
                            )
                            
                            if not stock_return_result['success']:
                                logger.error(f"Stock return failed: {stock_return_result['errors']}")
                                raise Exception(
                                    "Stock restoration failed: " + 
                                    ", ".join(stock_return_result['errors'])
                                )
                            else:
                                logger.info(
                                    f"✅ Return processed for invoice {invoice.invoice_number}. "
                                    f"Stock returned: {retail_return.item.item.name} "
                                    f"x{retail_return.quantity}"
                                )
                    
                    except Exception as e:
                        logger.error(f"Error restoring stock for return: {e}", exc_info=True)
                        raise
            
            # Success
            success_msg = (
                f'✅ Return of ₹{retail_return.amount:,.2f} recorded successfully! '
                f'Quantity: {retail_return.quantity}'
            )
            
            if retail_return.item and retail_return.item.item:
                success_msg += f' | Stock restored: {retail_return.item.item.name}'
            
            messages.success(request, success_msg)
            return redirect('retailapp:invoice_detail', invoice_id=invoice.id)
            
        except ValueError as ve:
            logger.error(f"Validation error creating return: {ve}", exc_info=True)
            messages.error(request, f'❌ {str(ve)}')
            return render(request, self.template_name, {
                'form': form,
                'invoice': invoice,
            })
            
        except Exception as e:
            logger.error(f"Error creating return: {e}", exc_info=True)
            messages.error(request, f'❌ Error creating return: {str(e)}')
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
    """AJAX endpoint to get item details with stock information"""
    try:
        item_info = InventoryManager.get_item_stock_info(item_id)
        
        if not item_info['success']:
            return JsonResponse({
                'success': False,
                'error': item_info['error']
            }, status=404)
        
        return JsonResponse({
            'success': True,
            'id': item_info['item_id'],
            'name': item_info['name'],
            'retail_price': float(item_info['price_retail']),
            'wholesale_price': float(item_info['price_wholesale']),
            'gst_percent': float(item_info['gst_percent']),
            'current_stock': item_info['current_stock'],
            'is_low_stock': item_info['is_low_stock'],
            'is_out_of_stock': item_info['is_out_of_stock'],
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
        
        if quantity <= 0:
            quantity = Decimal('1')
        if rate < 0:
            rate = Decimal('0')
        if gst_percent < 0:
            gst_percent = Decimal('0')
        if discount_percent < 0:
            discount_percent = Decimal('0')
        
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
    """AJAX endpoint to toggle invoice payment status"""
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Invalid request method'
        }, status=405)
    
    try:
        invoice = get_object_or_404(RetailInvoice, id=invoice_id, is_active=True)
        
        if invoice.payment_mode == RetailInvoice.PaymentMode.UNPAID:
            invoice.payment_mode = RetailInvoice.PaymentMode.CASH
            invoice.transaction_reference = ''
            status_text = 'Paid (Cash)'
        else:
            invoice.payment_mode = RetailInvoice.PaymentMode.UNPAID
            invoice.transaction_reference = ''
            status_text = 'Unpaid'

        invoice.updated_by = request.user
        invoice.save()

        return JsonResponse({
            'success': True,
            'is_paid': invoice.is_paid,
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
    """AJAX endpoint to update payment mode with specific value"""
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Invalid request method'
        }, status=405)
    
    try:
        invoice = get_object_or_404(RetailInvoice, id=invoice_id, is_active=True)
        
        payment_mode = request.POST.get('payment_mode', '').strip()
        transaction_ref = request.POST.get('transaction_reference', '').strip()
        
        if payment_mode not in dict(RetailInvoice.PaymentMode.choices):
            return JsonResponse({
                'success': False,
                'error': 'Invalid payment mode'
            }, status=400)
        
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
            'gst_percent',
            'quantity'
        )[:20]
        
        results = [
            {
                'id': item['id'],
                'name': item['name'],
                'retail_price': float(item['price_retail'] or 0),
                'wholesale_price': float(item['price_wholesale'] or 0),
                'gst_percent': float(item['gst_percent'] or 0),
                'stock': item['quantity'],
                'is_low_stock': item['quantity'] <= 10,
                'is_out_of_stock': item['quantity'] == 0,
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


@login_required
def ajax_check_stock_availability(request):
    """AJAX endpoint to check stock availability for multiple items"""
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'Invalid request method'
        }, status=405)
    
    try:
        import json
        
        try:
            items_to_check = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=400)
        
        if not isinstance(items_to_check, list):
            return JsonResponse({
                'success': False,
                'error': 'Expected array of items'
            }, status=400)
        
        validated_items = []
        for item_data in items_to_check:
            item_id = item_data.get('item_id')
            quantity = item_data.get('quantity')
            
            if not item_id or not quantity:
                continue
            
            try:
                validated_items.append({
                    'item_id': int(item_id),
                    'quantity': int(quantity)
                })
            except (ValueError, TypeError):
                continue
        
        if not validated_items:
            return JsonResponse({
                'success': True,
                'available': True,
                'unavailable_items': [],
                'message': 'No items to check'
            })
        
        availability_result = check_stock_availability(validated_items)
        
        response_data = {
            'success': True,
            'available': availability_result['available'],
            'message': availability_result['message'],
            'unavailable_items': [
                {
                    'item_id': item['item_id'],
                    'name': item['name'],
                    'hns_code': item['hns_code'],
                    'available': item['available'],
                    'requested': item['requested'],
                    'reason': item['reason']
                }
                for item in availability_result['unavailable_items']
            ]
        }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Error checking stock availability: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Failed to check stock availability'
        }, status=500)


@login_required
def ajax_get_item_stock(request, item_id):
    """AJAX endpoint to get real-time stock information for a single item"""
    try:
        item_info = InventoryManager.get_item_stock_info(item_id)
        
        if not item_info['success']:
            return JsonResponse({
                'success': False,
                'error': item_info['error']
            }, status=404)
        
        return JsonResponse({
            'success': True,
            'item': {
                'id': item_info['item_id'],
                'name': item_info['name'],
                'hns_code': item_info['hns_code'],
                'current_stock': item_info['current_stock'],
                'is_active': item_info['is_active'],
                'is_low_stock': item_info['is_low_stock'],
                'is_out_of_stock': item_info['is_out_of_stock'],
                'price_retail': float(item_info['price_retail']),
                'price_wholesale': float(item_info['price_wholesale']),
                'gst_percent': float(item_info['gst_percent']),
                'discount': float(item_info['discount']),
            }
        })
        
    except Exception as e:
        logger.error(f"Error fetching item stock info: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Failed to fetch item stock information'
        }, status=500)


@login_required
def debug_invoice_stock_movements(request, invoice_id):
    """Debug view to see all stock movements related to an invoice"""
    if not request.user.is_staff:
        messages.error(request, 'Access denied')
        return redirect('retailapp:dashboard')
    
    try:
        from items.models import StockMovement
        
        invoice = get_object_or_404(RetailInvoice, id=invoice_id)
        
        movements = StockMovement.objects.filter(
            invoice_id=invoice_id,
            invoice_type='retail'
        ).select_related('item', 'created_by').order_by('-created_at')
        
        context = {
            'invoice': invoice,
            'movements': movements,
            'total_movements': movements.count(),
        }
        
        return render(request, 'retailapp/debug_stock_movements.html', context)
        
    except Exception as e:
        logger.error(f"Error fetching stock movements: {e}")
        messages.error(request, 'Error loading stock movements')
        return redirect('retailapp:invoice_detail', invoice_id=invoice_id)
    