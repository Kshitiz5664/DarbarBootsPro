# retailapp/urls.py
from django.urls import path
from . import views

app_name = 'retailapp'

urlpatterns = [
    # ================================================================
    # MAIN VIEWS
    # ================================================================
    
    # Dashboard
    path('', views.RetailDashboardView.as_view(), name='dashboard'),
    
    # Invoice CRUD
    path('invoice/create/', views.RetailInvoiceCreateView.as_view(), name='invoice_create'),
    path('invoice/<int:invoice_id>/', views.RetailInvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoice/<int:invoice_id>/update/', views.RetailInvoiceUpdateView.as_view(), name='invoice_update'),
    path('invoice/<int:invoice_id>/delete/', views.retail_invoice_delete, name='invoice_delete'),
    path('invoice/<int:invoice_id>/pdf/', views.retail_invoice_pdf, name='invoice_pdf'),
    
    # Returns
    path('invoice/<int:invoice_id>/return/', views.RetailReturnCreateView.as_view(), name='return_create'),
    
    # ================================================================
    # AJAX ENDPOINTS - EXISTING
    # ================================================================
    
    # Item details and calculations
    path('ajax/item/<int:item_id>/', views.ajax_get_item_details, name='ajax_item_details'),
    path('ajax/calculate/', views.ajax_calculate_item_total, name='ajax_calculate_total'),
    path('ajax/search-items/', views.ajax_search_items, name='ajax_search_items'),
    
    # Payment management
    path('ajax/toggle-payment/<int:invoice_id>/', views.ajax_toggle_payment_status, name='ajax_toggle_payment'),
    path('ajax/update-payment-mode/<int:invoice_id>/', views.ajax_update_payment_mode, name='ajax_update_payment_mode'),
    
    # ================================================================
    # AJAX ENDPOINTS - NEW (INVENTORY MANAGEMENT)
    # ================================================================
    
    # Stock availability and real-time stock info
    path('ajax/check-stock/', views.ajax_check_stock_availability, name='ajax_check_stock'),
    path('ajax/item-stock/<int:item_id>/', views.ajax_get_item_stock, name='ajax_item_stock'),
    
    # ================================================================
    # DEBUG/ADMIN ENDPOINTS (OPTIONAL - COMMENT OUT IN PRODUCTION)
    # ================================================================
    
    # Debug view for stock movements
    path('debug/invoice/<int:invoice_id>/movements/', views.debug_invoice_stock_movements, name='debug_stock_movements'),
]