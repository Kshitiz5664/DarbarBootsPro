from django.urls import path
from .views import (
    PartyListView, PartyCreateView, PartyUpdateView, PartyDeleteView,
    PartyDetailView, SendReminderView
)

app_name = 'party'

urlpatterns = [
    path('', PartyListView.as_view(), name='party_list'),
    path('add/', PartyCreateView.as_view(), name='party_create'),
    path('<int:pk>/', PartyDetailView.as_view(), name='party_detail'),
    path('<int:pk>/edit/', PartyUpdateView.as_view(), name='party_edit'),
    path('<int:pk>/delete/', PartyDeleteView.as_view(), name='party_delete'),
    path('<int:pk>/send-reminder/', SendReminderView.as_view(), name='send_reminder'),
]
