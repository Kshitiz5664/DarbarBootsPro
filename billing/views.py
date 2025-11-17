from django.views import View
from django.views.generic import ListView, DetailView
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db.models import Sum
from decimal import Decimal, ROUND_HALF_UP
import logging
import json
import time

# PDF Generation
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from datetime import datetime

from .models import (
    Invoice, InvoiceItem, Payment, Return, Challan, ChallanItem, Balance
)
from .forms import (
    InvoiceForm, InvoiceItemFormSet, PaymentForm,
    ReturnForm, ChallanForm, ChallanItemFormSet, BalanceFormSet
)
from party.models import Party
from party.utils import send_payment_receipt
from items.models import Item


logger = logging.getLogger(__name__)


# ================================================================
# HELPER FUNCTIONS
# ================================================================

def calculate_item_totals(quantity, rate, gst_percent, discount_amount=0):
    """
    Calculate item totals with proper GST calculation
    GST is calculated on: (quantity * rate * GST%) - discount is applied after
    """
    quantity = Decimal(str(quantity))
    rate = Decimal(str(rate))
    gst_percent = Decimal(str(gst_percent))
    discount_amount = Decimal(str(discount_amount))
    
    base_amount = (quantity * rate).quantize(Decimal('0.01'), ROUND_HALF_UP)
    gst_amount = (base_amount * gst_percent / Decimal('100')).quantize(Decimal('0.01'), ROUND_HALF_UP)
    total = (base_amount + gst_amount - discount_amount).quantize(Decimal('0.01'), ROUND_HALF_UP)
    
    return {
        'base_amount': base_amount,
        'gst_amount': gst_amount,
        'discount_amount': discount_amount,
        'total': total
    }


def check_and_close_invoice(invoice):
    """Check if invoice should be closed based on payments and returns"""
    total_amount = invoice.total_amount or Decimal('0.00')
    total_paid = invoice.total_paid or Decimal('0.00')
    total_returns = sum(r.amount for r in invoice.returns.all()) if hasattr(invoice, 'returns') else Decimal('0.00')
    
    balance = total_amount - total_paid - total_returns
    
    if balance <= Decimal('0.00'):
        invoice.is_paid = True
        invoice.save(update_fields=['is_paid'])
        logger.info(f"✅ Invoice {invoice.invoice_number} automatically closed. Balance: {balance}")
        return True
    return False


def login_required_cbv(view):
    """Decorator for class-based views"""
    return method_decorator(login_required, name='dispatch')(view)


# ================================================================
# PDF GENERATION FUNCTIONS
# ================================================================

