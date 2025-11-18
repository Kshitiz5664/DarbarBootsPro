# core/urls.py

from django.urls import path
from .views import GreetingView

app_name = 'core'

urlpatterns = [
    path('greeting/', GreetingView.as_view(), name='greeting'),
]
