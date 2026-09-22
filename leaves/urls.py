from django.urls import path
from . import views

urlpatterns = [
    path('apply/', views.apply_leave, name='apply_leave'),
    path('my/', views.my_leaves, name='my_leaves'),
    path('my/<int:id>/export/', views.export_leave_pdf, name='export_leave_pdf'),
    path('my/attendance/<int:id>/export/', views.export_attendance_request_pdf, name='export_attendance_request_pdf'),
    path('my/holiday-work/<int:id>/export/', views.export_holiday_work_request_pdf, name='export_holiday_work_request_pdf'),
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
    path('reports/export/', views.export_reports_pdf, name='export_reports'),
    path('reports/comp-off/<int:id>/toggle-paid/', views.toggle_comp_off_paid, name='toggle_comp_off_paid'),

    path('employee/<int:employee_id>/', views.employee_detail, name='employee_detail'),
    path("employee/<int:employee_id>/export/", views.export_employee_pdf, name="export_employee_pdf"),

    path("api/ad-to-bs/", views.ad_to_bs_api, name="ad_to_bs_api"),
    path("api/leave-stats/", views.employee_leave_stats_api, name="employee_leave_stats_api"),
    path("api/movement-stats/", views.movement_stats_api, name="movement_stats_api"),
    path("api/attendance-stats/", views.attendance_reports_api, name="attendance_reports_api"),

    path("attendance/", views.my_attendance, name="my_attendance"),
    path("attendance/team/", views.team_attendance, name="team_attendance"),
    path("api/attendance-detail/", views.attendance_day_detail_api, name="attendance_day_detail_api"),
]