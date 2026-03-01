from django.urls import path

from . import views

app_name = "patient"

urlpatterns = [
    path("patient/dashboard/", views.dashboard, name="dashboard"),
    path("patient/prescriptions/<int:prescription_id>/", views.prescription_detail, name="prescription_detail"),
    path("patient/doses/today/", views.doses_today, name="doses_today"),
    path("patient/doses/times/", views.custom_dose_times, name="custom_dose_times"),
    path("patient/follow-ups/", views.followups, name="follow_ups"),
    path("patient/notifications/", views.notifications, name="notifications"),
    path("patient/health-record/", views.health_record, name="health_record"),
    path("patient/doctors/", views.doctor_list, name="doctor_list"),
    path("patient/chat/", views.chatbot, name="chatbot"),
    path("patient/chat-ui/", views.chat_ui, name="chat_ui"),
    path("patient/doctors/<int:doctor_id>/", views.doctor_detail, name="doctor_detail"),
    path("patient/doctors/<int:doctor_id>/book/", views.book_doctor, name="book_doctor"),
    path("patient/prescriptions/<int:prescription_id>/download/", views.download_prescription, name="download_prescription"),
    path("patient/api/chat/history/", views.chat_api_history, name="chat_api_history"),
    path("patient/api/chat/send/", views.chat_api_send, name="chat_api_send"),
    path("patient/api/chat/clear/", views.chat_api_clear, name="chat_api_clear"),
    path("patient/api/chat/sessions/", views.chat_api_sessions, name="chat_api_sessions"),
    path("patient/api/chat/session/new/", views.chat_api_new_session, name="chat_api_new_session"),
    path("patient/analytics/", views.patient_analytics_view, name="analytics"),
    path("patient/payments/export/", views.patient_payment_history, name="payment_history_export"),
    path("patient/appointments/", views.appointments, name="appointments"),
    path("patient/appointments/<int:appointment_id>/", views.appointment_detail_patient, name="appointment_detail"),
    path("patient/appointments/<int:appointment_id>/cancel/", views.request_cancellation, name="request_cancellation"),
    path("patient/appointments/<int:appointment_id>/edit/", views.edit_appointment, name="edit_appointment"),
]