def generate_invoice_pdf(invoice):
    """Generate professional PDF invoice"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=28,
        textColor=colors.HexColor('#00c2ff'),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#0099cc'),
        spaceAfter=8,
        fontName='Helvetica-Bold'
    )
    
    right_align_style = ParagraphStyle('RightAlign', parent=styles['Normal'], alignment=TA_RIGHT)
    
    # Title
    elements.append(Paragraph("INVOICE", title_style))
    elements.append(Spacer(1, 0.3*inch))
    
    # Invoice Info
    invoice_info = [
        ['Invoice No:', invoice.invoice_number, 'Date:', invoice.date.strftime('%d %b %Y')],
        ['Status:', 'PAID' if invoice.is_paid else 'PENDING', '', '']
    ]
    invoice_table = Table(invoice_info, colWidths=[1.5*inch, 2.5*inch, 1*inch, 1.5*inch])
    invoice_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#666666')),
        ('TEXTCOLOR', (2, 0), (2, -1), colors.HexColor('#666666')),
    ]))
    elements.append(invoice_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Party Details
    elements.append(Paragraph("BILL TO", heading_style))
    party_data = [
        ['Party Name:', invoice.party.name],
        ['Phone:', invoice.party.phone or 'N/A'],
        ['Email:', invoice.party.email or 'N/A'],
    ]
    party_table = Table(party_data, colWidths=[1.5*inch, 5*inch])
    party_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#666666')),
    ]))
    elements.append(party_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Items Table
    elements.append(Paragraph("ITEMS", heading_style))
    items_data = [['#', 'Item', 'Qty', 'Rate', 'GST', 'Discount', 'Total']]
    for idx, item in enumerate(invoice.invoice_items.all(), 1):
        items_data.append([
            str(idx),
            item.item.name[:30] if item.item else 'N/A',
            str(item.quantity),
            f'₹ {item.rate:,.2f}',
            f'₹ {item.gst_amount:,.2f}',
            f'₹ {item.discount_amount:,.2f}',
            f'₹ {item.total:,.2f}'
        ])
    
    total_amount = sum(item.total for item in invoice.invoice_items.all())
    items_data.append(['', '', '', '', '', 'TOTAL:', f'₹ {total_amount:,.2f}'])
    
    items_table = Table(items_data, colWidths=[0.4*inch, 2.5*inch, 0.7*inch, 1*inch, 1*inch, 1*inch, 1.2*inch])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#00c2ff')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
        ('GRID', (0, 0), (-1, -2), 1, colors.grey),
        ('FONTNAME', (0, 1), (-1, -2), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -2), 9),
        ('ALIGN', (2, 1), (-1, -2), 'RIGHT'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#00c2ff')),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.whitesmoke),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 11),
        ('ALIGN', (0, -1), (-1, -1), 'RIGHT'),
        ('SPAN', (0, -1), (-3, -1)),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Payment Summary
    elements.append(Paragraph("PAYMENT SUMMARY", heading_style))
    total_paid = sum(payment.amount for payment in invoice.payments.all())
    balance = total_amount - total_paid
    
    summary_data = [
        ['Invoice Total:', f'₹ {total_amount:,.2f}'],
        ['Amount Paid:', f'₹ {total_paid:,.2f}'],
        ['Balance Due:', f'₹ {balance:,.2f}']
    ]
    
    summary_table = Table(summary_data, colWidths=[4.5*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -2), 10),
        ('FONTSIZE', (0, -1), (-1, -1), 12),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f0f0f0')),
        ('LINEABOVE', (0, -1), (-1, -1), 2, colors.HexColor('#00c2ff')),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 0.5*inch))
    
    # Footer
    footer_text = f"Generated on {datetime.now().strftime('%d %b %Y at %I:%M %p')}"
    elements.append(Paragraph(footer_text, right_align_style))
    elements.append(Paragraph("Thank you for your business!", styles['Normal']))
    
    doc.build(elements)
    buffer.seek(0)
    
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    filename = f'Invoice_{invoice.invoice_number.replace("/", "-")}_{invoice.party.name.replace(" ", "_")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


def generate_payment_receipt_pdf(payment):
    """Generate professional PDF payment receipt"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#28a745'),
        spaceAfter=12,
        alignment=TA_CENTER
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#34d058'),
        spaceAfter=6
    )
    
    right_align_style = ParagraphStyle('RightAlign', parent=styles['Normal'], alignment=TA_RIGHT)
    
    # Title
    elements.append(Paragraph("PAYMENT RECEIPT", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Receipt Info
    receipt_info = [
        ['Receipt No:', f'PAY-{payment.id:06d}', 'Date:', payment.date.strftime('%d %b %Y')],
    ]
    receipt_table = Table(receipt_info, colWidths=[1.5*inch, 2*inch, 1*inch, 2*inch])
    receipt_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
    ]))
    elements.append(receipt_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Party Details
    elements.append(Paragraph("RECEIVED FROM", heading_style))
    party_data = [
        ['Party Name:', payment.party.name],
        ['Phone:', payment.party.phone or 'N/A'],
        ['Email:', payment.party.email or 'N/A'],
    ]
    party_table = Table(party_data, colWidths=[1.5*inch, 5*inch])
    party_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
    ]))
    elements.append(party_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Payment Details
    elements.append(Paragraph("PAYMENT DETAILS", heading_style))
    payment_data = [
        ['Description', 'Amount'],
        ['Payment for ' + (f'Invoice #{payment.invoice.invoice_number}' if payment.invoice else 'General Payment'),
         f'₹ {payment.amount:,.2f}'],
        ['Payment Mode:', payment.get_mode_display()],
    ]
    
    if payment.notes:
        payment_data.append(['Notes:', payment.notes[:100]])
    
    payment_table = Table(payment_data, colWidths=[4*inch, 2.5*inch])
    payment_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#28a745')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('ALIGN', (1, 1), (1, 1), 'RIGHT'),
    ]))
    elements.append(payment_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Total Amount Box
    total_data = [['TOTAL AMOUNT RECEIVED', f'₹ {payment.amount:,.2f}']]
    total_table = Table(total_data, colWidths=[4*inch, 2.5*inch])
    total_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#34d058')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 14),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('PADDING', (0, 0), (-1, -1), 15),
    ]))
    elements.append(total_table)
    elements.append(Spacer(1, 0.5*inch))
    
    # Footer
    footer_text = f"Generated on {datetime.now().strftime('%d %b %Y at %I:%M %p')}"
    elements.append(Paragraph(footer_text, right_align_style))
    elements.append(Paragraph("Thank you for your payment!", styles['Normal']))
    
    doc.build(elements)
    buffer.seek(0)
    
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    filename = f'Payment_Receipt_{payment.id}_{payment.party.name.replace(" ", "_")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


