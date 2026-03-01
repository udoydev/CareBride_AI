from django.contrib import admin
from .models import DoctorSchedule, Appointment


@admin.register(DoctorSchedule)
class DoctorScheduleAdmin(admin.ModelAdmin):
    list_display = ("doctor", "day_of_week", "start_time", "end_time", "is_active")
    list_filter = ("day_of_week", "is_active")
    search_fields = ("doctor__user__first_name", "doctor__user__last_name", "doctor__user__email")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "doctor", "appointment_date", "start_time", "consultation_type", "status", "fee_bdt")
    list_filter = ("status", "consultation_type", "appointment_date")
    search_fields = ("patient__user__first_name", "patient__user__last_name", "doctor__user__first_name", "doctor__user__last_name")
