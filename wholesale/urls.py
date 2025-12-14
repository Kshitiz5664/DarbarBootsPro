"""
URL configuration for wholesale dashboard and reporting.
Provides routes for main dashboard, analytics, and financial reports.
"""
from django.urls import path
from .views import (
    DashboardHomeView,
    AnalyticsReportView,
    PendingInvoicesReportView,
    PaymentHistoryReportView
)

app_name = 'wholesale'

urlpatterns = [
    # Main dashboard home
    path('', DashboardHomeView.as_view(), name='dashboard_home'),
    
    # Analytics and reports
    path('analytics/', AnalyticsReportView.as_view(), name='analytics_report'),
    
    # Pending invoices report
    path('pending-invoices/', PendingInvoicesReportView.as_view(), name='pending_invoices_report'),
    
    # Payment history report
    path('payment-history/', PaymentHistoryReportView.as_view(), name='payment_history_report'),
]