def generate_return_receipt_pdf(return_obj):
    """Generate professional PDF return receipt"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#dc3545'),
        spaceAfter=12,
        alignment=TA_CENTER
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#e74c3c'),
        spaceAfter=6
    )
    
    right_align_style = ParagraphStyle('RightAlign', parent=styles['Normal'], alignment=TA_RIGHT)
    
    # Title
    elements.append(Paragraph("RETURN RECEIPT", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Return Info
    return_info = [
        ['Return No:', f'RET-{return_obj.id:06d}', 'Date:', return_obj.return_date.strftime('%d %b %Y')],
        ['Invoice:', return_obj.invoice.invoice_number, '', '']
    ]
    return_table = Table(return_info, colWidths=[1.5*inch, 2*inch, 1*inch, 2*inch])
    return_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('SPAN', (1, 1), (-1, 1)),
    ]))
    elements.append(return_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Party Details
    elements.append(Paragraph("RETURN FROM", heading_style))
    party_data = [
        ['Party Name:', return_obj.party.name],
        ['Phone:', return_obj.party.phone or 'N/A'],
        ['Email:', return_obj.party.email or 'N/A'],
    ]
    party_table = Table(party_data, colWidths=[1.5*inch, 5*inch])
    party_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
    ]))
    elements.append(party_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Return Details
    elements.append(Paragraph("RETURN DETAILS", heading_style))
    return_data = [
        ['Description', 'Amount'],
        [f'Return for Invoice #{return_obj.invoice.invoice_number}', f'₹ {return_obj.amount:,.2f}'],
    ]
    
    if return_obj.reason:
        return_data.append(['Reason:', return_obj.reason[:100]])
    
    return_details_table = Table(return_data, colWidths=[4*inch, 2.5*inch])
    return_details_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#dc3545')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('ALIGN', (1, 1), (1, 1), 'RIGHT'),
    ]))
    elements.append(return_details_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Total Amount Box
    total_data = [['TOTAL RETURN AMOUNT', f'₹ {return_obj.amount:,.2f}']]
    total_table = Table(total_data, colWidths=[4*inch, 2.5*inch])
    total_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e74c3c')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 14),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('PADDING', (0, 0), (-1, -1), 15),
    ]))
    elements.append(total_table)
    elements.append(Spacer(1, 0.5*inch))
    
    # Footer
    footer_text = f"Generated on {datetime.now().strftime('%d %b %Y at %I:%M %p')}"
    elements.append(Paragraph(footer_text, right_align_style))
    elements.append(Paragraph("Return processed successfully.", styles['Normal']))
    
    doc.build(elements)
    buffer.seek(0)
    
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    filename = f'Return_Receipt_{return_obj.id}_{return_obj.party.name.replace(" ", "_")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


def generate_challan_pdf(challan):
    """Generate professional PDF challan"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=28,
        textColor=colors.HexColor('#6f42c1'),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#8e44ad'),
        spaceAfter=8,
        fontName='Helvetica-Bold'
    )
    
    right_align_style = ParagraphStyle('RightAlign', parent=styles['Normal'], alignment=TA_RIGHT)
    
    # Title
    elements.append(Paragraph("DELIVERY CHALLAN", title_style))
    elements.append(Spacer(1, 0.3*inch))
    
    # Challan Info
    challan_info = [
        ['Challan No:', challan.challan_number, 'Date:', challan.date.strftime('%d %b %Y')],
    ]
    if challan.invoice:
        challan_info.append(['Invoice No:', challan.invoice.invoice_number, '', ''])
    
    challan_table = Table(challan_info, colWidths=[1.5*inch, 2.5*inch, 1*inch, 1.5*inch])
    challan_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('SPAN', (1, 1), (-1, 1)) if challan.invoice else ('SPAN', (0, 0), (0, 0)),
    ]))
    elements.append(challan_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Party Details
    elements.append(Paragraph("DELIVER TO", heading_style))
    party_data = [
        ['Party Name:', challan.party.name],
        ['Phone:', challan.party.phone or 'N/A'],
        ['Email:', challan.party.email or 'N/A'],
    ]
    party_table = Table(party_data, colWidths=[1.5*inch, 5*inch])
    party_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
    ]))
    elements.append(party_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Items Table
    elements.append(Paragraph("ITEMS", heading_style))
    items_data = [['#', 'Item Name', 'Quantity']]
    for idx, item in enumerate(challan.challan_items.all(), 1):
        items_data.append([
            str(idx),
            item.item.name if item.item else 'N/A',
            str(item.quantity)
        ])
    
    items_table = Table(items_data, colWidths=[0.5*inch, 5*inch, 1.5*inch])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6f42c1')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ALIGN', (2, 1), (2, -1), 'CENTER'),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Transport Details
    if challan.transport_details:
        elements.append(Paragraph("TRANSPORT DETAILS", heading_style))
        elements.append(Paragraph(challan.transport_details, styles['Normal']))
        elements.append(Spacer(1, 0.3*inch))
    
    elements.append(Spacer(1, 0.5*inch))
    
    # Footer
    footer_text = f"Generated on {datetime.now().strftime('%d %b %Y at %I:%M %p')}"
    elements.append(Paragraph(footer_text, right_align_style))
    elements.append(Paragraph("Thank you for your business!", styles['Normal']))
    
    doc.build(elements)
    buffer.seek(0)
    
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    filename = f'Challan_{challan.challan_number.replace("/", "-")}_{challan.party.name.replace(" ", "_")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


# ================================================================
# INVOICE VIEWS
# ================================================================

@login_required_cbv
class InvoiceListView(ListView):
    model = Invoice
    template_name = 'billing/invoice_list.html'
    context_object_name = 'invoice_data'
    ordering = ['-date']

    def get_queryset(self):
        return super().get_queryset().select_related('party', 'created_by').prefetch_related('invoice_items')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for invoice in context['invoice_data']:
            check_and_close_invoice(invoice)
        return context


