from django.contrib import admin
from django.utils.html import format_html
from .models import ChatSession, ChatMessage, HealthMetric, MedicalHistory, PatientVisit, PatientHealthReport


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("patient", "title", "created_at", "updated_at", "message_count")
    list_filter = ("created_at",)
    search_fields = ("patient__user__first_name", "patient__user__email", "title")
    readonly_fields = ("message_count",)

    def message_count(self, obj):
        return obj.messages.count()
    message_count.short_description = "Messages"


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("patient", "session", "role", "preview", "language", "ai_model_used", "created_at")
    list_filter = ("role", "language", "ai_model_used", "created_at")
    search_fields = ("content", "patient__user__first_name", "patient__user__email")
    readonly_fields = ("patient", "session", "role", "language", "ai_model_used", "content", "created_at")

    def preview(self, obj):
        content = obj.content[:80] if obj.content else ""
        return format_html('<span title="{}">{}</span>', obj.content[:200], content + ("..." if len(obj.content) > 80 else ""))
    preview.short_description = "Message Preview"


@admin.register(HealthMetric)
class HealthMetricAdmin(admin.ModelAdmin):
    list_display = ("patient", "blood_pressure_sys", "blood_pressure_dia", "blood_sugar_fasting", "weight_kg", "pulse_rate", "logged_at")
    list_filter = ("logged_at",)
    search_fields = ("patient__user__first_name", "patient__user__email")


@admin.register(MedicalHistory)
class MedicalHistoryAdmin(admin.ModelAdmin):
    list_display = ("patient", "chronic_conditions", "allergies")
    search_fields = ("patient__user__first_name", "patient__user__email", "allergies", "chronic_conditions")


@admin.register(PatientVisit)
class PatientVisitAdmin(admin.ModelAdmin):
    list_display = ("patient", "doctor", "appointment", "prescription", "heart_rate", "blood_pressure_systolic", "blood_pressure_diastolic", "temperature_celsius", "weight_kg", "height_cm", "oxygen_saturation", "visited_at")
    list_filter = ("visited_at", "doctor")
    search_fields = ("patient__user__first_name", "patient__user__email", "doctor__user__first_name", "visit_notes")


@admin.register(PatientHealthReport)
class PatientHealthReportAdmin(admin.ModelAdmin):
    list_display = ("patient", "title", "report_type", "date_performed", "doctor_or_clinic_name", "created_at")
    list_filter = ("report_type", "date_performed")
    search_fields = ("patient__user__first_name", "patient__user__email", "title", "doctor_or_clinic_name")
