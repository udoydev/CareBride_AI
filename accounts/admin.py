from django.contrib import admin
from django.utils.html import format_html
from .models import Patient, Doctor, AIProvider


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "phone_number",
        "district",
        "verification_status",
        "is_verified",
        "view_identity_link",
    )
    list_editable = ("verification_status", "is_verified")
    readonly_fields = ("view_identity_link",)
    list_filter = ("verification_status", "is_verified", "district", "country")
    search_fields = ("user__first_name", "user__last_name", "user__email", "phone_number", "nid_or_birth_reg")
    actions = ["approve_and_verify_patient", "reject_patient_verification"]

    @admin.action(description="Approve & Verify Patient (BD Citizen Verified)")
    def approve_and_verify_patient(self, request, queryset):
        for patient in queryset:
            patient.verification_status = "verified"
            patient.is_verified = True
            patient.save()
        self.message_user(request, f"Successfully verified {queryset.count()} patient(s) as Bangladeshi citizens.")

    @admin.action(description="Reject Patient Verification")
    def reject_patient_verification(self, request, queryset):
        for patient in queryset:
            patient.verification_status = "rejected"
            patient.is_verified = False
            patient.save()
        self.message_user(request, f"Rejected verification for {queryset.count()} patient(s).")

    def view_identity_link(self, obj):
        if obj and obj.identity_document:
            return format_html(
                '<a href="{}" target="_blank" style="display:inline-block;padding:6px 12px;background-color:#0d9488;color:#ffffff;font-weight:bold;border-radius:6px;text-decoration:none;">🪪 Click to View NID/Birth Certificate File</a>',
                obj.identity_document.url
            )
        return "No document uploaded"
    view_identity_link.short_description = "Uploaded Document Proof"
    view_identity_link.allow_tags = True


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "specialty",
        "registration_number",
        "verification_status",
        "is_verified",
        "view_certificate_link",
    )
    list_editable = ("verification_status", "is_verified")
    readonly_fields = ("view_certificate_link",)
    list_filter = ("verification_status", "is_verified", "specialty", "country")
    search_fields = ("user__first_name", "user__last_name", "user__email", "registration_number", "phone_number", "nid_number")
    actions = ["approve_and_verify_doctor", "reject_doctor_verification"]

    @admin.action(description="Approve & Verify Doctor (BMDC & BD Citizen Verified)")
    def approve_and_verify_doctor(self, request, queryset):
        for doctor in queryset:
            doctor.verification_status = "verified"
            doctor.is_verified = True
            doctor.save()
        self.message_user(request, f"Successfully verified {queryset.count()} doctor(s) with BMDC status.")

    @admin.action(description="Reject Doctor Verification")
    def reject_doctor_verification(self, request, queryset):
        for doctor in queryset:
            doctor.verification_status = "rejected"
            doctor.is_verified = False
            doctor.save()
        self.message_user(request, f"Rejected verification for {queryset.count()} doctor(s).")

    def view_certificate_link(self, obj):
        if obj and obj.bmdc_certificate:
            return format_html(
                '<a href="{}" target="_blank" style="display:inline-block;padding:6px 12px;background-color:#0d9488;color:#ffffff;font-weight:bold;border-radius:6px;text-decoration:none;">📄 Click to View BMDC License Document</a>',
                obj.bmdc_certificate.url
            )
        return "No document uploaded"
    view_certificate_link.short_description = "Uploaded BMDC Certificate"
    view_certificate_link.allow_tags = True


@admin.register(AIProvider)
class AIProviderAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "provider",
        "model_name",
        "is_active",
        "priority",
        "current_usage_count",
        "max_requests_per_minute",
        "success_rate",
        "is_available",
    )
    list_filter = ("provider", "is_active")
    search_fields = ("name", "model_name", "api_key")
    list_editable = ("is_active", "priority", "max_requests_per_minute")
    readonly_fields = ("success_rate", "is_available", "current_usage_count", "success_count", "failure_count", "last_used_at")

    fieldsets = (
        ("Basic Info", {"fields": ("name", "provider", "model_name", "base_url")}),
        ("API Credentials", {"fields": ("api_key",)}),
        ("Rate Limiting", {"fields": ("priority", "max_requests_per_minute", "current_usage_count")}),
        ("Status", {"fields": ("is_active", "success_count", "failure_count", "success_rate", "last_used_at")}),
    )

    def success_rate(self, obj):
        return f"{obj.success_rate}%"
    success_rate.short_description = "Success Rate"

    def is_available(self, obj):
        return "✅ Yes" if obj.is_available else "❌ No (rate limited or inactive)"
    is_available.short_description = "Available Now"

    actions = ["test_selected_providers"]

    @admin.action(description="Test selected providers (show exact error/success)")
    def test_selected_providers(self, request, queryset):
        from carebridge.ai_services import GeminiAIService
        for provider in queryset:
            try:
                if provider.provider == "gemini":
                    res = GeminiAIService._call_gemini_sdk(provider.api_key, "Say 'OK' in one word.", None)
                    status = res.get("reply_text", "No response") if res else "SDK failed"
                else:
                    res = GeminiAIService._call_openai_compatible(provider, "Say 'OK' in one word.", None)
                    status = res.get("reply_text", "No response") if res else "API call failed"
                self.message_user(request, f"✅ {provider.name}: {status[:100]}")
            except Exception as e:
                self.message_user(request, f"❌ {provider.name}: {str(e)[:200]}", level="ERROR")
