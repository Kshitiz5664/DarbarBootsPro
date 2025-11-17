# UserAuth/urls.py

from django.urls import path
from .views import IndexView, LoginView, LogoutView, RegisterView

app_name = 'UserAuth'

urlpatterns = [
    path('', IndexView.as_view(), name='index'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('register/', RegisterView.as_view(), name='register'),
]
