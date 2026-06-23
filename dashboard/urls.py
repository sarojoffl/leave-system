from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('manager/', views.manager_dashboard, name='manager_dashboard'),
    path("calendar-data/", views.calendar_data, name="calendar_data"),
]