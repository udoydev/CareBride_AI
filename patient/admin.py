from django.contrib import admin
from .models import ChatMessage, HealthMetric, MedicalHistory


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("patient", "role", "language", "ai_model_used", "created_at")
    list_filter = ("role", "language", "ai_model_used")
    search_fields = ("content", "patient__user__first_name", "patient__user__email")


@admin.register(HealthMetric)
class HealthMetricAdmin(admin.ModelAdmin):
    list_display = ("patient", "blood_pressure_sys", "blood_pressure_dia", "blood_sugar_fasting", "weight_kg", "pulse_rate", "logged_at")
    list_filter = ("logged_at",)
    search_fields = ("patient__user__first_name", "patient__user__email")


@admin.register(MedicalHistory)
class MedicalHistoryAdmin(admin.ModelAdmin):
    list_display = ("patient", "chronic_conditions", "allergies")
    search_fields = ("patient__user__first_name", "patient__user__email", "allergies", "chronic_conditions")
