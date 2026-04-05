# billing/views.py
# ✅ COMPLETE - All errors fixed, all functionality preserved

from django.views import View
from django.views.generic import ListView, DetailView
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.contrib import messages
from django.db import transaction, IntegrityError, models
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db.models import Sum, Prefetch, Q, Count
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from django.core.exceptions import ValidationError
import logging
import json
import time
# Service Layer
from .services import InvoiceService, ReturnService, PaymentService
# PDF Generation

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from datetime import datetime, timedelta

from .models import (
    Invoice, InvoiceItem, Payment, Return, ReturnItem, Challan, ChallanItem, Balance
)
from .forms import (
    InvoiceForm, InvoiceItemFormSet, PaymentForm,
    ReturnForm, ChallanForm, ChallanItemFormSet, BalanceFormSet
)
from io import BytesIO
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable)
from django.http import HttpResponse

# Inventory Manager Integration
from core.inventory_manager import (
    check_stock_availability,
    deduct_items_for_invoice,
    add_items_for_return,
    update_items_for_invoice,
    restore_items_for_invoice_deletion
)
from party.models import Party
from party.utils import send_payment_receipt
from items.models import Item
# Service Layer

logger = logging.getLogger(__name__)


# ================================================================
# DECORATORS
# ================================================================

def login_required_cbv(view_class):
    """Decorator for class-based views requiring authentication"""
    return method_decorator(login_required, name='dispatch')(view_class)


# ================================================================
# HELPER FUNCTIONS
# ================================================================

                            # def calculate_item_totals(quantity, rate, gst_percent, discount_amount=0):
                            #     """
                            #     Calculate item totals with proper GST calculation.
                                
                            #     Args:
                            #         quantity: Item quantity
                            #         rate: Per-unit rate
                            #         gst_percent: GST percentage
                            #         discount_amount: Flat discount amount
                                
                            #     Returns:
                            #         dict with base_amount, gst_amount, discount_amount, total
                            #     """
                            #     try:
                            #         quantity = Decimal(str(quantity))
                            #         rate = Decimal(str(rate))
                            #         gst_percent = Decimal(str(gst_percent))
                            #         discount_amount = Decimal(str(discount_amount))
                                    
                            #         base_amount = (quantity * rate).quantize(Decimal('0.01'), ROUND_HALF_UP)
                            #         gst_amount = (base_amount * gst_percent / Decimal('100')).quantize(Decimal('0.01'), ROUND_HALF_UP)
                            #         total = (base_amount + gst_amount - discount_amount).quantize(Decimal('0.01'), ROUND_HALF_UP)
                                    
                            #         return {
                            #             'base_amount': base_amount,
                            #             'gst_amount': gst_amount,
                            #             'discount_amount': discount_amount,
                            #             'total': total
                            #         }
                            #     except (InvalidOperation, ValueError) as e:
                            #         logger.error(f"❌ Error calculating item totals: {e}")
                            #         raise ValidationError(f"Invalid calculation parameters: {e}")


                            # def check_and_close_invoice(invoice):
                            #     """
                            #     Check if invoice should be closed based on payments and returns.
                                
                            #     Args:
                            #         invoice: Invoice instance
                                
                            #     Returns:
                            #         bool: True if invoice was closed, False otherwise
                            #     """
                            #     try:
                            #         total_amount = invoice.total_amount or Decimal('0.00')
                            #         total_paid = invoice.total_paid or Decimal('0.00')
                            #         total_returns = sum(
                            #             r.amount for r in invoice.returns.filter(is_active=True)
                            #         ) if hasattr(invoice, 'returns') else Decimal('0.00')
                                    
                            #         balance = total_amount - total_paid - total_returns
                                    
                            #         if balance <= Decimal('0.00') and not invoice.is_paid:
                            #             invoice.is_paid = True
                            #             invoice.save(update_fields=['is_paid'])
                            #             logger.info(f"✅ Invoice {invoice.invoice_number} auto-closed. Balance: ₹{balance}")
                            #             return True
                                    
                            #         return False
                            #     except Exception as e:
                            #         logger.error(f"❌ Error checking invoice closure: {e}")
                            #         return False

# ================================================================
# WATERMARK
# ================================================================
 
WATERMARK_TEXT = (
    "All rights reserved | DarbarBootsPro App | "
    "Darbar Stores | Developed by Kshitiz Singh Tomar"
)
 
def _add_watermark(canv, doc):
    """
    Draws a faint diagonal watermark on every page.
    Called automatically by SimpleDocTemplate as an onPage callback.
    """
    width, height = A4
    canv.saveState()
    canv.setFont('Helvetica', 9)
    canv.setFillColor(colors.HexColor('#cccccc'))   # very light grey
    canv.setFillAlpha(0.35)                          # 35 % opacity
    canv.translate(width / 2, height / 2)
    canv.rotate(42)                                  # diagonal angle
    canv.drawCentredString(0, 0, WATERMARK_TEXT)
    canv.restoreState()
# ================================================================
# SHARED HEADER / FOOTER HELPERS
# ================================================================

def _build_store_header(elements, styles):
    """
    Builds the Darbar Stores letterhead block and appends it to `elements`.
    Layout:
        |OM SHANTI|                  (center, small italic)
        GST NO: ...  |  mob: ...     (left / right)
        DARBAR STORES                (center, large bold)
        main road Khirkiya DIST: Harda  (center)
        ─────────────────────────────── (divider)
    """
    # ── |OM SHANTI| ──────────────────────────────────────────────
    om_style = ParagraphStyle(
        'OmShanti',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#555555'),
        alignment=TA_CENTER,
        fontName='Helvetica-Oblique',
        spaceAfter=2,
    )
    elements.append(Paragraph('| OM SHANTI |', om_style))

    # ── GST (left) + Mob (right) in a two-column table ───────────
    gst_style = ParagraphStyle(
        'GSTLeft',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#333333'),
        alignment=TA_LEFT,
        fontName='Helvetica-Bold',
    )
    mob_style = ParagraphStyle(
        'MobRight',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#333333'),
        alignment=TA_RIGHT,
        fontName='Helvetica-Bold',
    )
    gst_mob_table = Table(
        [[Paragraph('GST NO: 23AVNPS8384N1ZQ', gst_style),
          Paragraph('Mob: 8871118384', mob_style)]],
        colWidths=[3.5 * inch, 3.5 * inch],
    )
    gst_mob_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(gst_mob_table)

    # ── DARBAR STORES (main heading) ─────────────────────────────
    store_name_style = ParagraphStyle(
        'StoreName',
        parent=styles['Heading1'],
        fontSize=22,
        textColor=colors.HexColor('#1a1a1a'),
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        spaceBefore=4,
        spaceAfter=0,
    )
    elements.append(Paragraph('DARBAR STORES', store_name_style))

    # ── Address (sub-heading) ─────────────────────────────────────
    address_style = ParagraphStyle(
        'StoreAddress',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#444444'),
        alignment=TA_CENTER,
        fontName='Helvetica',
        spaceAfter=6,
    )
    elements.append(Paragraph('Main Road Khirkiya, DIST: Harda', address_style))

    # ── Divider ───────────────────────────────────────────────────
    elements.append(HRFlowable(
        width='100%', thickness=1.5,
        color=colors.HexColor('#333333'),
        spaceAfter=8,
    ))


def _build_store_footer(elements, styles):
    """
    Appends the terms/disclaimer footer block to `elements`.
    """
    # Divider above footer
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(HRFlowable(
        width='100%', thickness=1,
        color=colors.HexColor('#aaaaaa'),
        spaceBefore=4, spaceAfter=6,
    ))

    terms = [
        '* No Guarantee &amp; No Warranty',
        '* No Change &amp; No Exchange',
        '* Subject To Khirkiya Jurisdiction',
        '* E &amp; O.E',
    ]
    terms_style = ParagraphStyle(
        'TermsStyle',
        parent=styles['Normal'],
        fontSize=7.5,
        textColor=colors.HexColor('#555555'),
        alignment=TA_CENTER,
        fontName='Helvetica',
        leading=11,
    )
    elements.append(Paragraph('&nbsp;&nbsp;&nbsp;'.join(terms), terms_style))


# ================================================================
# PDF GENERATION FUNCTIONS
# ================================================================

