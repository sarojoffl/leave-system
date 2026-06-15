from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('dashboard.urls')),
    path('leaves/', include('leaves.urls')),
    path('accounts/', include('accounts.urls')),
]