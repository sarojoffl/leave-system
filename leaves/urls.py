from django.urls import path
from . import views

urlpatterns = [
    path('apply/', views.apply_leave, name='apply_leave'),
    path('my/', views.my_leaves, name='my_leaves'),
    path('cancel/<int:id>/', views.cancel_leave, name='cancel_leave'),

    path('approvals/', views.approvals, name='approvals'),
    path('approve/<int:id>/', views.approve_leave, name='approve_leave'),
    path('reject/<int:id>/', views.reject_leave, name='reject_leave'),

    path('calendar/', views.calendar, name='calendar'),
    path('team/', views.team, name='team'),
    path('reports/', views.reports, name='reports'),
]