def generate_invoice_pdf(invoice):
    """Generate professional PDF invoice with complete styling."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )
    elements = []
    styles = getSampleStyleSheet()

    # ── Letterhead ────────────────────────────────────────────────
    _build_store_header(elements, styles)

    # ── Document-specific title ───────────────────────────────────
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#00c2ff'),
        spaceAfter=10,
        spaceBefore=4,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    )
    heading_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=11,
        textColor=colors.HexColor('#0099cc'),
        spaceAfter=6,
        fontName='Helvetica-Bold',
    )
    right_align_style = ParagraphStyle(
        'RightAlign',
        parent=styles['Normal'],
        alignment=TA_RIGHT,
    )

    elements.append(Paragraph('WHOLESALE INVOICE', title_style))
    elements.append(Spacer(1, 0.2 * inch))

    # Invoice Info
    invoice_info = [
        ['Invoice No:', invoice.invoice_number, 'Date:', invoice.date.strftime('%d %b %Y')],
        ['Status:', 'PAID' if invoice.is_paid else 'PENDING', '', ''],
    ]
    invoice_table = Table(invoice_info, colWidths=[1.5 * inch, 2.5 * inch, 1 * inch, 1.5 * inch])
    invoice_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#666666')),
        ('TEXTCOLOR', (2, 0), (2, -1), colors.HexColor('#666666')),
    ]))
    elements.append(invoice_table)
    elements.append(Spacer(1, 0.3 * inch))

    # Bill To
    elements.append(Paragraph('BILL TO', heading_style))
    party_data = [
        ['Party Name:', invoice.party.name],
        ['Phone:', invoice.party.phone or 'N/A'],
        ['Email:', getattr(invoice.party, 'email', None) or 'N/A'],
    ]
    party_table = Table(party_data, colWidths=[1.5 * inch, 5 * inch])
    party_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#666666')),
    ]))
    elements.append(party_table)
    elements.append(Spacer(1, 0.3 * inch))

    # Items Table
    elements.append(Paragraph('ITEMS', heading_style))
    items_data = [['#', 'Item', 'Qty', 'Rate', 'GST', 'Discount', 'Total']]
    for idx, item in enumerate(invoice.invoice_items.filter(is_active=True), 1):
        items_data.append([
            str(idx),
            item.item.name[:30] if item.item else 'Manual Item',
            str(item.quantity),
            f'\u20b9{item.rate:,.2f}',
            f'\u20b9{item.gst_amount:,.2f}',
            f'\u20b9{item.discount_amount:,.2f}',
            f'\u20b9{item.total:,.2f}',
        ])

    total_amount = sum(item.total for item in invoice.invoice_items.filter(is_active=True))
    items_data.append(['', '', '', '', '', 'TOTAL:', f'\u20b9{total_amount:,.2f}'])

    items_table = Table(
        items_data,
        colWidths=[0.4 * inch, 2.5 * inch, 0.7 * inch, 1 * inch, 1 * inch, 1 * inch, 1.2 * inch],
    )
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
    elements.append(Spacer(1, 0.3 * inch))

    # Payment Summary
    elements.append(Paragraph('PAYMENT SUMMARY', heading_style))
    total_paid = sum(payment.amount for payment in invoice.payments.filter(is_active=True))
    balance = total_amount - total_paid

    summary_data = [
        ['Invoice Total:', f'\u20b9{total_amount:,.2f}'],
        ['Amount Paid:', f'\u20b9{total_paid:,.2f}'],
        ['Balance Due:', f'\u20b9{balance:,.2f}'],
    ]
    summary_table = Table(summary_data, colWidths=[4.5 * inch, 2 * inch])
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -2), 10),
        ('FONTSIZE', (0, -1), (-1, -1), 12),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f0f0f0')),
        ('LINEABOVE', (0, -1), (-1, -1), 2, colors.HexColor('#00c2ff')),
    ]))
    elements.append(summary_table)

    # Generated-on line
    elements.append(Spacer(1, 0.2 * inch))
    footer_text = f"Generated on {datetime.now().strftime('%d %b %Y at %I:%M %p')}"
    elements.append(Paragraph(footer_text, right_align_style))
    elements.append(Paragraph('Thank you for your business!', styles['Normal']))

    # ── Store footer ──────────────────────────────────────────────
    _build_store_footer(elements, styles)

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    filename = (
        f'Invoice_{invoice.invoice_number.replace("/", "-")}'
        f'_{invoice.party.name.replace(" ", "_")}.pdf'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ----------------------------------------------------------------

def generate_payment_receipt_pdf(payment):
    """Generate professional PDF payment receipt."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )
    elements = []
    styles = getSampleStyleSheet()

    _build_store_header(elements, styles)

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#28a745'),
        spaceAfter=10,
        spaceBefore=4,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    )
    heading_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=11,
        textColor=colors.HexColor('#34d058'),
        spaceAfter=6,
        fontName='Helvetica-Bold',
    )
    right_align_style = ParagraphStyle(
        'RightAlign',
        parent=styles['Normal'],
        alignment=TA_RIGHT,
    )

    elements.append(Paragraph('PAYMENT RECEIPT', title_style))
    elements.append(Spacer(1, 0.2 * inch))

    payment_num = payment.payment_number or f'PAY-{payment.id}'
    receipt_info = [
        ['Receipt No:', payment_num, 'Date:', payment.date.strftime('%d %b %Y')],
    ]
    receipt_table = Table(receipt_info, colWidths=[1.5 * inch, 2 * inch, 1 * inch, 2 * inch])
    receipt_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
    ]))
    elements.append(receipt_table)
    elements.append(Spacer(1, 0.3 * inch))

    elements.append(Paragraph('RECEIVED FROM', heading_style))
    party_data = [
        ['Party Name:', payment.party.name],
        ['Phone:', payment.party.phone or 'N/A'],
        ['Email:', getattr(payment.party, 'email', None) or 'N/A'],
    ]
    party_table = Table(party_data, colWidths=[1.5 * inch, 5 * inch])
    party_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
    ]))
    elements.append(party_table)
    elements.append(Spacer(1, 0.3 * inch))

    elements.append(Paragraph('PAYMENT DETAILS', heading_style))
    payment_data = [
        ['Description', 'Amount'],
        [
            f'Payment for {f"Invoice #{payment.invoice.invoice_number}" if payment.invoice else "General Payment"}',
            f'\u20b9{payment.amount:,.2f}',
        ],
        ['Payment Mode:', payment.get_mode_display()],
    ]
    if payment.notes:
        payment_data.append(['Notes:', payment.notes[:100]])

    payment_table = Table(payment_data, colWidths=[4 * inch, 2.5 * inch])
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
    elements.append(Spacer(1, 0.3 * inch))

    total_data = [['TOTAL AMOUNT RECEIVED', f'\u20b9{payment.amount:,.2f}']]
    total_table = Table(total_data, colWidths=[4 * inch, 2.5 * inch])
    total_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#34d058')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 14),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 15),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
    ]))
    elements.append(total_table)

    elements.append(Spacer(1, 0.2 * inch))
    footer_text = f"Generated on {datetime.now().strftime('%d %b %Y at %I:%M %p')}"
    elements.append(Paragraph(footer_text, right_align_style))
    elements.append(Paragraph('Thank you for your payment!', styles['Normal']))

    _build_store_footer(elements, styles)

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    filename = f'Payment_Receipt_{payment_num}_{payment.party.name.replace(" ", "_")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ----------------------------------------------------------------

def generate_return_receipt_pdf(return_obj):
    """Generate professional PDF return receipt."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )
    elements = []
    styles = getSampleStyleSheet()

    _build_store_header(elements, styles)

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#dc3545'),
        spaceAfter=10,
        spaceBefore=4,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    )
    heading_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=11,
        textColor=colors.HexColor('#e74c3c'),
        spaceAfter=6,
        fontName='Helvetica-Bold',
    )
    right_align_style = ParagraphStyle(
        'RightAlign',
        parent=styles['Normal'],
        alignment=TA_RIGHT,
    )

    elements.append(Paragraph('RETURN RECEIPT', title_style))
    elements.append(Spacer(1, 0.2 * inch))

    return_num = return_obj.return_number or f'RET-{return_obj.id}'
    return_info = [
        ['Return No:', return_num, 'Date:', return_obj.return_date.strftime('%d %b %Y')],
        ['Invoice:', return_obj.invoice.invoice_number, '', ''],
    ]
    return_table = Table(return_info, colWidths=[1.5 * inch, 2 * inch, 1 * inch, 2 * inch])
    return_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('SPAN', (1, 1), (-1, 1)),
    ]))
    elements.append(return_table)
    elements.append(Spacer(1, 0.3 * inch))

    elements.append(Paragraph('RETURN FROM', heading_style))
    party_data = [
        ['Party Name:', return_obj.party.name],
        ['Phone:', return_obj.party.phone or 'N/A'],
        ['Email:', getattr(return_obj.party, 'email', None) or 'N/A'],
    ]
    party_table = Table(party_data, colWidths=[1.5 * inch, 5 * inch])
    party_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
    ]))
    elements.append(party_table)
    elements.append(Spacer(1, 0.3 * inch))

    elements.append(Paragraph('RETURN DETAILS', heading_style))
    return_data = [
        ['Description', 'Amount'],
        [f'Return for Invoice #{return_obj.invoice.invoice_number}', f'\u20b9{return_obj.amount:,.2f}'],
    ]
    if return_obj.reason:
        return_data.append(['Reason:', return_obj.reason[:100]])

    return_details_table = Table(return_data, colWidths=[4 * inch, 2.5 * inch])
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
    elements.append(Spacer(1, 0.3 * inch))

    total_data = [['TOTAL RETURN AMOUNT', f'\u20b9{return_obj.amount:,.2f}']]
    total_table = Table(total_data, colWidths=[4 * inch, 2.5 * inch])
    total_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e74c3c')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 14),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 15),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
    ]))
    elements.append(total_table)

    elements.append(Spacer(1, 0.2 * inch))
    footer_text = f"Generated on {datetime.now().strftime('%d %b %Y at %I:%M %p')}"
    elements.append(Paragraph(footer_text, right_align_style))
    elements.append(Paragraph('Return processed successfully.', styles['Normal']))

    _build_store_footer(elements, styles)

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    filename = f'Return_Receipt_{return_num}_{return_obj.party.name.replace(" ", "_")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ----------------------------------------------------------------

def generate_challan_pdf(challan):
    """Generate professional PDF challan (delivery note)."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )
    elements = []
    styles = getSampleStyleSheet()

    _build_store_header(elements, styles)

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#6f42c1'),
        spaceAfter=10,
        spaceBefore=4,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    )
    heading_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=11,
        textColor=colors.HexColor('#8e44ad'),
        spaceAfter=6,
        fontName='Helvetica-Bold',
    )
    right_align_style = ParagraphStyle(
        'RightAlign',
        parent=styles['Normal'],
        alignment=TA_RIGHT,
    )

    elements.append(Paragraph('DELIVERY CHALLAN', title_style))
    elements.append(Spacer(1, 0.2 * inch))

    challan_num = challan.challan_number or f'CHN-{challan.id}'
    challan_info = [
        ['Challan No:', challan_num, 'Date:', challan.date.strftime('%d %b %Y')],
    ]
    if challan.invoice:
        challan_info.append(['Invoice No:', challan.invoice.invoice_number, '', ''])

    challan_table = Table(challan_info, colWidths=[1.5 * inch, 2.5 * inch, 1 * inch, 1.5 * inch])
    table_style_list = [
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
    ]
    if challan.invoice:
        table_style_list.append(('SPAN', (1, 1), (-1, 1)))
    challan_table.setStyle(TableStyle(table_style_list))
    elements.append(challan_table)
    elements.append(Spacer(1, 0.3 * inch))

    elements.append(Paragraph('DELIVER TO', heading_style))
    party_data = [
        ['Party Name:', challan.party.name],
        ['Phone:', challan.party.phone or 'N/A'],
        ['Email:', getattr(challan.party, 'email', None) or 'N/A'],
    ]
    party_table = Table(party_data, colWidths=[1.5 * inch, 5 * inch])
    party_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
    ]))
    elements.append(party_table)
    elements.append(Spacer(1, 0.3 * inch))

    elements.append(Paragraph('ITEMS', heading_style))
    items_data = [['#', 'Item Name', 'Quantity']]
    for idx, item in enumerate(challan.challan_items.filter(is_active=True), 1):
        items_data.append([
            str(idx),
            item.item.name if item.item else 'N/A',
            str(item.quantity),
        ])

    items_table = Table(items_data, colWidths=[0.5 * inch, 5 * inch, 1.5 * inch])
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
    elements.append(Spacer(1, 0.3 * inch))

    if challan.transport_details:
        elements.append(Paragraph('TRANSPORT DETAILS', heading_style))
        elements.append(Paragraph(challan.transport_details, styles['Normal']))
        elements.append(Spacer(1, 0.3 * inch))

    footer_text = f"Generated on {datetime.now().strftime('%d %b %Y at %I:%M %p')}"
    elements.append(Paragraph(footer_text, right_align_style))
    elements.append(Paragraph('Thank you for your business!', styles['Normal']))

    _build_store_footer(elements, styles)

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    filename = (
        f'Challan_{challan_num.replace("/", "-")}'
        f'_{challan.party.name.replace(" ", "_")}.pdf'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response




# ================================================================
# INVOICE LIST VIEW
# ================================================================

@login_required_cbv
class InvoiceListView(ListView):
    """
    Display list of all active invoices with search and auto-closure.
    """
    model = Invoice
    template_name = 'billing/invoice_list.html'
    context_object_name = 'invoice_data'
    ordering = ['-date', '-invoice_number']
    paginate_by = 50

    def get_queryset(self):
        """Get active invoices with optimized related data fetching"""
        queryset = Invoice.objects.filter(
            is_active=True
        ).select_related(
            'party', 
            'created_by', 
            'updated_by'
        ).prefetch_related(
            Prefetch(
                'invoice_items',
                queryset=InvoiceItem.objects.filter(is_active=True)
            ),
            Prefetch(
                'payments',
                queryset=Payment.objects.filter(is_active=True)
            ),
            Prefetch(
                'returns',
                queryset=Return.objects.filter(is_active=True)
            )
        )
        
        # Apply search filter if provided
        search_query = self.request.GET.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(invoice_number__icontains=search_query) |
                Q(party__name__icontains=search_query) |
                Q(party__phone__icontains=search_query)
            )
        
        return queryset
    
    def get_context_data(self, **kwargs):
        """Add search query and auto-close fully paid invoices"""
        context = super().get_context_data(**kwargs)
        
        # Auto-close fully paid invoices
        for invoice in context['invoice_data']:
            InvoiceService.check_and_close_invoice(invoice)
        
        context['search_query'] = self.request.GET.get('search', '')
        
        return context


# ================================================================
# INVOICE DETAIL VIEW
# ================================================================

