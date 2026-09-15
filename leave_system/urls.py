from django.contrib import admin
from django.urls import path, include
from leaves import views as leave_views
from leaves import iclock_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('dashboard.urls')),
    path('leaves/', include('leaves.urls')),
    path('accounts/', include('accounts.urls')),

    path('hr/movement/', leave_views.staff_movement, name='staff_movement'),
    path('hr/movement/export-pdf/', leave_views.staff_movement_export_pdf, name='staff_movement_export_pdf'),
    path('hr/movement/<int:id>/edit/', leave_views.staff_movement_edit, name='staff_movement_edit'),
    path('hr/movement/<int:id>/cancel/', leave_views.staff_movement_cancel, name='staff_movement_cancel'),

    # ZKTeco iClock biometric device endpoints (supporting optional trailing slash)
    path('iclock/cdata', iclock_views.iclock_cdata, name='iclock_cdata'),
    path('iclock/cdata/', iclock_views.iclock_cdata),
    path('iclock/getrequest', iclock_views.iclock_getrequest, name='iclock_getrequest'),
    path('iclock/getrequest/', iclock_views.iclock_getrequest),
    path('iclock/devicecmd', iclock_views.iclock_devicecmd, name='iclock_devicecmd'),
    path('iclock/devicecmd/', iclock_views.iclock_devicecmd),
]