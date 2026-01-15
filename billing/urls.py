# 

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
    path('invoices/<int:invoice_id>/delete/', views.invoice_delete, name='invoice_delete'),
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
    path('payments/<int:payment_id>/pdf/', views.payment_pdf, name='payment_pdf'),


    # ============================
    # RETURNS
    # ============================
    path('returns/', views.ReturnListView.as_view(), name='return_list'),
    path('returns/create/', views.ReturnCreateView.as_view(), name='return_create'),
    path('returns/<int:return_id>/', views.ReturnDetailView.as_view(), name='return_detail'),  # ✅ ADDED
    path('returns/<int:return_id>/pdf/', views.return_pdf, name='return_pdf'),


    # ============================
    # CHALLANS
    # ============================
    path('challans/', views.ChallanListView.as_view(), name='challan_list'),
    path('challans/create/', views.ChallanCreateView.as_view(), name='challan_create'),
    path('challans/<int:challan_id>/', views.ChallanDetailView.as_view(), name='challan_detail'),
    path('challans/<int:challan_id>/edit/', views.ChallanUpdateView.as_view(), name='challan_update'),
    path('challans/<int:challan_id>/delete/', views.challan_delete, name='challan_delete'),
    path('challans/<int:challan_id>/pdf/', views.challan_pdf, name='challan_pdf'),


    # ============================
    # BALANCE MANAGEMENT
    # ============================
    path('balances/manage/', views.BalanceManageView.as_view(), name='manage_balance'),


    # ============================
    # API ENDPOINTS
    # ============================
    # Item data
    path('api/item-rate/<int:item_id>/', views.get_item_rate, name='get_item_rate'),
    
    # Invoice data
    path('api/invoice-amounts/<int:invoice_id>/', views.get_invoice_amounts, name='get_invoice_amounts'),
    path('api/invoice-items/<int:invoice_id>/', views.get_invoice_items, name='get_invoice_items'),  # ✅ ADDED
    
    # Party data
    path('api/party-invoices/<int:party_id>/', views.get_party_invoices, name='get_party_invoices'),  # ✅ ADDED
    
    # Stock checking
    path('api/check-stock/', views.check_stock_ajax, name='check_stock_ajax'),  # ✅ ADDED
    
    # Dashboard
    path('api/dashboard-stats/', views.dashboard_stats, name='dashboard_stats'),  # ✅ ADDED
    
    # Bulk operations
    path('api/bulk-delete-invoices/', views.bulk_invoice_delete, name='bulk_invoice_delete'),  # ✅ ADDED
    
    # Legacy support (keep for backward compatibility)
    path('invoice-amounts/<int:invoice_id>/', views.get_invoice_amounts, name='invoice_amounts'),


    # ============================
    # SESSION MANAGEMENT
    # ============================
    path('clear-pdf-session/', views.clear_pdf_session, name='clear_pdf_session'),


    # ============================
    # EXPORT
    # ============================
    path('export/invoices-csv/', views.export_invoices_csv, name='export_invoices_csv'),  # ✅ ADDED
]