@login_required_cbv
class InvoiceDetailView(DetailView):
    """
    Display detailed invoice information with all related data.
    """
    model = Invoice
    template_name = 'billing/invoice_detail.html'
    pk_url_kwarg = 'invoice_id'
    context_object_name = 'invoice'

    def get_queryset(self):
        """Get invoice with all related data optimized"""
        return Invoice.objects.filter(
            is_active=True
        ).select_related(
            'party', 
            'created_by', 
            'updated_by'
        ).prefetch_related(
            Prefetch(
                'invoice_items',
                queryset=InvoiceItem.objects.filter(is_active=True).select_related('item')
            ),
            Prefetch(
                'payments',
                queryset=Payment.objects.filter(is_active=True)
            ),
            Prefetch(
                'returns',
                queryset=Return.objects.filter(is_active=True)
            )
        )

    def get_context_data(self, **kwargs):
        """Add calculated totals and status to context"""
        context = super().get_context_data(**kwargs)
        invoice = context['invoice']
        
        # Auto-close if fully paid (using service)
        InvoiceService.check_and_close_invoice(invoice)
        invoice.refresh_from_db()
        
        # Calculate all totals
        total_paid = invoice.total_paid or Decimal('0.00')
        total_returns = sum(
            r.amount for r in invoice.returns.filter(is_active=True)
        )
        balance_due = invoice.balance_due or Decimal('0.00')
        
        # Ensure non-negative balance
        if balance_due < Decimal('0.00'):
            balance_due = Decimal('0.00')
        
        # Add to context
        context.update({
            'items': invoice.invoice_items.filter(is_active=True),
            'payments': invoice.payments.filter(is_active=True).order_by('-date'),
            'returns': invoice.returns.filter(is_active=True).order_by('-return_date'),
            'total_paid': total_paid,
            'balance_due': balance_due,
            'total_returns': total_returns,
            'status': 'Closed' if invoice.is_paid else 'Open'
        })
        
        return context


# ================================================================
# INVOICE CREATE VIEW
# ================================================================

