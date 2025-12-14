# retailapp/urls.py
from django.urls import path
from . import views

app_name = 'retailapp'

urlpatterns = [
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
    
    # AJAX Endpoints
    path('ajax/item/<int:item_id>/', views.ajax_get_item_details, name='ajax_item_details'),
    path('ajax/calculate/', views.ajax_calculate_item_total, name='ajax_calculate_total'),
    path('ajax/toggle-payment/<int:invoice_id>/', views.ajax_toggle_payment_status, name='ajax_toggle_payment'),
    path('ajax/search-items/', views.ajax_search_items, name='ajax_search_items'),
]