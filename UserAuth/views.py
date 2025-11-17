from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.views import View
from django.views.generic import TemplateView, ListView, FormView
from django.urls import reverse_lazy
from items.models import Item


# ✅ Homepage
class IndexView(ListView):
    model = Item
    template_name = "UserAuth/index.html"
    context_object_name = "items"

    def get_queryset(self):
        # Show all active inventory, sort featured items to top.
        return (
            Item.objects.filter(is_active=True, is_deleted=False)
                        .order_by('-is_featured', 'name')
        )


# ✅ Login View
class LoginView(View):
    template_name = "UserAuth/login.html"

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user:
            login(request, user)
            messages.success(request, f"Welcome, {user.username}!")
            return redirect('core:greeting')
        else:
            messages.error(request, "Invalid username or password.")
            return render(request, self.template_name)


# ✅ Logout View
class LogoutView(LoginRequiredMixin, View):
    login_url = reverse_lazy('UserAuth:login')

    def get(self, request):
        logout(request)
        messages.info(request, "You have been logged out.")
        return redirect('UserAuth:login')


# ✅ Registration View
class RegisterView(View):
    template_name = "UserAuth/register.html"

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        username = request.POST.get('username')
        password = request.POST.get('password')

        if not username or not password:
            messages.error(request, "All fields are required.")
            return render(request, self.template_name)

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return render(request, self.template_name)

        User.objects.create_user(username=username, password=password)
        messages.success(request, "User registered successfully. Please log in.")
        return redirect('UserAuth:login')