@login_required_cbv
class InvoiceCreateView(View):
    """
    Create new wholesale invoice with automatic inventory deduction.
    """
    template_name = 'billing/create_invoice.html'

    def generate_invoice_number(self):
        """
        Generate unique invoice number with WHSL prefix.
        Format: WHSL-INV-YYYY-NNNN-TTTT
        """
        year = timezone.now().year
        prefix = f"WHSL-INV-{year}-"
        
        last_invoice = Invoice.objects.filter(
            invoice_number__startswith=prefix
        ).order_by("-id").first()
        
        next_num = 1
        if last_invoice and last_invoice.invoice_number:
            try:
                parts = last_invoice.invoice_number.replace(prefix, '').split('-')
                next_num = int(parts[0]) + 1
            except (ValueError, IndexError):
                logger.warning(f"Could not parse last invoice number: {last_invoice.invoice_number}")
                pass
        
        timestamp = timezone.now().strftime('%f')[:4]
        return f"{prefix}{next_num:04d}-{timestamp}"

    @transaction.atomic
    def get(self, request):
        """Display invoice creation form"""
        auto_invoice_number = self.generate_invoice_number()
        
        form = InvoiceForm(initial={
            'is_limit_enabled': False,
            'limit_amount': 0,
            'invoice_number': auto_invoice_number
        })
        
        # Make invoice number readonly
        form.fields['invoice_number'].widget.attrs['readonly'] = True
        
        formset = InvoiceItemFormSet()
        
        # Get active parties for dropdown
        parties = list(Party.objects.filter(is_active=True).values('id', 'name', 'phone'))
        
        return render(request, self.template_name, {
            'form': form,
            'formset': formset,
            'parties': json.dumps(parties),
        })

    @transaction.atomic
    def post(self, request):
        """
        REFACTORED: Process invoice creation using service layer.
        All business logic delegated to InvoiceService.
        """
        form = InvoiceForm(request.POST)
        formset = InvoiceItemFormSet(request.POST)

        # Get optional flags
        send_whatsapp = request.POST.get('send_whatsapp') == 'on'
        download_pdf = request.POST.get('download_pdf') == 'on'

        # Validate form
        if not form.is_valid():
            messages.error(request, f'Form errors: {form.errors}')
            parties = list(Party.objects.filter(is_active=True).values('id', 'name', 'phone'))
            return render(request, self.template_name, {
                'form': form,
                'formset': formset,
                'parties': json.dumps(parties),
            })

        # ========================================
        # STEP 1: Parse and validate invoice items
        # ========================================
        valid_items = []
        formset_errors = []
        
        for i, f in enumerate(formset.forms):
            prefix = f'{formset.prefix}-{i}'
            item_id = request.POST.get(f'{prefix}-item', '').strip()
            new_item_name = request.POST.get(f'{prefix}-new_item_name', '').strip()
            qty = request.POST.get(f'{prefix}-quantity', '').strip()
            rate = request.POST.get(f'{prefix}-rate', '').strip()

            # Skip completely empty rows
            if not any([item_id, new_item_name, qty, rate]):
                continue
            
            # Validate item selection
            if not (item_id or new_item_name):
                formset_errors.append(f"Row {i+1}: Select an item or enter new item name")
                continue
            
            # Validate quantity
            try:
                if not qty or float(qty) <= 0:
                    formset_errors.append(f"Row {i+1}: Quantity must be greater than zero")
                    continue
            except ValueError:
                formset_errors.append(f"Row {i+1}: Quantity must be a valid number")
                continue
            
            # Validate rate
            try:
                if not rate or float(rate) <= 0:
                    formset_errors.append(f"Row {i+1}: Rate must be greater than zero")
                    continue
            except ValueError:
                formset_errors.append(f"Row {i+1}: Rate must be a valid number")
                continue

            # Add to valid items
            valid_items.append({
                'item_id': item_id,
                'new_item_name': new_item_name,
                'quantity': int(float(qty)),
                'rate': Decimal(rate),
                'gst_amount': Decimal(request.POST.get(f'{prefix}-gst_amount', '0')),
                'discount_amount': Decimal(request.POST.get(f'{prefix}-discount_amount', '0')),
            })

        # Display formset errors
        if formset_errors:
            for error in formset_errors:
                messages.error(request, error)
            parties = list(Party.objects.filter(is_active=True).values('id', 'name', 'phone'))
            return render(request, self.template_name, {
                'form': form,
                'formset': formset,
                'parties': json.dumps(parties),
            })

        # Ensure at least one item
        if not valid_items:
            messages.error(request, "Please add at least one item to the invoice.")
            parties = list(Party.objects.filter(is_active=True).values('id', 'name', 'phone'))
            return render(request, self.template_name, {
                'form': form,
                'formset': formset,
                'parties': json.dumps(parties),
            })

        try:
            # ========================================
            # STEP 2: Handle party creation
            # ========================================
            new_party_name = form.cleaned_data.get('new_party_name', '').strip()
            if new_party_name:
                party, created = Party.objects.get_or_create(
                    name__iexact=new_party_name,
                    defaults={
                        'name': new_party_name,
                        'phone': form.cleaned_data.get('new_party_phone', ''),
                        'created_by': request.user
                    }
                )
                if created:
                    logger.info(f"✨ New party created: {party.name}")
            else:
                party = form.cleaned_data.get('party')

            if not party:
                messages.error(request, "Please select or create a party.")
                raise ValueError("Missing party")

            # ========================================
            # STEP 3: Process items (get/create Item objects)
            # ========================================
            items_data = []
            items_for_stock_check = []
            
            for item_info in valid_items:
                # Get or create item object
                if item_info['item_id']:
                    try:
                        item_obj = Item.objects.get(id=item_info['item_id'])
                    except Item.DoesNotExist:
                        messages.error(request, f"Item with ID {item_info['item_id']} not found.")
                        raise ValueError(f"Item not found: {item_info['item_id']}")
                else:
                    # Create new item
                    item_obj, created = Item.objects.get_or_create(
                        name__iexact=item_info['new_item_name'],
                        defaults={
                            'name': item_info['new_item_name'],
                            'price_retail': item_info['rate'],
                            'price_wholesale': item_info['rate'],
                            'gst_percent': Decimal('0.00'),
                            'created_by': request.user
                        }
                    )
                    if created:
                        logger.info(f"✨ New item created: {item_obj.name}")
                
                items_data.append({
                    'item': item_obj,
                    'quantity': item_info['quantity'],
                    'rate': item_info['rate'],
                    'discount_amount': item_info['discount_amount']
                })
                
                # Track for stock check
                if item_obj:
                    items_for_stock_check.append({
                        'item_id': item_obj.id,
                        'quantity': item_info['quantity']
                    })

            # ========================================
            # STEP 4: PRE-CHECK STOCK AVAILABILITY
            # ========================================
            if items_for_stock_check:
                logger.info(f"🔍 Pre-checking stock for {len(items_for_stock_check)} item(s)")
                available, errors = InvoiceService.validate_stock_availability(items_for_stock_check)
                
                if not available:
                    # ✅ FIXED: Show detailed stock errors without generic wrapper
                    messages.error(
                        request, 
                        "❌ INSUFFICIENT STOCK - Cannot create invoice with the following items:"
                    )
                    for error in errors:
                        messages.error(request, f"   • {error}")
                    
                    # ✅ Don't raise exception - just return to form with errors
                    parties = list(Party.objects.filter(is_active=True).values('id', 'name', 'phone'))
                    return render(request, self.template_name, {
                        'form': form,
                        'formset': formset,
                        'parties': json.dumps(parties),
                    })
                
                logger.info(f"✅ Stock availability confirmed")

            # ========================================
            # STEP 5: Calculate total and validate limit
            # ========================================
            total_amount = Decimal('0.00')
            for item_data in items_data:
                gst_percent = item_data['item'].gst_percent or Decimal('0.00')
                calculated = InvoiceService.calculate_item_totals(
                    quantity=item_data['quantity'],
                    rate=item_data['rate'],
                    gst_percent=gst_percent,
                    discount_amount=item_data['discount_amount']
                )
                total_amount += calculated['total']
            
            # Validate invoice limit
            is_limit_enabled = form.cleaned_data.get('is_limit_enabled', False)
            limit_amount = form.cleaned_data.get('limit_amount') or Decimal('0.00')
            
            if is_limit_enabled and total_amount > limit_amount:
                messages.error(
                    request,
                    f"❌ Invoice limit exceeded. Limit: ₹{limit_amount:.2f}, "
                    f"Calculated Total: ₹{total_amount:.2f}"
                )
                raise ValueError("Invoice limit exceeded")

            # ========================================
            # STEP 6: CREATE INVOICE (using service)
            # ========================================
            invoice_data = {
                'party': party,
                'date': form.cleaned_data['date'],
                'is_limit_enabled': is_limit_enabled,
                'limit_amount': limit_amount,
                'invoice_number': form.cleaned_data.get('invoice_number') or self.generate_invoice_number()
            }
            
            invoice = InvoiceService.create_invoice_with_items(
                invoice_data=invoice_data,
                items_data=items_data,
                user=request.user
            )

            # ========================================
            # STEP 7: Success
            # ========================================
            success_msg = (
                f'✅ Invoice {invoice.invoice_number} created successfully '
                f'with {len(items_data)} item(s). '
                f'Stock deducted for {len(items_for_stock_check)} tracked item(s).'
            )
            messages.success(request, success_msg)
            
            # WhatsApp notification (optional)
            if send_whatsapp and invoice.party.phone:
                try:
                    # Implement your WhatsApp logic here
                    logger.info(f"📱 WhatsApp invoice sent to {invoice.party.name}")
                except Exception as e:
                    logger.warning(f"WhatsApp send failed: {e}")
                    messages.warning(request, "Invoice created but WhatsApp send failed.")
            
            # PDF download redirect
            if download_pdf:
                return redirect(f"/billing/invoices/{invoice.id}/?download=1")
            
            return redirect('billing:invoice_detail', invoice_id=invoice.id)

        except ValueError as ve:
            logger.error(f"Validation error: {ve}", exc_info=True)
            messages.error(request, f"Validation Error: {ve}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            messages.error(request, f"An unexpected error occurred: {str(e)}")

        # Return form with errors
        parties = list(Party.objects.filter(is_active=True).values('id', 'name', 'phone'))
        items = list(Item.objects.filter().values('id', 'name'))
        return render(request, self.template_name, {
            'form': form,
            'formset': formset,
            'parties': json.dumps(parties),
            'items': json.dumps(items),
        })


# ================================================================
# INVOICE UPDATE VIEW
# ================================================================

@login_required_cbv
class InvoiceUpdateView(View):
    """
    Update existing invoice with automatic inventory adjustment.
    """
    template_name = 'billing/edit_invoice.html'

    @transaction.atomic
    def get(self, request, invoice_id):
        """Display invoice edit form with existing data"""
        invoice = get_object_or_404(Invoice, id=invoice_id, is_active=True)
        
        form = InvoiceForm(instance=invoice)
        formset = InvoiceItemFormSet(instance=invoice)
        
        # Get active parties for dropdown
        parties = list(Party.objects.filter(is_active=True).values('id', 'name', 'phone'))
        
        return render(request, self.template_name, {
            'form': form,
            'formset': formset,
            'invoice': invoice,
            'parties': json.dumps(parties)
        })


    @transaction.atomic
    def post(self, request, invoice_id):
        """
        REFACTORED: Process invoice update using service layer.
        """
        invoice = get_object_or_404(Invoice, id=invoice_id, is_active=True)
        
        form = InvoiceForm(request.POST, instance=invoice)
        formset = InvoiceItemFormSet(request.POST, instance=invoice)

        if not (form.is_valid() and formset.is_valid()):
            messages.error(request, 'Please correct the form errors.')
            parties = list(Party.objects.filter(is_active=True).values('id', 'name', 'phone'))
            return render(request, self.template_name, {
                'form': form,
                'formset': formset,
                'invoice': invoice,
                'parties': json.dumps(parties)
            })

        try:
            # ========================================
            # STEP 1: Capture ORIGINAL items
            # ========================================
            original_items_map = {}
            for item_obj in invoice.invoice_items.filter(is_active=True):
                if item_obj.item:
                    item_id = item_obj.item.id
                    original_items_map[item_id] = original_items_map.get(item_id, 0) + int(item_obj.quantity)

            original_items = [
                {'item_id': k, 'quantity': v}
                for k, v in original_items_map.items()
            ]

            logger.info(f"📊 Original items for invoice {invoice.invoice_number}: {len(original_items)}")

            # ========================================
            # STEP 2: Save form changes
            # ========================================
            invoice = form.save(commit=False)
            invoice.updated_by = request.user
            
            total = Decimal('0.00')
            items = formset.save(commit=False)

            # Process each item
            for item in items:
                # Handle new item creation via inline form field
                if not item.item and hasattr(item, 'new_item_name'):
                    name = item.new_item_name.strip()
                    if name:
                        item.item, created = Item.objects.get_or_create(
                            name__iexact=name,
                            defaults={
                                'name': name,
                                'price_retail': item.rate,
                                'price_wholesale': item.rate,
                                'gst_percent': Decimal('0.00'),
                                'created_by': request.user
                            }
                        )
                        if created:
                            logger.info(f"✨ New item created during update: {item.item.name}")

                # Recalculate totals
                if item.item:
                    gst_percent = item.item.gst_percent or Decimal('0.00')
                    calculated = InvoiceService.calculate_item_totals(
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

            # Delete removed items
            for obj in formset.deleted_objects:
                logger.info(f"🗑️ Deleting invoice item: {obj}")
                obj.delete()

            # ========================================
            # STEP 3: Capture UPDATED items
            # ========================================
            updated_items_map = {}
            for item in items:
                if item.item:
                    item_id = item.item.id
                    updated_items_map[item_id] = updated_items_map.get(item_id, 0) + int(item.quantity)

            updated_items = [
                {'item_id': k, 'quantity': v}
                for k, v in updated_items_map.items()
            ]

            logger.info(f"📊 Updated items for invoice {invoice.invoice_number}: {len(updated_items)}")

            # ========================================
            # STEP 4: Adjust stock (using service)
            # ========================================
            if original_items or updated_items:
                logger.info(f"🔄 Adjusting stock for invoice {invoice.invoice_number}...")
                
                InvoiceService.update_invoice_items(
                    invoice=invoice,
                    original_items=original_items,
                    updated_items=updated_items,
                    user=request.user
                )

            # ========================================
            # STEP 5: Update invoice totals
            # ========================================
            invoice.base_amount = total
            invoice.save()

            # Check if invoice should be auto-closed
            InvoiceService.check_and_close_invoice(invoice)

            # ========================================
            # STEP 6: Success
            # ========================================
            success_msg = f'✅ Invoice {invoice.invoice_number} updated successfully.'
            if original_items or updated_items:
                success_msg += ' Inventory adjusted automatically.'

            messages.success(request, success_msg)
            return redirect('billing:invoice_detail', invoice_id=invoice.id)

        except Exception as e:
            logger.error(f"❌ Error updating invoice {invoice_id}: {e}", exc_info=True)
            messages.error(request, f'Error updating invoice: {str(e)}')
            parties = list(Party.objects.filter(is_active=True).values('id', 'name', 'phone'))
            return render(request, self.template_name, {
                'form': form,
                'formset': formset,
                'invoice': invoice,
                'parties': json.dumps(parties)
            })


# ================================================================
# INVOICE DELETE VIEW
# ================================================================
@login_required
@transaction.atomic
def invoice_delete(request, invoice_id):
    """
    ✅ ENHANCED: Soft-delete invoice with comprehensive stock restoration
    and proper handling of related records (payments, returns).
    """
    # Get invoice or 404
    invoice = get_object_or_404(
        Invoice.objects.select_related('party').prefetch_related('invoice_items__item'),
        id=invoice_id,
        is_active=True
    )
    
    # ==================== GET: Show confirmation page ====================
    if request.method == 'GET':
        # Count items for display
        total_items = invoice.invoice_items.filter(is_active=True).count()
        tracked_items = invoice.invoice_items.filter(
            is_active=True,
            item__isnull=False
        ).count()
        
        context = {
            'invoice': invoice,
            'total_items_count': total_items,
            'tracked_items_count': tracked_items,
        }
        
        return render(request, 'billing/confirm_delete_invoice.html', context)
    
    # ==================== POST: Process deletion ====================
    if request.method == 'POST':
        try:
            logger.info(f"🗑️ Starting deletion for Invoice {invoice.invoice_number}")
            
            # Step 1: Check if invoice has payments/returns
            has_payments = invoice.payments.filter(is_active=True).exists()
            has_returns = invoice.returns.filter(is_active=True).exists()
            
            if has_payments or has_returns:
                warning_parts = []
                if has_payments:
                    payment_count = invoice.payments.filter(is_active=True).count()
                    warning_parts.append(f"{payment_count} payment(s)")
                if has_returns:
                    return_count = invoice.returns.filter(is_active=True).count()
                    warning_parts.append(f"{return_count} return(s)")
                
                warning_msg = f"This invoice has {' and '.join(warning_parts)}. These will also be marked as inactive."
                messages.warning(request, warning_msg)
            
            # Step 2: Collect items for stock restoration
            items_to_restore = []
            
            for inv_item in invoice.invoice_items.filter(is_active=True):
                if inv_item.item:  # Only restore tracked items
                    items_to_restore.append({
                        'item_id': inv_item.item.id,
                        'quantity': int(inv_item.quantity)
                    })
            
            logger.info(f"📦 Found {len(items_to_restore)} items to restore stock")
            
            # Step 3: Restore stock
            if items_to_restore:
                stock_result = restore_items_for_invoice_deletion(
                    invoice_items=items_to_restore,
                    invoice_type='wholesale',
                    invoice_id=invoice.id,
                    created_by=request.user
                )
                
                if not stock_result['success']:
                    raise ValidationError(
                        f"Stock restoration failed: {', '.join(stock_result['errors'])}"
                    )
                
                logger.info(f"✅ Stock restored for {len(stock_result['items_processed'])} items")
            else:
                logger.info("ℹ️ No tracked items to restore stock")
            
            # Step 4: Soft-delete related records
            # Delete invoice items
            deleted_items = invoice.invoice_items.filter(is_active=True).update(
                is_active=False,
                updated_by=request.user
            )
            
            # Delete related payments
            deleted_payments = invoice.payments.filter(is_active=True).update(
                is_active=False,
                updated_by=request.user
            )
            
            # Delete related returns (and their items)
            for return_obj in invoice.returns.filter(is_active=True):
                return_obj.return_items.filter(is_active=True).update(
                    is_active=False,
                    updated_by=request.user
                )
                return_obj.is_active = False
                return_obj.updated_by = request.user
                return_obj.save()
            
            deleted_returns = invoice.returns.filter(is_active=False).count()
            
            # Step 5: Soft-delete invoice
            invoice.is_active = False
            invoice.updated_by = request.user
            invoice.save()
            
            logger.info(f"✅ Invoice {invoice.invoice_number} soft-deleted successfully")
            
            # Step 6: Success message
            success_msg = (
                f'✅ Invoice {invoice.invoice_number} deleted successfully! '
                f'({deleted_items} items, {deleted_payments} payments, {deleted_returns} returns)'
            )
            
            if items_to_restore:
                success_msg += f' Stock restored for {len(items_to_restore)} item(s).'
            
            messages.success(request, success_msg)
            
            # Redirect to invoice list
            return redirect('billing:invoice_list')
            
        except ValidationError as ve:
            logger.error(f"❌ Validation error during deletion: {ve}")
            messages.error(request, f"Deletion failed: {str(ve)}")
            return redirect('billing:invoice_detail', invoice_id=invoice.id)
            
        except Exception as e:
            logger.error(f"❌ Unexpected error during deletion: {e}", exc_info=True)
            messages.error(request, f"An unexpected error occurred: {str(e)}")
            return redirect('billing:invoice_detail', invoice_id=invoice.id)
    
    # If somehow neither GET nor POST (shouldn't happen)
    return redirect('billing:invoice_detail', invoice_id=invoice.id)

# ================================================================
# AJAX ENDPOINTS
# ================================================================

@login_required
def get_item_rate(request, item_id):
    """
    AJAX endpoint to get item details for auto-population.
    """
    try:
        item = get_object_or_404(Item, id=item_id, is_active=True)
        
        return JsonResponse({
            'success': True,
            'wholesale_rate': float(getattr(item, 'price_wholesale', 0) or 0),
            'retail_rate': float(getattr(item, 'price_retail', 0) or 0),
            'gst_percent': float(getattr(item, 'gst_percent', 0) or 0),
            'current_stock': int(getattr(item, 'quantity', 0) or 0),
            'is_low_stock': getattr(item, 'is_low_stock', False),
            'is_out_of_stock': getattr(item, 'is_out_of_stock', False),
            'hns_code': getattr(item, 'hns_code', '') or '',
            'name': item.name
        })
        
    except Item.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Item not found'
        }, status=404)
    except Exception as e:
        logger.error(f"❌ Error fetching item rate for ID {item_id}: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while fetching item data'
        }, status=500)


