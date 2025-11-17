# core/views.py

from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin


class GreetingView(LoginRequiredMixin, TemplateView):
    template_name = 'core/greeting.html'
    login_url = 'login'  # Redirect unauthenticated users to login page
