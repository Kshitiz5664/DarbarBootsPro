"""
Billing URLs Configuration
"""

from django.urls import path
from . import views

app_name = 'billing'

urlpatterns = [

    # ============================
    # INVOICES
    # ============================
    path('invoices/', views.InvoiceListView.as_view(), name='invoice_list'),
    path('invoices/create/', views.InvoiceCreateView.as_view(), name='invoice_create'),
    path('invoices/<int:invoice_id>/', views.InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoices/<int:invoice_id>/edit/', views.InvoiceUpdateView.as_view(), name='invoice_update'),

    # NEW — Dedicated PDF endpoint
    path('invoices/<int:invoice_id>/pdf/', views.invoice_pdf, name='invoice_pdf'),


    # ============================
    # PAYMENTS
    # ============================
    path('payments/', views.PaymentListView.as_view(), name='payment_list'),
    path('payments/create/', views.PaymentCreateView.as_view(), name='payment_create'),
    path('payments/create/<int:invoice_id>/', views.PaymentCreateView.as_view(),
         name='payment_create_for_invoice'),
    path('payments/<int:payment_id>/', views.PaymentDetailView.as_view(),
         name='payment_detail'),

    # NEW — Dedicated Payment PDF endpoint
    path('payments/<int:payment_id>/pdf/', views.payment_pdf, name='payment_pdf'),

     # ============================
     # RETURNS
     # ============================
     path('returns/', views.ReturnListView.as_view(), name='return_list'),
     path('returns/create/', views.ReturnCreateView.as_view(), name='return_create'),

     # Correct name for template compatibility
     path('returns/<int:return_id>/pdf/', views.return_pdf, name='return_pdf'),

          # ============================
     # PDF SESSION MANAGEMENT
     # ============================
     path('clear-pdf-session/', views.clear_pdf_session, name='clear_pdf_session'),




    # ============================
    # CHALLANS
    # ============================
    path('challans/', views.ChallanListView.as_view(), name='challan_list'),
    path('challans/create/', views.ChallanCreateView.as_view(), name='challan_create'),
    path('challans/<int:challan_id>/', views.ChallanDetailView.as_view(), name='challan_detail'),
    path('challans/<int:challan_id>/edit/', views.ChallanUpdateView.as_view(), name='challan_update'),
    path('challans/<int:challan_id>/delete/', views.challan_delete, name='challan_delete'),

    # NEW — Dedicated Challan PDF endpoint
    path('challans/<int:challan_id>/pdf/', views.challan_pdf, name='challan_pdf'),


    # ============================
    # BALANCE MANAGEMENT
    # ============================
    path('balances/manage/', views.BalanceManageView.as_view(), name='manage_balance'),


    # ============================
    # API ENDPOINTS
    # ============================
    path('api/item-rate/<int:item_id>/', views.get_item_rate, name='get_item_rate'),
    path('api/invoice-amounts/<int:invoice_id>/', views.get_invoice_amounts, name='get_invoice_amounts'),

    # Legacy support
    path('invoice-amounts/<int:invoice_id>/', views.get_invoice_amounts, name='invoice_amounts'),
]