@login_required
def get_invoice_amounts(request, invoice_id):
    """
    AJAX endpoint to fetch invoice total and pending amounts.
    """
    try:
        invoice = Invoice.objects.select_related('party').prefetch_related(
            Prefetch('payments', queryset=Payment.objects.filter(is_active=True)),
            Prefetch('returns', queryset=Return.objects.filter(is_active=True))
        ).get(id=invoice_id, is_active=True)

        total = float(invoice.total_amount or 0)
        paid = float(invoice.total_paid or 0)
        returns = float(sum(r.amount for r in invoice.returns.filter(is_active=True)))
        pending = max(total - paid - returns, 0)  # Ensure non-negative

        return JsonResponse({
            'success': True,
            'total': round(total, 2),
            'paid': round(paid, 2),
            'returns': round(returns, 2),
            'pending': round(pending, 2),
            'invoice_number': invoice.invoice_number,
            'party_name': invoice.party.name,
            'party_phone': invoice.party.phone or '',
            'is_closed': invoice.is_paid,
            'date': invoice.date.strftime('%d %b %Y')
        })

    except Invoice.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Invoice not found'
        }, status=404)
    except Exception as e:
        logger.error(f"❌ Error fetching invoice amounts for ID {invoice_id}: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'An error occurred while fetching invoice data'
        }, status=500)


@login_required
def get_party_invoices(request, party_id):
    """
    AJAX endpoint to get all unpaid invoices for a party.
    """
    try:
        party = get_object_or_404(Party, id=party_id, is_active=True)
        
        invoices = Invoice.objects.filter(
            party=party,
            is_paid=False,
            is_active=True
        ).select_related('party').prefetch_related(
            'payments',
            'returns'
        ).order_by('-date')
        
        # Calculate balance for each invoice
        invoice_data = []
        for inv in invoices:
            invoice_data.append({
                'id': inv.id,
                'invoice_number': inv.invoice_number,
                'date': inv.date.strftime('%d %b %Y'),
                'total': float(inv.total_amount or 0),
                'paid': float(inv.total_paid or 0),
                'balance': float(inv.balance_due or 0)
            })
        
        return JsonResponse({
            'success': True,
            'party_name': party.name,
            'party_phone': party.phone or '',
            'invoices': invoice_data,
            'count': len(invoice_data)
        })
        
    except Party.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Party not found'
        }, status=404)
    except Exception as e:
        logger.error(f"❌ Error fetching party invoices for party {party_id}: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'An error occurred'
        }, status=500)


