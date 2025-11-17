# wholesale/urls.py
from django.urls import path
from .views import (
    DashboardHomeView,
    AnalyticsReportView,
    PendingInvoicesReportView,
    PaymentHistoryReportView
)

app_name = 'wholesale'

urlpatterns = [
    path('', DashboardHomeView.as_view(), name='dashboard_home'),
    path('analytics/', AnalyticsReportView.as_view(), name='analytics_report'),
    path('pending-invoices/', PendingInvoicesReportView.as_view(), name='pending_invoices_report'),
    path('payment-history/', PaymentHistoryReportView.as_view(), name='payment_history_report'),
]
