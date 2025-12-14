from django.urls import path
from .views import (
    PartyListView, PartyCreateView, PartyUpdateView, PartyDeleteView,
    PartyDetailView, SendReminderView
)

app_name = 'party'

urlpatterns = [
    # List all parties
    path('', PartyListView.as_view(), name='party_list'),
    
    # Create new party
    path('add/', PartyCreateView.as_view(), name='party_create'),
    
    # Party detail view
    path('<int:pk>/', PartyDetailView.as_view(), name='party_detail'),
    
    # Update existing party
    path('<int:pk>/edit/', PartyUpdateView.as_view(), name='party_edit'),
    
    # Delete party
    path('<int:pk>/delete/', PartyDeleteView.as_view(), name='party_delete'),
    
    # Send WhatsApp reminder
    path('<int:pk>/send-reminder/', SendReminderView.as_view(), name='send_reminder'),
]