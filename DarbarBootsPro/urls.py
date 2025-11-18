from django.contrib import admin
from django.urls import path, include
from django.conf import settings                # ✅ Added this line
from django.conf.urls.static import static      # ✅ And this one
from core.views_migrate import run_migrations

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('UserAuth.urls')),
    path('items/', include('items.urls')),
    path('core/', include('core.urls')),
    path('party/', include('party.urls')),
    path('billing/', include('billing.urls')),
    path('wholesale/', include('wholesale.urls')),
    path('retail/', include('retailapp.urls')),  
    path('run-migrations/', run_migrations),
    path('run-migrations/', run_migrations),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