@login_required
def get_invoice_items(request, invoice_id):
    """
    AJAX endpoint to get all items from an invoice.
    """
    try:
        invoice = get_object_or_404(
            Invoice.objects.prefetch_related(
                Prefetch(
                    'invoice_items',
                    queryset=InvoiceItem.objects.filter(is_active=True).select_related('item')
                )
            ),
            id=invoice_id,
            is_active=True
        )
        
        items_data = []
        for inv_item in invoice.invoice_items.filter(is_active=True):
            items_data.append({
                'id': inv_item.id,
                'item_id': inv_item.item.id if inv_item.item else None,
                'item_name': inv_item.item.name if inv_item.item else 'Manual Item',
                'item_hns': inv_item.item.hns_code if inv_item.item else 'N/A',
                'quantity': int(inv_item.quantity),
                'rate': float(inv_item.rate),
                'gst_amount': float(inv_item.gst_amount),
                'discount_amount': float(inv_item.discount_amount),
                'total': float(inv_item.total)
            })
        
        return JsonResponse({
            'success': True,
            'invoice_number': invoice.invoice_number,
            'party_name': invoice.party.name,
            'party_id': invoice.party.id,
            'items': items_data,
            'total_amount': float(invoice.base_amount or 0),
            'items_count': len(items_data)
        })
        
    except Invoice.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Invoice not found'
        }, status=404)
    except Exception as e:
        logger.error(f"❌ Error fetching invoice items for invoice {invoice_id}: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'An error occurred'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def check_stock_ajax(request):
    """
    AJAX endpoint to check stock availability for multiple items.
    """
    try:
        data = json.loads(request.body)
        items = data.get('items', [])
        
        if not items:
            return JsonResponse({
                'success': False,
                'error': 'No items provided'
            }, status=400)
        
        # Validate items format
        validated_items = []
        for item in items:
            try:
                validated_items.append({
                    'item_id': int(item['item_id']),
                    'quantity': int(item['quantity'])
                })
            except (KeyError, ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid item format'
                }, status=400)
        
        # Check stock availability
        stock_check = check_stock_availability(validated_items)
        
        return JsonResponse({
            'success': True,
            'available': stock_check['available'],
            'unavailable_items': stock_check.get('unavailable_items', []),
            'message': 'Stock check completed'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"❌ Error in stock check AJAX: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ================================================================
# PAYMENT VIEWS
# ================================================================

@login_required_cbv
class PaymentListView(ListView):
    """
    List all payments with session-based PDF download support.
    """
    model = Payment
    template_name = 'billing/payment_list.html'
    context_object_name = 'payments'
    ordering = ['-date', '-payment_number']
    paginate_by = 50

    def get_queryset(self):
        """Get active payments with related data"""
        return Payment.objects.filter(
            is_active=True
        ).select_related(
            'party', 
            'invoice', 
            'created_by',
            'updated_by'
        )

    def get_context_data(self, **kwargs):
        """Add PDF download trigger from session"""
        context = super().get_context_data(**kwargs)
        
        # Check for PDF download trigger from session
        download_payment = self.request.session.pop("download_payment", None)
        context["download_payment"] = download_payment
        
        return context


@login_required_cbv
class PaymentDetailView(DetailView):
    """
    Display detailed payment information.
    """
    model = Payment
    template_name = 'billing/payment_detail.html'
    pk_url_kwarg = 'payment_id'
    context_object_name = 'payment'

    def get_queryset(self):
        """Get payment with all related data"""
        return Payment.objects.filter(
            is_active=True
        ).select_related(
            'party', 
            'invoice__party',
            'created_by', 
            'updated_by'
        )


@login_required_cbv
class PaymentCreateView(View):
    """
    Create new payment with automatic invoice status update.
    """
    template_name = 'billing/add_payment.html'

    @transaction.atomic
    def get(self, request, invoice_id=None):
        """Display payment creation form"""
        initial_data = {}
        
        # Pre-fill from invoice if provided
        if invoice_id:
            invoice = get_object_or_404(Invoice, id=invoice_id, is_active=True)
            initial_data = {
                'invoice': invoice,
                'party': invoice.party,
                'amount': invoice.balance_due if invoice.balance_due > 0 else None,
                'date': timezone.now().date()
            }

        form = PaymentForm(initial=initial_data)
        
        return render(request, self.template_name, {
            'form': form,
            'invoice_id': invoice_id
        })

    @transaction.atomic
    def post(self, request, invoice_id=None):
        """
        REFACTORED: Process payment creation using service layer.
        """
        form = PaymentForm(request.POST)

        # Get optional flags
        download_pdf = request.POST.get('download_receipt') == 'on'

        if not form.is_valid():
            # Build detailed error messages
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
            # ========================================
            # STEP 1: Handle party creation
            # ========================================
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
                    logger.info(f"✨ New party created: {new_party_name}")
                    messages.info(request, f'✨ New party "{new_party_name}" created successfully.')

            if not party:
                messages.error(request, "Please select or create a party.")
                raise ValueError("Missing party")

            # ========================================
            # STEP 2: CREATE PAYMENT (using service)
            # ========================================
            payment = PaymentService.create_payment(
                party=party,
                amount=form.cleaned_data['amount'],
                date=form.cleaned_data['date'],
                mode=form.cleaned_data['mode'],
                invoice=form.cleaned_data.get('invoice'),
                notes=form.cleaned_data.get('notes', ''),
                user=request.user
            )

            # ========================================
            # STEP 3: Handle receipt sending
            # ========================================
            send_receipt = form.cleaned_data.get('send_receipt', False)

            if send_receipt:
                if payment.party.phone:
                    try:
                        send_payment_receipt(payment.party, payment)
                        messages.success(
                            request,
                            f'✅ Payment {payment.payment_number} - ₹{payment.amount:.2f} '
                            f'recorded and receipt sent to {payment.party.name}.'
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ Receipt send failed for payment {payment.payment_number}: {e}")
                        messages.warning(
                            request,
                            f'✅ Payment recorded but receipt failed to send. Error: {str(e)}'
                        )
                else:
                    messages.warning(
                        request,
                        f'✅ Payment recorded but party has no phone number for receipt.'
                    )
            else:
                messages.success(
                    request,
                    f'✅ Payment {payment.payment_number} - ₹{payment.amount:.2f} '
                    f'recorded successfully for {payment.party.name}.'
                )

            # ========================================
            # STEP 4: Handle PDF download
            # ========================================
            if download_pdf:
                request.session["download_payment"] = payment.id
                return redirect("billing:payment_list")

            # Redirect appropriately
            if invoice_id:
                return redirect('billing:invoice_detail', invoice_id=invoice_id)

            return redirect('billing:payment_list')

        except ValueError as ve:
            logger.error(f"❌ Validation error adding payment: {ve}", exc_info=True)
            messages.error(request, f"Validation Error: {str(ve)}")
        except Exception as e:
            logger.error(f"❌ Error adding payment: {e}", exc_info=True)
            messages.error(request, f"❌ Error processing payment: {str(e)}")
        
        # Return form with errors
        return render(request, self.template_name, {
            'form': form,
            'invoice_id': invoice_id
        })


# ================================================================
# RETURN VIEWS
# ================================================================

@login_required_cbv
class ReturnListView(ListView):
    """
    List all returns with session-based PDF download support.
    """
    model = Return
    template_name = 'billing/return_list.html'
    context_object_name = 'returns'
    ordering = ['-return_date', '-return_number']
    paginate_by = 50

    def get_queryset(self):
        """Get active returns with related data"""
        return Return.objects.filter(
            is_active=True
        ).select_related(
            'invoice__party',
            'party', 
            'created_by', 
            'updated_by'
        )

    def get_context_data(self, **kwargs):
        """Add PDF download trigger from session"""
        context = super().get_context_data(**kwargs)
        
        # Check for PDF download trigger from session
        download_return = self.request.session.pop("download_return", None)
        context["download_return"] = download_return
        
        return context


@login_required_cbv
class ReturnDetailView(DetailView):
    """
    Display detailed return information with item breakdown.
    """
    model = Return
    template_name = 'billing/return_detail.html'
    pk_url_kwarg = 'return_id'
    context_object_name = 'return_obj'  # ✅ FIXED: Changed from 'return' (Python keyword)

    def get_queryset(self):
        """Get return with all related data"""
        return Return.objects.filter(
            is_active=True
        ).select_related(
            'invoice__party',
            'party', 
            'created_by', 
            'updated_by'
        ).prefetch_related(
            Prefetch(
                'return_items',
                queryset=ReturnItem.objects.filter(is_active=True).select_related('invoice_item__item')
            )
        )

    def get_context_data(self, **kwargs):
        """Add return items to context"""
        context = super().get_context_data(**kwargs)
        
        # Add return items if they exist
        if hasattr(context['return_obj'], 'return_items'):
            context['return_items'] = context['return_obj'].return_items.filter(is_active=True)
        
        return context




from django.views import View
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.utils import timezone
from decimal import Decimal
import logging

from .models import Return, ReturnItem, Invoice
from .forms import ReturnForm, ReturnItemFormSet
from core.inventory_manager import add_items_for_return

logger = logging.getLogger(__name__)


def login_required_cbv(view_class):
    """Decorator for class-based views"""
    return method_decorator(login_required, name='dispatch')(view_class)


@login_required_cbv
class ReturnCreateView(View):
    """
    ✅ COMPLETE REFACTOR - Invoice-driven return creation with item-level tracking.
    """
    template_name = 'billing/create_return.html'

    @transaction.atomic
    def get(self, request):
        """Display return creation form"""
        invoice_id = request.GET.get('invoice_id')
        
        initial_data = {}
        invoice = None
        
        if invoice_id:
            try:
                invoice = Invoice.objects.get(id=invoice_id, is_active=True)
                initial_data = {
                    'invoice': invoice,
                    'return_date': timezone.now().date()
                }
            except Invoice.DoesNotExist:
                messages.warning(request, f"Invoice ID {invoice_id} not found.")
        
        form = ReturnForm(initial=initial_data)
        formset = ReturnItemFormSet(invoice=invoice)
        
        return render(request, self.template_name, {
            'form': form,
            'formset': formset,
            'invoice': invoice
        })
    
    
    @transaction.atomic
    def post(self, request):
        """
        ✅ FIXED: Process return creation with proper form binding.
        """
        print("\n" + "="*60)
        print("🔍 RETURN CREATE POST - DEBUG")
        print("="*60)
        
        # Log POST data
        print("📦 POST Data:")
        for key, value in request.POST.items():
            print(f"  {key}: {value}")
        
        # ✅ STEP 1: Create form with POST data
        form = ReturnForm(request.POST, request.FILES)
        
        # ✅ STEP 2: Get invoice BEFORE formset creation
        invoice_id = request.POST.get('invoice')
        invoice = None
        
        print(f"\n📋 Invoice ID from POST: {invoice_id}")
        
        if invoice_id:
            try:
                invoice = Invoice.objects.get(id=invoice_id, is_active=True)
                print(f"✅ Invoice found: {invoice.invoice_number}")
            except Invoice.DoesNotExist:
                print(f"❌ Invoice {invoice_id} not found!")
                messages.error(request, f"Invoice with ID {invoice_id} not found.")
                formset = ReturnItemFormSet(invoice=None)
                return render(request, self.template_name, {
                    'form': form,
                    'formset': formset,
                    'invoice': None
                })
            except ValueError:
                print(f"❌ Invalid invoice ID: {invoice_id}")
                messages.error(request, "Invalid invoice ID.")
                formset = ReturnItemFormSet(invoice=None)
                return render(request, self.template_name, {
                    'form': form,
                    'formset': formset,
                    'invoice': None
                })
        
        # ✅ STEP 3: Create formset with invoice context
        formset = ReturnItemFormSet(request.POST, invoice=invoice)
        
        print(f"\n🔍 Form Validation:")
        print(f"  Form valid: {form.is_valid()}")
        print(f"  Form errors: {form.errors}")
        print(f"  Formset valid: {formset.is_valid()}")
        print(f"  Formset errors: {formset.errors}")
        
        # Get PDF download flag
        download_pdf = request.POST.get('download_pdf') == 'on'
        
        # ✅ STEP 4: Validate forms
        if not form.is_valid():
            print("❌ Form validation failed!")
            messages.error(request, 'Please correct the form errors.')
            return render(request, self.template_name, {
                'form': form,
                'formset': formset,
                'invoice': invoice  # ✅ Pass invoice to preserve selection
            })
        
        if not formset.is_valid():
            print("❌ Formset validation failed!")
            messages.error(request, 'Please correct the item errors.')
            return render(request, self.template_name, {
                'form': form,
                'formset': formset,
                'invoice': invoice
            })
        
        # ✅ STEP 5: Collect return items data from formset
        return_items_data = []
        
        print(f"\n📊 Processing {len(formset.forms)} formset forms...")
        
        for idx, form_item in enumerate(formset):
            if form_item.cleaned_data:
                invoice_item = form_item.cleaned_data.get('invoice_item')
                quantity = form_item.cleaned_data.get('quantity')
                amount = form_item.cleaned_data.get('amount')
                
                print(f"  Form {idx}:")
                print(f"    invoice_item: {invoice_item}")
                print(f"    quantity: {quantity}")
                print(f"    amount: {amount}")
                
                if invoice_item and quantity and amount:
                    return_items_data.append({
                        'invoice_item': invoice_item,
                        'quantity': quantity,
                        'amount': amount
                    })
                    print(f"    ✅ Added to return_items_data")
        
        if not return_items_data:
            print("❌ No return items collected!")
            messages.error(request, "Please add at least one item to return.")
            return render(request, self.template_name, {
                'form': form,
                'formset': formset,
                'invoice': invoice
            })
        
        print(f"\n✅ Collected {len(return_items_data)} return items")
        
        try:
            # ✅ STEP 6: Get form data
            invoice = form.cleaned_data['invoice']
            return_date = form.cleaned_data['return_date']
            reason = form.cleaned_data.get('reason', '')
            image = form.cleaned_data.get('image')
            
            print(f"\n💾 Creating return:")
            print(f"  Invoice: {invoice.invoice_number}")
            print(f"  Date: {return_date}")
            print(f"  Items: {len(return_items_data)}")
            
            # ✅ STEP 7: CREATE RETURN (using service)
            return_obj = ReturnService.create_return_with_items(
                invoice=invoice,
                return_items_data=return_items_data,
                return_date=return_date,
                reason=reason,
                image=image,
                user=request.user
            )
            
            print(f"✅ Return created: {return_obj.return_number}")
            print("="*60 + "\n")
            
            # Success message
            status_msg = " Invoice closed." if invoice.is_paid else ""
            
            success_msg = (
                f'✅ Return {return_obj.return_number} created! '
                f'{len(return_items_data)} item(s) returned for ₹{return_obj.amount:.2f}.{status_msg} '
                f'Stock restored for {len(return_items_data)} item(s).'
            )
            messages.success(request, success_msg)
            
            # Handle PDF download
            if download_pdf:
                request.session["download_return"] = return_obj.id
                logger.info(f"📄 PDF queued for return {return_obj.return_number}")
                return redirect("billing:return_list")
            
            return redirect("billing:invoice_detail", invoice_id=invoice.id)
        
        except ValidationError as ve:
            print(f"❌ Validation error: {ve}")
            messages.error(request, f"Validation Error: {str(ve)}")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            messages.error(request, f"Error: {str(e)}")
        
        print("="*60 + "\n")
        
        return render(request, self.template_name, {
            'form': form,
            'formset': formset,
            'invoice': invoice
        })
                

# ================================================================
# PDF DOWNLOAD ENDPOINTS
# ================================================================

@login_required
def invoice_pdf(request, invoice_id):
    """
    Generate and download invoice PDF.
    """
    try:
        invoice = get_object_or_404(
            Invoice.objects.select_related('party').prefetch_related(
                Prefetch(
                    'invoice_items',
                    queryset=InvoiceItem.objects.filter(is_active=True).select_related('item')
                ),
                Prefetch(
                    'payments',
                    queryset=Payment.objects.filter(is_active=True)
                ),
                Prefetch(
                    'returns',
                    queryset=Return.objects.filter(is_active=True)
                )
            ),
            id=invoice_id,
            is_active=True
        )
        
        logger.info(f"📄 Generating PDF for invoice {invoice.invoice_number}")
        return generate_invoice_pdf(invoice)
        
    except Exception as e:
        logger.error(f"❌ Error generating invoice PDF for ID {invoice_id}: {e}", exc_info=True)
        messages.error(request, f"Error generating PDF: {str(e)}")
        return redirect('billing:invoice_detail', invoice_id=invoice_id)


@login_required
def payment_pdf(request, payment_id):
    """
    Generate and download payment receipt PDF.
    """
    try:
        payment = get_object_or_404(
            Payment.objects.select_related('party', 'invoice__party'),
            id=payment_id,
            is_active=True
        )
        
        logger.info(f"📄 Generating PDF for payment {payment.payment_number}")
        return generate_payment_receipt_pdf(payment)
        
    except Exception as e:
        logger.error(f"❌ Error generating payment PDF for ID {payment_id}: {e}", exc_info=True)
        messages.error(request, f"Error generating PDF: {str(e)}")
        return redirect('billing:payment_detail', payment_id=payment_id)


@login_required
def return_pdf(request, return_id):
    """
    Generate and download return receipt PDF.
    """
    try:
        return_obj = get_object_or_404(
            Return.objects.select_related('invoice__party', 'party'),
            id=return_id,
            is_active=True
        )
        
        logger.info(f"📄 Generating PDF for return {return_obj.return_number}")
        return generate_return_receipt_pdf(return_obj)
        
    except Exception as e:
        logger.error(f"❌ Error generating return PDF for ID {return_id}: {e}", exc_info=True)
        messages.error(request, f"Error generating PDF: {str(e)}")
        return redirect('billing:return_list')


# ================================================================
# CHALLAN VIEWS
# ================================================================

@login_required_cbv
class ChallanListView(ListView):
    """
    List all delivery challans.
    """
    model = Challan
    template_name = 'billing/challan_list.html'
    context_object_name = 'challans'
    ordering = ['-date', '-challan_number']
    paginate_by = 50

    def get_queryset(self):
        """Get active challans with related data"""
        return Challan.objects.filter(
            is_active=True
        ).select_related(
            'party', 
            'invoice__party',
            'created_by', 
            'updated_by'
        ).prefetch_related(
            Prefetch(
                'challan_items',
                queryset=ChallanItem.objects.filter(is_active=True).select_related('item')
            )
        )


@login_required_cbv
class ChallanDetailView(DetailView):
    """
    Display challan details with items.
    """
    model = Challan
    template_name = 'billing/challan_details.html'
    pk_url_kwarg = 'challan_id'
    context_object_name = 'challan'

    def get_queryset(self):
        """Get challan with all related data"""
        return Challan.objects.filter(
            is_active=True
        ).select_related(
            'party', 
            'invoice__party',
            'created_by', 
            'updated_by'
        ).prefetch_related(
            Prefetch(
                'challan_items',
                queryset=ChallanItem.objects.filter(is_active=True).select_related('item')
            )
        )

    def get_context_data(self, **kwargs):
        """Add items to context"""
        context = super().get_context_data(**kwargs)
        context['items'] = context['challan'].challan_items.filter(is_active=True)
        return context


@login_required_cbv
class ChallanCreateView(View):
    """
    Create new delivery challan.
    """
    template_name = 'billing/create_challan.html'

    def get(self, request):
        """Display challan creation form"""
        form = ChallanForm()
        formset = ChallanItemFormSet()
        
        return render(request, self.template_name, {
            'form': form,
            'formset': formset
        })

    @transaction.atomic
    def post(self, request):
        """Process challan creation"""
        form = ChallanForm(request.POST)
        formset = ChallanItemFormSet(request.POST)

        # Get optional flags
        download_pdf = request.POST.get('download_pdf') == 'on'

        if not (form.is_valid() and formset.is_valid()):
            messages.error(request, "Please correct the errors below.")
            return render(request, self.template_name, {
                'form': form,
                'formset': formset
            })

        try:
            # STEP 1: Save challan (auto-generates challan_number via model)
            challan = form.save(commit=False)
            challan.created_by = request.user
            challan.updated_by = request.user
            challan.save()

            logger.info(f"✅ Challan created: {challan.challan_number}")

            # STEP 2: Save challan items
            items = formset.save(commit=False)

            # Delete any items marked for deletion
            for deleted_item in formset.deleted_objects:
                deleted_item.delete()

            # Save new/updated items
            for item in items:
                item.challan = challan
                item.created_by = request.user
                item.updated_by = request.user
                item.save()

            logger.info(f"✅ {len(items)} item(s) added to challan {challan.challan_number}")

            # STEP 3: Success message
            messages.success(
                request,
                f"✅ Challan {challan.challan_number} created successfully with {len(items)} item(s)!"
            )

            # STEP 4: Handle PDF download
            if download_pdf:
                from django.urls import reverse
                url = reverse('billing:challan_detail', args=[challan.id])
                return redirect(f"{url}?download=1")

            return redirect('billing:challan_detail', challan_id=challan.id)

        except Exception as e:
            logger.error(f"❌ Error creating challan: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")
            return render(request, self.template_name, {
                'form': form,
                'formset': formset
            })


@login_required_cbv
class ChallanUpdateView(View):
    """
    Update existing delivery challan.
    """
    template_name = 'billing/update_challan.html'

    @transaction.atomic
    def get(self, request, challan_id):
        """Display challan edit form"""
        challan = get_object_or_404(Challan, id=challan_id, is_active=True)
        
        form = ChallanForm(instance=challan)
        formset = ChallanItemFormSet(instance=challan)
        
        return render(request, self.template_name, {
            'form': form,
            'formset': formset,
            'challan': challan
        })

    @transaction.atomic
    def post(self, request, challan_id):
        """Process challan update"""
        challan = get_object_or_404(Challan, id=challan_id, is_active=True)
        
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
            # STEP 1: Save challan updates
            challan = form.save(commit=False)
            challan.updated_by = request.user
            challan.save()

            # STEP 2: Save challan items
            items = formset.save(commit=False)

            # Delete removed items
            for obj in formset.deleted_objects:
                obj.delete()

            # Save new/updated items
            for item in items:
                item.challan = challan
                item.updated_by = request.user
                if not item.created_by:
                    item.created_by = request.user
                item.save()

            logger.info(f"✅ Challan updated: {challan.challan_number}")

            messages.success(
                request,
                f"✅ Challan {challan.challan_number} updated successfully!"
            )
            return redirect('billing:challan_detail', challan_id=challan.id)

        except Exception as e:
            logger.error(f"❌ Error updating challan {challan_id}: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")
            return render(request, self.template_name, {
                'form': form,
                'formset': formset,
                'challan': challan
            })


@login_required
def challan_delete(request, challan_id):
    """
    Delete delivery challan (soft delete by default).
    """
    challan = get_object_or_404(Challan, id=challan_id, is_active=True)

    if request.method == "POST":
        try:
            with transaction.atomic():
                challan_number = challan.challan_number
                items_count = challan.challan_items.filter(is_active=True).count()
                
                # Soft delete via SoftDeleteMixin
                challan.delete()
                
                logger.info(f"✅ Challan deleted: {challan_number}")
                messages.success(
                    request, 
                    f"✅ Challan {challan_number} deleted successfully "
                    f"({items_count} item(s))."
                )
                return redirect('billing:challan_list')
                
        except Exception as e:
            logger.error(f"❌ Error deleting challan {challan_id}: {e}", exc_info=True)
            messages.error(request, f"❌ Error deleting challan: {str(e)}")
            return redirect('billing:challan_detail', challan_id=challan_id)

    # GET request - show confirmation page
    return render(request, "billing/confirm_delete_challan.html", {
        "challan": challan,
        "items_count": challan.challan_items.filter(is_active=True).count()
    })


@login_required
def challan_pdf(request, challan_id):
    """
    Generate and download challan PDF.
    """
    try:
        challan = get_object_or_404(
            Challan.objects.select_related('party', 'invoice__party').prefetch_related(
                Prefetch(
                    'challan_items',
                    queryset=ChallanItem.objects.filter(is_active=True).select_related('item')
                )
            ),
            id=challan_id,
            is_active=True
        )
        
        logger.info(f"📄 Generating PDF for challan {challan.challan_number}")
        return generate_challan_pdf(challan)
        
    except Exception as e:
        logger.error(f"❌ Error generating challan PDF for ID {challan_id}: {e}", exc_info=True)
        messages.error(request, f"Error generating PDF: {str(e)}")
        return redirect('billing:challan_detail', challan_id=challan_id)


# ================================================================
# BALANCE MANAGEMENT
# ================================================================

@login_required_cbv
class BalanceManageView(View):
    """
    Manage old balances for parties and items.
    """
    template_name = 'billing/manage_balance.html'

    @transaction.atomic
    def get(self, request):
        """Display balance management form"""
        formset = BalanceFormSet(
            queryset=Balance.objects.filter(is_active=True).select_related(
                'party', 'item'
            ).order_by('party', 'item')
        )
        
        return render(request, self.template_name, {'formset': formset})

    @transaction.atomic
    def post(self, request):
        """Process balance updates"""
        formset = BalanceFormSet(request.POST)
        
        if not formset.is_valid():
            messages.error(request, 'Please correct form errors.')
            return render(request, self.template_name, {'formset': formset})
        
        try:
            # Save new/updated balances
            instances = formset.save(commit=False)
            
            for instance in instances:
                instance.created_by = request.user
                instance.updated_by = request.user
                instance.save()
            
            # Delete removed balances
            for obj in formset.deleted_objects:
                obj.delete()
            
            logger.info(f"✅ Balances updated by {request.user.username}")
            messages.success(request, '✅ Balances updated successfully.')
            return redirect('billing:manage_balance')
            
        except Exception as e:
            logger.error(f"❌ Error managing balance: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")
            return render(request, self.template_name, {'formset': formset})


# ================================================================
# SESSION MANAGEMENT & CLEANUP
# ================================================================

@login_required
@require_http_methods(["POST"])
def clear_pdf_session(request):
    """
    Clear PDF download session variables.
    """
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            "success": False,
            "error": "AJAX requests only"
        }, status=400)
    
    cleared_keys = []
    pdf_keys = ['download_invoice', 'download_payment', 'download_return', 'download_challan']
    
    for key in pdf_keys:
        if key in request.session:
            request.session.pop(key)
            cleared_keys.append(key)
    
    logger.info(f"🧹 Cleared PDF session keys: {cleared_keys}")
    
    return JsonResponse({
        "success": True,
        "cleared": cleared_keys,
        "count": len(cleared_keys)
    })


# ================================================================
# DASHBOARD & STATISTICS
# ================================================================

@login_required
def dashboard_stats(request):
    """
    AJAX endpoint for dashboard statistics.
    """
    try:
        today = timezone.now().date()
        thirty_days_ago = today - timedelta(days=30)
        
        # Invoice statistics
        total_invoices = Invoice.objects.filter(is_active=True).count()
        pending_invoices = Invoice.objects.filter(
            is_paid=False,
            is_active=True
        ).count()
        
        # Payment statistics (last 30 days)
        recent_payments = Payment.objects.filter(
            is_active=True,
            date__gte=thirty_days_ago
        ).aggregate(
            count=Count('id'),
            total=Sum('amount')
        )
        
        # Return statistics (last 30 days)
        recent_returns = Return.objects.filter(
            is_active=True,
            return_date__gte=thirty_days_ago
        ).aggregate(
            count=Count('id'),
            total=Sum('amount')
        )
        
        # Outstanding balance calculation
        pending_invoice_ids = Invoice.objects.filter(
            is_paid=False,
            is_active=True
        ).values_list('id', flat=True)
        
        total_outstanding = Decimal('0.00')
        for inv_id in pending_invoice_ids:
            try:
                invoice = Invoice.objects.get(id=inv_id)
                total_outstanding += invoice.balance_due or Decimal('0.00')
            except Invoice.DoesNotExist:
                continue
        
        return JsonResponse({
            'success': True,
            'data': {
                'invoices': {
                    'total': total_invoices,
                    'pending': pending_invoices,
                    'paid': total_invoices - pending_invoices
                },
                'payments': {
                    'count_30d': recent_payments['count'] or 0,
                    'total_30d': float(recent_payments['total'] or 0)
                },
                'returns': {
                    'count_30d': recent_returns['count'] or 0,
                    'total_30d': float(recent_returns['total'] or 0)
                },
                'outstanding_balance': float(total_outstanding)
            }
        })
        
    except Exception as e:
        logger.error(f"❌ Error fetching dashboard stats: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Failed to fetch statistics'
        }, status=500)


