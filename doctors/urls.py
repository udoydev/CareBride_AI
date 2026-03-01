from django.urls import path

from . import views

app_name = "doctors"

urlpatterns = [
    path("doctors/dashboard/", views.dashboard, name="dashboard"),
    path("doctors/patients/", views.patient_list, name="patient_list"),
    path("doctors/patients/<int:patient_id>/", views.patient_detail, name="patient_detail"),
    path("doctors/patients/<int:patient_id>/prescribe/", views.create_prescription, name="create_prescription"),
    path("doctors/notifications/", views.notifications, name="notifications"),
    path("doctors/history/", views.history, name="history"),
    path("doctors/profile/edit/", views.profile_edit, name="profile_edit"),
    path("doctors/prescriptions/<int:prescription_id>/", views.prescription_detail, name="prescription_detail"),
    path("doctors/prescriptions/<int:prescription_id>/download/", views.download_prescription, name="download_prescription"),
    path("doctors/followup/<int:followup_id>/status/", views.update_followup_status, name="update_followup_status"),
    path("doctors/schedule/", views.schedule_management, name="schedule_management"),
    path("doctors/schedule/<int:schedule_id>/delete/", views.delete_schedule, name="delete_schedule"),
    path("doctors/financial-report/export/", views.doctor_financial_report, name="financial_report_export"),
    path("doctors/appointments/", views.appointment_list, name="appointment_list"),
    path("doctors/appointments/<int:appointment_id>/", views.appointment_detail, name="appointment_detail"),
    path("doctors/emergency/", views.send_emergency_notification, name="send_emergency_notification"),
    path("doctors/appointments/<int:appointment_id>/cancel/approve/", views.approve_cancellation, name="approve_cancellation"),
    path("doctors/appointments/<int:appointment_id>/mark/", views.mark_attendance, name="mark_attendance"),
    path("doctors/appointments/auto-missed/", views.auto_detect_missed, name="auto_detect_missed"),
    path("doctors/appointments/report/", views.appointment_report, name="appointment_report"),
    path("doctors/appointments/report/export/", views.appointment_report_export, name="appointment_report_export"),
]