@login_required_cbv
class InvoiceDetailView(DetailView):
    model = Invoice
    template_name = 'billing/invoice_detail.html'
    pk_url_kwarg = 'invoice_id'
    context_object_name = 'invoice'

    def get_queryset(self):
        return Invoice.objects.select_related('party').prefetch_related(
            'invoice_items__item', 'payments', 'returns'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = context['invoice']
        
        check_and_close_invoice(invoice)
        invoice.refresh_from_db()
        
        total_paid = invoice.total_paid or Decimal('0.00')
        total_returns = sum(r.amount for r in invoice.returns.all())
        balance_due = invoice.balance_due or Decimal('0.00')
        
        if balance_due < Decimal('0.00'):
            balance_due = Decimal('0.00')
        
        context.update({
            'items': invoice.invoice_items.all(),
            'payments': invoice.payments.all(),
            'returns': invoice.returns.all(),
            'total_paid': total_paid,
            'balance_due': balance_due,
            'total_returns': total_returns,
            'status': 'Closed' if invoice.is_paid else 'Open'
        })
        return context


@login_required_cbv
class InvoiceCreateView(View):
    template_name = 'billing/create_invoice.html'

    def generate_invoice_number(self):
        """Generate unique invoice number with timestamp"""
        year = timezone.now().year
        prefix = f"INV-{year}-"
        
        last_invoice = Invoice.objects.filter(
            invoice_number__startswith=prefix
        ).order_by("-id").first()
        
        next_num = 1
        if last_invoice and last_invoice.invoice_number:
            try:
                parts = last_invoice.invoice_number.replace(prefix, '').split('-')
                next_num = int(parts[0]) + 1
            except (ValueError, IndexError):
                pass
        
        timestamp = timezone.now().strftime('%f')[:4]
        return f"{prefix}{next_num:04d}-{timestamp}"

    @transaction.atomic
    def get(self, request):
        auto_invoice_number = self.generate_invoice_number()
        form = InvoiceForm(initial={
            'is_limit_enabled': False,
            'limit_amount': 0,
            'invoice_number': auto_invoice_number
        })
        form.fields['invoice_number'].widget.attrs['readonly'] = True
        formset = InvoiceItemFormSet()
        parties = list(Party.objects.values('id', 'name', 'phone'))
        return render(request, self.template_name, {
            'form': form,
            'formset': formset,
            'parties': json.dumps(parties),
        })

    @transaction.atomic
    def post(self, request):
        form = InvoiceForm(request.POST)
        formset = InvoiceItemFormSet(request.POST)

        send_whatsapp = request.POST.get('send_whatsapp') == 'on'
        download_pdf = request.POST.get('download_pdf') == 'on'

        if not form.is_valid():
            messages.error(request, f'Form errors: {form.errors}')
            parties = list(Party.objects.values('id', 'name', 'phone'))
            return render(request, self.template_name, {
                'form': form,
                'formset': formset,
                'parties': json.dumps(parties),
            })

        valid_items, formset_errors = [], []
        for i, f in enumerate(formset.forms):
            prefix = f'{formset.prefix}-{i}'
            item_id = request.POST.get(f'{prefix}-item', '').strip()
            new_item_name = request.POST.get(f'{prefix}-new_item_name', '').strip()
            qty = request.POST.get(f'{prefix}-quantity', '').strip()
            rate = request.POST.get(f'{prefix}-rate', '').strip()

            if not any([item_id, new_item_name, qty, rate]):
                continue
            if not (item_id or new_item_name):
                formset_errors.append(f"Row {i+1}: Select or enter item name")
                continue
            try:
                if not qty or float(qty) <= 0:
                    formset_errors.append(f"Row {i+1}: Invalid quantity")
                    continue
            except ValueError:
                formset_errors.append(f"Row {i+1}: Quantity must be numeric")
                continue
            try:
                if not rate or float(rate) <= 0:
                    formset_errors.append(f"Row {i+1}: Invalid rate")
                    continue
            except ValueError:
                formset_errors.append(f"Row {i+1}: Rate must be numeric")
                continue

            valid_items.append({
                'item_id': item_id,
                'new_item_name': new_item_name,
                'quantity': qty,
                'rate': rate,
                'discount_amount': request.POST.get(f'{prefix}-discount_amount', '0'),
            })

        if formset_errors:
            for e in formset_errors:
                messages.error(request, e)
            return render(request, self.template_name, {
                'form': form,
                'formset': formset,
                'parties': json.dumps(list(Party.objects.values('id', 'name', 'phone'))),
            })

        if not valid_items:
            messages.error(request, "Please add at least one item.")
            return render(request, self.template_name, {
                'form': form,
                'formset': formset,
                'parties': json.dumps(list(Party.objects.values('id', 'name', 'phone'))),
            })

        try:
            new_party_name = form.cleaned_data.get('new_party_name', '').strip()
            if new_party_name:
                party, _ = Party.objects.get_or_create(
                    name__iexact=new_party_name,
                    defaults={
                        'name': new_party_name,
                        'phone': form.cleaned_data.get('new_party_phone', ''),
                        'created_by': request.user
                    }
                )
            else:
                party = form.cleaned_data.get('party')

            if not party:
                messages.error(request, "Select or create a party.")
                raise ValueError("Missing party")

            invoice = form.save(commit=False)
            invoice.party = party
            invoice.created_by = request.user
            invoice.updated_by = request.user
            if not invoice.invoice_number:
                invoice.invoice_number = self.generate_invoice_number()
            invoice.is_limit_enabled = form.cleaned_data.get('is_limit_enabled', False)
            invoice.limit_amount = form.cleaned_data.get('limit_amount') or Decimal('0.00')

            max_retries = 10
            attempt = 0
            saved = False
            last_error = None
            
            while attempt < max_retries and not saved:
                attempt += 1
                sid = transaction.savepoint()
                try:
                    if attempt > 1:
                        invoice.pk = None
                        invoice.id = None
                    
                    invoice.save()
                    transaction.savepoint_commit(sid)
                    saved = True
                    logger.info(f"✅ Invoice saved: {invoice.invoice_number} (ID: {invoice.id}) on attempt {attempt}")
                    
                except IntegrityError as ie:
                    transaction.savepoint_rollback(sid)
                    last_error = ie
                    error_msg = str(ie).lower()
                    
                    logger.warning(f"IntegrityError on invoice.save() attempt {attempt}: {ie}")
                    
                    if 'invoice_number' in error_msg or 'unique constraint' in error_msg:
                        year = timezone.now().year
                        prefix = f"INV-{year}-"
                        
                        last_invoice = Invoice.objects.filter(
                            invoice_number__startswith=prefix
                        ).order_by("-id").first()
                        
                        next_num = 1
                        if last_invoice and last_invoice.invoice_number:
                            try:
                                parts = last_invoice.invoice_number.replace(prefix, '').split('-')
                                next_num = int(parts[0]) + 1
                            except (ValueError, IndexError):
                                pass
                        
                        timestamp = timezone.now().strftime('%f')
                        invoice.invoice_number = f"{prefix}{next_num:04d}-{timestamp}-{attempt}"
                        time.sleep(0.001)
                    else:
                        logger.error(f"Non-invoice_number IntegrityError: {ie}")
                        transaction.savepoint_rollback(sid)
                        raise
                        
                except Exception as e:
                    transaction.savepoint_rollback(sid)
                    logger.error(f"Unexpected error on invoice.save() attempt {attempt}: {e}", exc_info=True)
                    raise

            if not saved:
                error_msg = f"Failed to save invoice after {max_retries} retries."
                logger.error(error_msg)
                if last_error:
                    messages.error(request, f"Unable to generate unique invoice number. Please try again.")
                    raise IntegrityError(error_msg) from last_error
                raise IntegrityError(error_msg)

            total_amount = Decimal('0.00')
            for item_data in valid_items:
                if item_data['item_id']:
                    try:
                        item_obj = Item.objects.get(id=item_data['item_id'])
                    except Item.DoesNotExist:
                        messages.error(request, f"Item with ID {item_data['item_id']} not found.")
                        raise ValueError(f"Item not found: {item_data['item_id']}")
                else:
                    item_obj, created = Item.objects.get_or_create(
                        name=item_data['new_item_name'],
                        defaults={
                            'price_retail': Decimal(item_data['rate']),
                            'price_wholesale': Decimal(item_data['rate']),
                            'created_by': request.user
                        }
                    )
                    if created:
                        logger.info(f"✅ New item created: {item_obj.name}")

                gst_percent = item_obj.gst_percent or Decimal('0.00')
                
                calculated = calculate_item_totals(
                    quantity=item_data['quantity'],
                    rate=item_data['rate'],
                    gst_percent=gst_percent,
                    discount_amount=item_data.get('discount_amount', '0')
                )
                
                inv_item = InvoiceItem.objects.create(
                    invoice=invoice,
                    item=item_obj,
                    quantity=Decimal(item_data['quantity']),
                    rate=Decimal(item_data['rate']),
                    gst_amount=calculated['gst_amount'],
                    discount_amount=calculated['discount_amount'],
                    total=calculated['total'],
                    created_by=request.user,
                    updated_by=request.user
                )
                total_amount += inv_item.total
                
                logger.info(f"✅ Item: {item_obj.name}, Qty: {inv_item.quantity}, "
                           f"Rate: {inv_item.rate}, GST%: {gst_percent}, "
                           f"GST Amount: {inv_item.gst_amount}, Total: {inv_item.total}")

                if invoice.is_limit_enabled and total_amount > (invoice.limit_amount or Decimal('0.00')):
                    messages.error(request, f"Invoice limit exceeded. Limit: ₹{invoice.limit_amount}, Total: ₹{total_amount}")
                    raise ValueError("Limit exceeded")

            invoice.base_amount = total_amount
            invoice.save()

            if send_whatsapp and invoice.party.phone:
                try:
                    logger.info(f"WhatsApp invoice sent to {invoice.party.name}")
                except Exception as e:
                    logger.warning(f"WhatsApp send failed: {e}")
                    messages.warning(request, "Invoice created but WhatsApp send failed.")

            success_msg = f'✅ Invoice {invoice.invoice_number} created successfully with {len(valid_items)} items.'
            
            if download_pdf:
                messages.success(request, success_msg)
                return redirect(f"/billing/invoices/{invoice.id}/?download=1")

            
            messages.success(request, success_msg)
            return redirect('billing:invoice_detail', invoice_id=invoice.id)

        except ValueError as ve:
            logger.error(f"Validation error creating invoice: {ve}", exc_info=True)
            messages.error(request, f"Validation Error: {ve}")
        except IntegrityError as ie:
            logger.error(f"Integrity error creating invoice: {ie}", exc_info=True)
            messages.error(request, "Database error occurred. Please try again.")
        except Exception as e:
            logger.error(f"Unexpected error creating invoice: {e}", exc_info=True)
            messages.error(request, f"An unexpected error occurred: {str(e)}")

        return render(request, self.template_name, {
            'form': form,
            'formset': formset,
            'parties': json.dumps(list(Party.objects.values('id', 'name', 'phone'))),
        })


@login_required
def get_item_rate(request, item_id):
    try:
        item = get_object_or_404(Item, id=item_id)
        return JsonResponse({
            "wholesale_rate": float(item.price_wholesale or 0),
            "retail_rate": float(item.price_retail or 0),
            "gst_percent": float(item.gst_percent or 0),
        })
    except Exception as e:
        logger.error(f"Error fetching item rate: {e}")
        return JsonResponse({"error": "Item not found"}, status=404)


@login_required_cbv
class InvoiceUpdateView(View):
    template_name = 'billing/edit_invoice.html'

    @transaction.atomic
    def get(self, request, invoice_id):
        invoice = get_object_or_404(Invoice, id=invoice_id)
        form = InvoiceForm(instance=invoice)
        formset = InvoiceItemFormSet(instance=invoice)
        parties = list(Party.objects.values('id', 'name', 'phone'))
        return render(request, self.template_name, {
            'form': form, 'formset': formset, 'invoice': invoice, 'parties': json.dumps(parties)
        })

    @transaction.atomic
    def post(self, request, invoice_id):
        invoice = get_object_or_404(Invoice, id=invoice_id)
        form = InvoiceForm(request.POST, instance=invoice)
        formset = InvoiceItemFormSet(request.POST, instance=invoice)

        if not (form.is_valid() and formset.is_valid()):
            messages.error(request, 'Please correct the errors.')
            return render(request, self.template_name, {'form': form, 'formset': formset, 'invoice': invoice})

        try:
            invoice = form.save(commit=False)
            invoice.updated_by = request.user
            total = Decimal('0.00')
            items = formset.save(commit=False)

            for item in items:
                if not item.item and hasattr(item, 'new_item_name'):
                    name = item.new_item_name.strip()
                    if name:
                        item.item, _ = Item.objects.get_or_create(name=name, defaults={
                            'price_retail': item.rate,
                            'price_wholesale': item.rate,
                            'created_by': request.user
                        })
                
                if item.item:
                    gst_percent = item.item.gst_percent or Decimal('0.00')
                    calculated = calculate_item_totals(
                        quantity=item.quantity,
                        rate=item.rate,
                        gst_percent=gst_percent,
                        discount_amount=item.discount_amount or Decimal('0.00')
                    )
                    item.gst_amount = calculated['gst_amount']
                    item.total = calculated['total']
                
                item.invoice = invoice
                item.updated_by = request.user
                item.save()
                total += item.total

            for obj in formset.deleted_objects:
                obj.delete()

            invoice.base_amount = total
            invoice.save()
            
            check_and_close_invoice(invoice)
            
            messages.success(request, f'Invoice {invoice.invoice_number} updated successfully.')
            return redirect('billing:invoice_detail', invoice_id=invoice.id)
        except Exception as e:
            logger.error(f"Error updating invoice: {e}", exc_info=True)
            messages.error(request, f'Error updating invoice: {str(e)}')
            return render(request, self.template_name, {'form': form, 'formset': formset, 'invoice': invoice})


@login_required
def get_invoice_amounts(request, invoice_id):
    """AJAX endpoint to fetch invoice total and pending amounts"""
    try:
        invoice = Invoice.objects.get(id=invoice_id)
        
        total = float(invoice.total_amount or 0)
        paid = invoice.payments.aggregate(
            total_paid=Sum('amount')
        )['total_paid'] or 0
        paid = float(paid)
        
        returns = sum(float(r.amount) for r in invoice.returns.all())
        pending = total - paid - returns
        
        if pending < 0:
            pending = 0
        
        return JsonResponse({
            'total': round(total, 2),
            'paid': round(paid, 2),
            'returns': round(returns, 2),
            'pending': round(pending, 2),
            'invoice_number': invoice.invoice_number,
            'party_name': invoice.party.name,
            'is_closed': invoice.is_paid,
            'status': 'success'
        })
        
    except Invoice.DoesNotExist:
        return JsonResponse({
            'error': 'Invoice not found',
            'status': 'error'
        }, status=404)
    except Exception as e:
        logger.error(f"Error fetching invoice amounts for ID {invoice_id}: {e}")
        return JsonResponse({
            'error': 'An error occurred while fetching invoice data',
            'status': 'error'
        }, status=500)


# ================================================================
# PAYMENT VIEWS
# ================================================================

@login_required_cbv
class PaymentListView(ListView):
    model = Payment
    template_name = 'billing/payment_list.html'
    context_object_name = 'payments'
    ordering = ['-date']

    def get_queryset(self):
        return Payment.objects.select_related('party', 'invoice')
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        download_payment = self.request.session.pop("download_payment", None)
        context["download_payment"] = download_payment

        return context



@login_required_cbv
class PaymentDetailView(DetailView):
    model = Payment
    template_name = 'billing/payment_detail.html'
    pk_url_kwarg = 'payment_id'
    context_object_name = 'payment'

    def get_queryset(self):
        return Payment.objects.select_related('party', 'invoice')


@login_required_cbv
class PaymentCreateView(View):
    template_name = 'billing/add_payment.html'

    @transaction.atomic
    def get(self, request, invoice_id=None):
        initial_data = {}
        if invoice_id:
            invoice = get_object_or_404(Invoice, id=invoice_id)
            initial_data = {
                'invoice': invoice, 
                'party': invoice.party, 
                'amount': invoice.balance_due if invoice.balance_due > 0 else None
            }
        
        form = PaymentForm(initial=initial_data)
        return render(request, self.template_name, {
            'form': form, 
            'invoice_id': invoice_id
        })

    @transaction.atomic
    def post(self, request, invoice_id=None):
        form = PaymentForm(request.POST)
        
        # Get toggle values
        download_pdf = request.POST.get('download_receipt') == 'on'
        
        if not form.is_valid():
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__':
                        error_messages.append(error)
                    else:
                        field_label = form.fields.get(field).label if field in form.fields else field
                        error_messages.append(f"{field_label}: {error}")
            
            messages.error(request, ' | '.join(error_messages))
            return render(request, self.template_name, {
                'form': form, 
                'invoice_id': invoice_id
            })

        try:
            party = form.cleaned_data.get('party')
            new_party_name = form.cleaned_data.get('new_party_name', '').strip()
            
            if not party and new_party_name:
                party, created = Party.objects.get_or_create(
                    name__iexact=new_party_name,
                    defaults={
                        'name': new_party_name,
                        'created_by': request.user
                    }
                )
                if created:
                    messages.info(request, f'✨ New party "{new_party_name}" created successfully.')

            payment = form.save(commit=False)
            payment.party = party
            payment.created_by = request.user
            payment.updated_by = request.user
            
            if payment.invoice:
                invoice = payment.invoice
                total_amount = invoice.total_amount or Decimal('0.00')
                total_paid = invoice.total_paid or Decimal('0.00')
                total_returns = sum(r.amount for r in invoice.returns.all())
                current_balance = total_amount - total_paid - total_returns
                
                if current_balance < Decimal('0.00'):
                    current_balance = Decimal('0.00')
                
                if payment.amount > current_balance:
                    messages.error(request, 
                        f'❌ Payment amount ₹{payment.amount} exceeds balance due ₹{current_balance:.2f}.')
                    return render(request, self.template_name, {
                        'form': form, 
                        'invoice_id': invoice_id
                    })
            
            if payment.amount <= Decimal('0.00'):
                messages.error(request, '❌ Payment amount must be greater than zero.')
                return render(request, self.template_name, {
                    'form': form, 
                    'invoice_id': invoice_id
                })
            
            payment.save()

            if payment.invoice:
                check_and_close_invoice(payment.invoice)

            send_receipt = form.cleaned_data.get('send_receipt', False)
            
            if send_receipt:
                if payment.party.phone:
                    try:
                        send_payment_receipt(payment.party, payment)
                        messages.success(request, 
                            f'✅ Payment ₹{payment.amount:.2f} recorded and receipt sent to {payment.party.name}.')
                    except Exception as e:
                        logger.warning(f"Receipt send failed for payment {payment.id}: {e}")
                        messages.warning(request, 
                            f'✅ Payment recorded but receipt failed to send.')
                else:
                    messages.warning(request, 
                        f'✅ Payment recorded but party has no phone number for receipt.')
            else:
                messages.success(request, 
                    f'✅ Payment ₹{payment.amount:.2f} recorded successfully for {payment.party.name}.')

            if download_pdf:
                request.session["download_payment"] = payment.id
                return redirect("billing:payment_list")


            if invoice_id:
                if download_pdf:
                    return redirect(f"/billing/payments/{payment.id}/?download=1")

            return redirect('billing:payment_list')
            
        except Exception as e:
            logger.error(f"Error adding payment: {e}", exc_info=True)
            messages.error(request, f"❌ Error processing payment: {str(e)}")
            return render(request, self.template_name, {
                'form': form, 
                'invoice_id': invoice_id
            })


# ================================================================
# RETURN VIEWS
# ================================================================
# ================================================================
# RETURN VIEWS (FINAL — With Session PDF Trigger)
# ================================================================
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


@login_required_cbv
class ReturnListView(ListView):
    model = Return
    template_name = 'billing/return_list.html'
    context_object_name = 'returns'
    ordering = ['-return_date']

    def get_queryset(self):
        return Return.objects.select_related('invoice', 'party', 'created_by')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["download_return"] = self.request.session.pop("download_return", None)
        return context



@login_required_cbv
class ReturnCreateView(View):
    template_name = 'billing/create_return.html'

    @transaction.atomic
    def get(self, request):
        form = ReturnForm()
        return render(request, self.template_name, {'form': form})

    @transaction.atomic
    def post(self, request):
        form = ReturnForm(request.POST, request.FILES)

        # Checkbox toggle
        download_pdf = request.POST.get('download_receipt') == 'on'

        if not form.is_valid():
            messages.error(request, 'Please correct the form errors.')
            return render(request, self.template_name, {'form': form})

        try:
            ret = form.save(commit=False)
            ret.created_by = request.user
            ret.updated_by = request.user

            invoice = ret.invoice
            total_amount = invoice.total_amount or Decimal('0.00')
            total_paid = invoice.total_paid or Decimal('0.00')
            existing_returns = sum(r.amount for r in invoice.returns.all())

            max_returnable = total_amount - existing_returns

            # Validation
            if ret.amount <= Decimal('0.00'):
                messages.error(request, 'Return amount must be greater than zero.')
                return render(request, self.template_name, {'form': form})

            if ret.amount > max_returnable:
                messages.error(
                    request,
                    f'Return amount ₹{ret.amount} exceeds maximum returnable amount ₹{max_returnable}. '
                    f'(Total: ₹{total_amount}, Existing Returns: ₹{existing_returns})'
                )
                return render(request, self.template_name, {'form': form})

            # Save Return
            ret.save()

            # Update invoice status
            check_and_close_invoice(invoice)
            invoice.refresh_from_db()

            status_msg = " Invoice automatically closed." if invoice.is_paid else ""
            messages.success(
                request,
                f'✅ Return of ₹{ret.amount} recorded for invoice {ret.invoice.invoice_number}.{status_msg}'
            )

            # 🚀 SESSION-BASED PDF DOWNLOAD AFTER REDIRECT
            if download_pdf:
                request.session["download_return"] = ret.id
                return redirect("billing:return_list")


            # Default redirect to invoice detail
            return redirect("billing:invoice_detail", invoice_id=ret.invoice.id)

        except Exception as e:
            logger.error(f"Error creating return: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")
            return render(request, self.template_name, {'form': form})


# ================================================================
# CHALLAN VIEWS
# ================================================================

@login_required_cbv
class ChallanListView(ListView):
    model = Challan
    template_name = 'billing/challan_list.html'
    context_object_name = 'challans'
    ordering = ['-date']

    def get_queryset(self):
        return (
            Challan.objects
            .select_related('party', 'invoice', 'created_by', 'updated_by')
            .prefetch_related('challan_items__item')
        )


@login_required_cbv
class ChallanDetailView(DetailView):
    model = Challan
    template_name = 'billing/challan_details.html'
    pk_url_kwarg = 'challan_id'
    context_object_name = 'challan'

    def get_queryset(self):
        return (
            Challan.objects
            .select_related('party', 'invoice', 'created_by', 'updated_by')
            .prefetch_related('challan_items__item')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['items'] = context['challan'].challan_items.all()
        return context


@login_required_cbv
class ChallanCreateView(View):
    template_name = 'billing/create_challan.html'

    def get(self, request):
        form = ChallanForm()
        formset = ChallanItemFormSet()
        return render(request, self.template_name, {'form': form, 'formset': formset})

    @transaction.atomic
    def post(self, request):
        form = ChallanForm(request.POST)
        formset = ChallanItemFormSet(request.POST)
        
        # Get toggle value for PDF download
        download_pdf = request.POST.get('download_pdf') == 'on'

        if not (form.is_valid() and formset.is_valid()):
            messages.error(request, "Please correct the errors below.")
            return render(request, self.template_name, {'form': form, 'formset': formset})

        try:
            challan = form.save(commit=False)
            challan.created_by = request.user
            challan.updated_by = request.user
            challan.save()

            items = formset.save(commit=False)

            for deleted_item in formset.deleted_objects:
                deleted_item.delete()

            for item in items:
                item.challan = challan
                item.created_by = request.user
                item.updated_by = request.user
                item.save()

            messages.success(request, f"✅ Challan {challan.challan_number} created successfully!")
            
            # Handle PDF download if requested
            from django.urls import reverse

            if download_pdf:
                url = reverse('billing:challan_detail', args=[challan.id])
                return redirect(f"{url}?download=1")

            
            return redirect('billing:challan_detail', challan_id=challan.id)

        except Exception as e:
            logger.error(f"Error creating challan: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")
            return render(request, self.template_name, {'form': form, 'formset': formset})


@login_required_cbv
class ChallanUpdateView(View):
    template_name = 'billing/update_challan.html'

    @transaction.atomic
    def get(self, request, challan_id):
        challan = get_object_or_404(Challan, id=challan_id)
        form = ChallanForm(instance=challan)
        formset = ChallanItemFormSet(instance=challan)
        return render(request, self.template_name, {
            'form': form,
            'formset': formset,
            'challan': challan
        })

    @transaction.atomic
    def post(self, request, challan_id):
        challan = get_object_or_404(Challan, id=challan_id)
        form = ChallanForm(request.POST, instance=challan)
        formset = ChallanItemFormSet(request.POST, instance=challan)

        if not (form.is_valid() and formset.is_valid()):
            messages.error(request, "Please correct the errors below.")
            return render(request, self.template_name, {
                'form': form,
                'formset': formset,
                'challan': challan
            })

        try:
            challan = form.save(commit=False)
            challan.updated_by = request.user
            challan.save()

            items = formset.save(commit=False)

            for obj in formset.deleted_objects:
                obj.delete()

            for item in items:
                item.challan = challan
                item.updated_by = request.user
                if not item.created_by:
                    item.created_by = request.user
                item.save()

            messages.success(request, f"Challan {challan.challan_number} updated successfully!")
            return redirect('billing:challan_detail', challan_id=challan.id)

        except Exception as e:
            logger.error(f"Error updating challan: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")
            return render(request, self.template_name, {
                'form': form,
                'formset': formset,
                'challan': challan
            })


@login_required
def challan_delete(request, challan_id):
    """Delete challan view"""
    challan = get_object_or_404(Challan, id=challan_id)

    if request.method == "POST":
        challan.delete()
        messages.success(request, "Challan deleted successfully.")
        return redirect('billing:challan_list')

    return render(request, "billing/confirm_delete_challan.html", {"challan": challan})


# ================================================================
# BALANCE MANAGEMENT
# ================================================================

@login_required_cbv
class BalanceManageView(View):
    template_name = 'billing/manage_balance.html'

    @transaction.atomic
    def get(self, request):
        formset = BalanceFormSet(queryset=Balance.objects.all())
        return render(request, self.template_name, {'formset': formset})

    @transaction.atomic
    def post(self, request):
        formset = BalanceFormSet(request.POST)
        if not formset.is_valid():
            messages.error(request, 'Please correct form errors.')
            return render(request, self.template_name, {'formset': formset})
        try:
            instances = formset.save(commit=False)
            for instance in instances:
                instance.created_by = request.user
                instance.updated_by = request.user
                instance.save()
            for obj in formset.deleted_objects:
                obj.delete()
            messages.success(request, 'Balances updated successfully.')
            return redirect('billing:manage_balance')
        except Exception as e:
            logger.error(f"Error managing balance: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")
            return render(request, self.template_name, {'formset': formset})
        
@login_required
def invoice_pdf(request, invoice_id):
    invoice = get_object_or_404(Invoice, id=invoice_id)
    return generate_invoice_pdf(invoice)

@login_required
def payment_pdf(request, payment_id):
    payment = get_object_or_404(Payment, id=payment_id)
    return generate_payment_receipt_pdf(payment)

@login_required
def return_pdf(request, return_id):
    ret = get_object_or_404(Return, id=return_id)
    return generate_return_receipt_pdf(ret)

@login_required
def challan_pdf(request, challan_id):
    challan = get_object_or_404(Challan, id=challan_id)
    return generate_challan_pdf(challan)


# ===============================================================
# CLEAR PDF SESSION (Required for auto-download cleanup)
# ===============================================================
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
@login_required
def clear_pdf_session(request):
    request.session.pop("download_invoice", None)
    request.session.pop("download_payment", None)
    request.session.pop("download_return", None)
    request.session.pop("download_challan", None)
    return JsonResponse({"status": "cleared"})