# ================================================================
# BULK OPERATIONS
# ================================================================

@login_required
@require_http_methods(["POST"])
def bulk_invoice_delete(request):
    """
    Bulk delete invoices with stock restoration.
    """
    try:
        data = json.loads(request.body)
        invoice_ids = data.get('invoice_ids', [])
        
        if not invoice_ids:
            return JsonResponse({
                'success': False,
                'error': 'No invoice IDs provided'
            }, status=400)
        
        deleted_count = 0
        errors = []
        restored_items_total = 0
        
        with transaction.atomic():
            for invoice_id in invoice_ids:
                try:
                    invoice = Invoice.objects.get(id=invoice_id, is_active=True)
                    
                    # Restore stock
                    items_to_restore = []
                    for item_obj in invoice.invoice_items.filter(is_active=True):
                        if item_obj.item:
                            items_to_restore.append({
                                'item_id': item_obj.item.id,
                                'quantity': int(item_obj.quantity)
                            })
                    
                    if items_to_restore:
                        restore_result = restore_items_for_invoice_deletion(
                            invoice_items=items_to_restore,
                            invoice_type='wholesale',
                            invoice_id=invoice.id,
                            created_by=request.user
                        )
                        
                        if restore_result['success']:
                            restored_items_total += len(restore_result['items_processed'])
                    
                    # Soft delete
                    invoice.delete()
                    deleted_count += 1
                    
                except Invoice.DoesNotExist:
                    errors.append(f"Invoice {invoice_id} not found")
                except Exception as e:
                    errors.append(f"Invoice {invoice_id}: {str(e)}")
        
        logger.info(
            f"✅ Bulk delete: {deleted_count} invoice(s), "
            f"{restored_items_total} item(s) restored"
        )
        
        return JsonResponse({
            'success': True,
            'deleted_count': deleted_count,
            'restored_items': restored_items_total,
            'errors': errors
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"❌ Error in bulk delete: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ================================================================
# EXPORT FUNCTIONALITY
# ================================================================

@login_required
def export_invoices_csv(request):
    """
    Export invoices to CSV.
    """
    import csv
    from django.utils.dateparse import parse_date
    
    try:
        # Get filter parameters
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        party_id = request.GET.get('party_id')
        status = request.GET.get('status')
        
        # Build queryset
        queryset = Invoice.objects.filter(is_active=True).select_related('party')
        
        if start_date:
            queryset = queryset.filter(date__gte=parse_date(start_date))
        if end_date:
            queryset = queryset.filter(date__lte=parse_date(end_date))
        if party_id:
            queryset = queryset.filter(party_id=party_id)
        if status == 'paid':
            queryset = queryset.filter(is_paid=True)
        elif status == 'pending':
            queryset = queryset.filter(is_paid=False)
        
        # Create CSV response
        response = HttpResponse(content_type='text/csv')
        filename = f'invoices_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Invoice Number', 'Date', 'Party', 'Total Amount',
            'Paid Amount', 'Balance', 'Status', 'Created By', 'Created At'
        ])
        
        for invoice in queryset:
            writer.writerow([
                invoice.invoice_number,
                invoice.date.strftime('%Y-%m-%d'),
                invoice.party.name,
                float(invoice.total_amount or 0),
                float(invoice.total_paid or 0),
                float(invoice.balance_due or 0),
                'Paid' if invoice.is_paid else 'Pending',
                invoice.created_by.username if invoice.created_by else 'N/A',
                invoice.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])
        
        logger.info(f"📊 CSV export generated: {queryset.count()} invoice(s)")
        return response
        
    except Exception as e:
        logger.error(f"❌ Error exporting invoices CSV: {e}", exc_info=True)
        messages.error(request, f"Error exporting data: {str(e)}")
        return redirect('billing:invoice_list')


