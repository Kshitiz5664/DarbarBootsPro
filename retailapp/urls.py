# retailapp/urls.py
from django.urls import path
from . import views

app_name = "retailapp"

urlpatterns = [
    # Console (main billing screen)
    path("billing/", views.RetailBillingConsoleView.as_view(), name="billing_console"),

    # Invoice CRUD
    path("invoice/create/", views.RetailInvoiceCreateView.as_view(), name="invoice_create"),
    path("invoice/<int:pk>/", views.RetailInvoiceDetailView.as_view(), name="invoice_detail"),
    path("invoice/<int:pk>/update/", views.RetailInvoiceUpdateView.as_view(), name="invoice_update"),
    path("invoice/<int:pk>/delete/", views.RetailInvoiceDeleteView.as_view(), name="invoice_delete"),

    # Items
    path("invoice/<int:invoice_id>/item/add/", views.RetailInvoiceItemCreateView.as_view(), name="item_add"),
    path("invoice/item/<int:pk>/edit/", views.RetailInvoiceItemUpdateView.as_view(), name="item_edit"),
    path("invoice/item/<int:pk>/delete/", views.RetailInvoiceItemDeleteView.as_view(), name="item_delete"),

    # Returns
    path("invoice/<int:invoice_id>/return/add/", views.RetailReturnCreateView.as_view(), name="return_add"),
    path("return/<int:pk>/edit/", views.RetailReturnUpdateView.as_view(), name="return_edit"),
    path("return/<int:pk>/delete/", views.RetailReturnDeleteView.as_view(), name="return_delete"),

    # PDF Export
    path("invoice/<int:pk>/pdf/", views.RetailInvoicePDFView.as_view(), name="invoice_pdf"),
]
    