from django.contrib import admin
from .models import Medicine, Prescription, PrescriptionItem, AIPrescriptionScan, FollowUp, ReminderSchedule


@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = ("brand_name", "generic_name", "form", "manufacturer")
    search_fields = ("brand_name", "generic_name", "manufacturer")


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ("id", "doctor", "patient", "status", "issued_at")
    list_filter = ("status", "issued_at")
    search_fields = ("doctor__user__first_name", "patient__user__first_name")


@admin.register(PrescriptionItem)
class PrescriptionItemAdmin(admin.ModelAdmin):
    list_display = ("prescription", "medicine", "dosage", "frequency", "timing_relation_to_meal", "duration_days")
    search_fields = ("medicine__brand_name", "medicine__generic_name")


@admin.register(AIPrescriptionScan)
class AIPrescriptionScanAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("patient__user__first_name", "patient__user__email")


@admin.register(FollowUp)
class FollowUpAdmin(admin.ModelAdmin):
    list_display = ("prescription", "scheduled_date", "status")
    list_filter = ("status", "scheduled_date")


@admin.register(ReminderSchedule)
class ReminderScheduleAdmin(admin.ModelAdmin):
    list_display = ("prescription_item", "scheduled_date", "reminder_time", "status", "taken_at")
    list_filter = ("status", "scheduled_date")
