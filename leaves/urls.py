from django.urls import path
from . import views

urlpatterns = [
    path('apply/', views.apply_leave, name='apply_leave'),
    path('my/', views.my_leaves, name='my_leaves'),
    path('my/export/', views.export_my_leaves_csv, name='export_my_leaves_csv'),
    path('cancel/<int:id>/', views.cancel_leave, name='cancel_leave'),

    path('approvals/', views.approvals, name='approvals'),
    path('approve/<int:id>/', views.approve_leave, name='approve_leave'),
    path('reject/<int:id>/', views.reject_leave, name='reject_leave'),

    path('approve/<str:request_type>/<int:id>/', views.decide_day_request, {'decision': 'approved'}, name='approve_day_request'),
    path('reject/<str:request_type>/<int:id>/', views.decide_day_request, {'decision': 'rejected'}, name='reject_day_request'),

    path('apply/attendance/', views.apply_attendance_request, name='apply_attendance_request'),
    path('apply/holiday-work/', views.apply_holiday_work, name='apply_holiday_work'),

    path('team/', views.team, name='team'),
    path('reports/', views.reports, name='reports'),
    path('reports/export/', views.export_reports_csv, name='export_reports'),

    path('employee/<int:employee_id>/', views.employee_detail, name='employee_detail'),
    path("employee/<int:employee_id>/export/", views.export_employee_csv, name="export_employee_csv"),

    path("api/ad-to-bs/", views.ad_to_bs_api, name="ad_to_bs_api"),
]