# ================================================================
# ERROR HANDLERS
# ================================================================

def handler404(request, exception):
    """Custom 404 error handler"""
    return render(request, 'billing/errors/404.html', status=404)


def handler500(request):
    """Custom 500 error handler"""
    return render(request, 'billing/errors/500.html', status=500)

from decimal import Decimal, ROUND_HALF_UP
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.db.models import Sum, Prefetch
import json
import logging

from .models import Invoice, InvoiceItem, ReturnItem, Return

logger = logging.getLogger(__name__)


@login_required
def get_invoice_items_for_return(request, invoice_id):
    """
    ✅ FIXED - AJAX endpoint to get returnable items from an invoice.
    """
    try:
        logger.info(f"📊 Fetching returnable items for invoice ID: {invoice_id}")
        
        # Get invoice with related data
        invoice = Invoice.objects.select_related('party').prefetch_related(
            Prefetch(
                'invoice_items',
                queryset=InvoiceItem.objects.filter(is_active=True).select_related('item')
            )
        ).get(id=invoice_id, is_active=True)
        
        logger.info(f"✅ Invoice found: {invoice.invoice_number}")
        
        items_data = []
        
        for inv_item in invoice.invoice_items.filter(is_active=True):
            # Skip items without Item reference (manual items)
            if not inv_item.item:
                logger.warning(f"⚠️ Skipping invoice item {inv_item.id} - no Item reference")
                continue
            
            try:
                # Calculate already returned quantity for this specific invoice item
                already_returned = ReturnItem.objects.filter(
                    invoice_item=inv_item,
                    return_instance__is_active=True
                ).aggregate(total=Sum('quantity'))['total'] or 0
                
                # Calculate remaining returnable quantity
                remaining_qty = inv_item.quantity - already_returned
                
                logger.info(
                    f"📦 Item {inv_item.item.name}: "
                    f"Sold={inv_item.quantity}, Returned={already_returned}, Remaining={remaining_qty}"
                )
                
                # Only include if there's still returnable quantity
                if remaining_qty > 0:
                    # Calculate per-unit price safely
                    if inv_item.quantity > 0 and inv_item.total:
                        per_unit_price = (Decimal(str(inv_item.total)) / Decimal(str(inv_item.quantity))).quantize(
                            Decimal('0.01'), ROUND_HALF_UP
                        )
                    else:
                        per_unit_price = Decimal('0.00')
                    
                    items_data.append({
                        'invoice_item_id': inv_item.id,
                        'item_id': inv_item.item.id,
                        'item_name': inv_item.item.name,
                        'item_hns': getattr(inv_item.item, 'hns_code', '') or 'N/A',
                        'sold_quantity': int(inv_item.quantity),
                        'already_returned': int(already_returned),
                        'remaining_returnable': int(remaining_qty),
                        'per_unit_price': float(per_unit_price),
                        'rate': float(inv_item.rate) if inv_item.rate else 0.0,
                        'total_amount': float(inv_item.total) if inv_item.total else 0.0,
                    })
                    
                    logger.info(f"✅ Added returnable item: {inv_item.item.name} ({remaining_qty} units)")
                else:
                    logger.info(f"⏭️ Skipping fully returned item: {inv_item.item.name}")
                    
            except Exception as item_error:
                logger.error(f"❌ Error processing invoice item {inv_item.id}: {item_error}", exc_info=True)
                continue
        
        logger.info(f"✅ Total returnable items found: {len(items_data)}")
        
        response_data = {
            'success': True,
            'invoice_number': invoice.invoice_number,
            'party_name': invoice.party.name,
            'party_id': invoice.party.id,
            'invoice_date': invoice.date.strftime('%d %b %Y'),
            'invoice_total': float(invoice.base_amount or 0),
            'items': items_data,
            'items_count': len(items_data)
        }
        
        logger.info(f"📤 Sending response with {len(items_data)} items")
        return JsonResponse(response_data)
        
    except Invoice.DoesNotExist:
        logger.error(f"❌ Invoice {invoice_id} not found")
        return JsonResponse({
            'success': False,
            'error': f'Invoice with ID {invoice_id} not found'
        }, status=404)
        
    except Exception as e:
        logger.error(f"❌ Unexpected error in get_invoice_items_for_return: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def calculate_return_amount(request):
    """
    ✅ FIXED - AJAX endpoint to calculate return amount.
    """
    try:
        data = json.loads(request.body)
        invoice_item_id = data.get('invoice_item_id')
        return_quantity = data.get('quantity')
        
        logger.info(f"🧮 Calculating return amount: item_id={invoice_item_id}, qty={return_quantity}")
        
        if not invoice_item_id or not return_quantity:
            return JsonResponse({
                'success': False,
                'error': 'Missing invoice_item_id or quantity'
            }, status=400)
        
        # Validate quantity
        try:
            return_quantity = int(return_quantity)
            if return_quantity <= 0:
                return JsonResponse({
                    'success': False,
                    'error': 'Quantity must be greater than zero'
                }, status=400)
        except (ValueError, TypeError):
            return JsonResponse({
                'success': False,
                'error': 'Invalid quantity format'
            }, status=400)
        
        # Get invoice item
        invoice_item = InvoiceItem.objects.select_related('item').get(
            id=invoice_item_id,
            is_active=True
        )
        
        # Calculate already returned
        already_returned = ReturnItem.objects.filter(
            invoice_item=invoice_item,
            return_instance__is_active=True
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        max_returnable = invoice_item.quantity - already_returned
        
        # Validate quantity doesn't exceed returnable amount
        if return_quantity > max_returnable:
            return JsonResponse({
                'success': False,
                'error': f'Cannot return {return_quantity} units. Maximum returnable: {max_returnable}',
                'max_returnable': int(max_returnable)
            }, status=400)
        
        # Calculate return amount (proportional to original)
        if invoice_item.quantity > 0 and invoice_item.total:
            per_unit_price = (Decimal(str(invoice_item.total)) / Decimal(str(invoice_item.quantity))).quantize(
                Decimal('0.01'), ROUND_HALF_UP
            )
        else:
            per_unit_price = Decimal('0.00')
        
        return_amount = (per_unit_price * return_quantity).quantize(
            Decimal('0.01'), ROUND_HALF_UP
        )
        
        logger.info(f"✅ Calculated: {return_quantity} × ₹{per_unit_price} = ₹{return_amount}")
        
        return JsonResponse({
            'success': True,
            'return_amount': float(return_amount),
            'per_unit_price': float(per_unit_price),
            'max_returnable': int(max_returnable),
            'item_name': invoice_item.item.name if invoice_item.item else 'Unknown'
        })
        
    except InvoiceItem.DoesNotExist:
        logger.error(f"❌ Invoice item {invoice_item_id} not found")
        return JsonResponse({
            'success': False,
            'error': 'Invoice item not found'
        }, status=404)
        
    except json.JSONDecodeError:
        logger.error("❌ Invalid JSON in request body")
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
        
    except Exception as e:
        logger.error(f"❌ Error calculating return amount: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def validate_return_items(request):
    """
    ✅ FIXED - AJAX endpoint to validate multiple return items.
    """
    try:
        data = json.loads(request.body)
        invoice_id = data.get('invoice_id')
        return_items = data.get('items', [])
        
        logger.info(f"🔍 Validating return items for invoice {invoice_id}: {len(return_items)} items")
        
        if not invoice_id:
            return JsonResponse({
                'success': False,
                'error': 'Missing invoice_id'
            }, status=400)
        
        if not return_items:
            return JsonResponse({
                'success': False,
                'error': 'No return items provided'
            }, status=400)
        
        invoice = Invoice.objects.get(id=invoice_id, is_active=True)
        
        errors = []
        total_return_amount = Decimal('0.00')
        validated_items = []
        
        for item_data in return_items:
            invoice_item_id = item_data.get('invoice_item_id')
            quantity = item_data.get('quantity')
            
            if not invoice_item_id or not quantity:
                errors.append("Missing invoice_item_id or quantity in item data")
                continue
            
            try:
                quantity = int(quantity)
                if quantity <= 0:
                    errors.append(f"Invalid quantity: {quantity}")
                    continue
            except (ValueError, TypeError):
                errors.append("Invalid quantity format")
                continue
            
            try:
                invoice_item = InvoiceItem.objects.select_related('item').get(
                    id=invoice_item_id,
                    invoice=invoice,
                    is_active=True
                )
                
                # Check returnable quantity
                already_returned = ReturnItem.objects.filter(
                    invoice_item=invoice_item,
                    return_instance__is_active=True
                ).aggregate(total=Sum('quantity'))['total'] or 0
                
                max_returnable = invoice_item.quantity - already_returned
                
                if quantity > max_returnable:
                    errors.append(
                        f"{invoice_item.item.name}: Cannot return {quantity} units. "
                        f"Max: {max_returnable}"
                    )
                    continue
                
                # Calculate amount
                if invoice_item.quantity > 0 and invoice_item.total:
                    per_unit_price = (Decimal(str(invoice_item.total)) / Decimal(str(invoice_item.quantity))).quantize(
                        Decimal('0.01'), ROUND_HALF_UP
                    )
                else:
                    per_unit_price = Decimal('0.00')
                
                item_return_amount = (per_unit_price * quantity).quantize(
                    Decimal('0.01'), ROUND_HALF_UP
                )
                
                total_return_amount += item_return_amount
                
                validated_items.append({
                    'invoice_item_id': invoice_item.id,
                    'item_name': invoice_item.item.name if invoice_item.item else 'Unknown',
                    'quantity': quantity,
                    'amount': float(item_return_amount)
                })
                
            except InvoiceItem.DoesNotExist:
                errors.append(f"Invoice item {invoice_item_id} not found")
                continue
        
        if errors:
            return JsonResponse({
                'success': False,
                'errors': errors,
                'message': 'Validation failed'
            }, status=400)
        
        # Check if total return doesn't exceed invoice total
        existing_returns = Return.objects.filter(
            invoice=invoice,
            is_active=True
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        max_returnable_amount = invoice.base_amount - existing_returns
        
        if total_return_amount > max_returnable_amount:
            return JsonResponse({
                'success': False,
                'error': f'Total return amount ₹{total_return_amount} exceeds maximum returnable ₹{max_returnable_amount:.2f}',
                'max_returnable': float(max_returnable_amount)
            }, status=400)
        
        logger.info(f"✅ Validation successful: {len(validated_items)} items, total: ₹{total_return_amount}")
        
        return JsonResponse({
            'success': True,
            'validated_items': validated_items,
            'total_return_amount': float(total_return_amount),
            'items_count': len(validated_items),
            'message': 'Validation successful'
        })
        
    except Invoice.DoesNotExist:
        logger.error(f"❌ Invoice {invoice_id} not found")
        return JsonResponse({
            'success': False,
            'error': 'Invoice not found'
        }, status=404)
        
    except json.JSONDecodeError:
        logger.error("❌ Invalid JSON in request body")
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
        
    except Exception as e:
        logger.error(f"❌ Error validating return items: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
  