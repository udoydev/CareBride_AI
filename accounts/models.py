from django.conf import settings
from django.db import models
from django.utils import timezone

try:
    from django.db.models import JSONField
except ImportError:
    from django.contrib.postgres.fields import JSONField

BD_DISTRICT_CHOICES = [
    ("Dhaka", "Dhaka"),
    ("Chattogram", "Chattogram"),
    ("Rajshahi", "Rajshahi"),
    ("Khulna", "Khulna"),
    ("Barishal", "Barishal"),
    ("Sylhet", "Sylhet"),
    ("Rangpur", "Rangpur"),
    ("Mymensingh", "Mymensingh"),
    ("Other BD District", "Other BD District"),
]


class Patient(models.Model):
    VERIFICATION_CHOICES = [
        ("pending", "Pending Verification"),
        ("verified", "BD Citizen Verified"),
        ("rejected", "Rejected"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="patient_profile")
    phone_number = models.CharField(max_length=20, blank=True, help_text="Bangladeshi mobile number e.g. +88017XXXXXXXX")
    district = models.CharField(max_length=50, choices=BD_DISTRICT_CHOICES, default="Dhaka")
    country = models.CharField(max_length=50, default="Bangladesh", editable=False)
    nid_or_birth_reg = models.CharField(max_length=30, blank=True, help_text="Bangladeshi NID or Birth Registration Number")
    identity_document = models.FileField(upload_to="patient_identity_docs/", null=True, blank=True, help_text="NID card or Birth Certificate image/PDF")
    verification_status = models.CharField(max_length=20, choices=VERIFICATION_CHOICES, default="pending")
    is_verified = models.BooleanField(default=False)
    avatar = models.ImageField(upload_to="patient_avatars/", null=True, blank=True)
    avatar_updated_at = models.DateTimeField(null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True)
    preferred_language = models.CharField(
        max_length=10,
        choices=[("bn", "Bangla"), ("en", "English")],
        default="bn",
    )
    custom_dose_times = JSONField(default=list, blank=True, help_text="Custom dose times in HH:MM format, e.g. ['08:00', '14:00', '20:00']")

    def save(self, *args, **kwargs):
        if self.verification_status == "rejected":
            self.is_verified = False
        elif self.verification_status == "verified":
            self.is_verified = True
        else:
            self.is_verified = bool(self.is_verified)
        super().save(*args, **kwargs)

    def __str__(self):
        status_badge = " [Verified BD Citizen]" if self.is_verified else " [Pending Verification]"
        return (self.user.get_full_name() or self.user.email or self.user.username) + status_badge


class Doctor(models.Model):
    VERIFICATION_CHOICES = [
        ("pending", "Pending Verification"),
        ("verified", "BMDC Verified"),
        ("rejected", "Rejected"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="doctor_profile")
    phone_number = models.CharField(max_length=20, blank=True, help_text="Bangladeshi mobile number e.g. +88017XXXXXXXX")
    specialty = models.CharField(max_length=100, blank=True)
    registration_number = models.CharField(max_length=50, blank=True, help_text="BMDC Registration Number e.g. A-12345")
    nid_number = models.CharField(max_length=30, blank=True, help_text="Bangladeshi NID Number for verification")
    bmdc_certificate = models.FileField(upload_to="doctor_certificates/", null=True, blank=True, help_text="BMDC certificate / license image or PDF")
    clinic_name = models.CharField(max_length=150, blank=True)
    location_text = models.CharField(max_length=255, blank=True)
    country = models.CharField(max_length=50, default="Bangladesh", editable=False)
    bio = models.TextField(blank=True)
    experience_years = models.PositiveIntegerField(default=0, help_text="Total years of medical practice experience")
    consultation_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Consultation fee in BDT")
    avatar = models.ImageField(upload_to="doctor_avatars/", null=True, blank=True)
    avatar_updated_at = models.DateTimeField(null=True, blank=True)
    verification_status = models.CharField(max_length=20, choices=VERIFICATION_CHOICES, default="pending")
    is_verified = models.BooleanField(default=False)
    payout_bank_name = models.CharField(max_length=150, blank=True)
    payout_account_number = models.CharField(max_length=100, blank=True)
    payout_mobile_wallet = models.CharField(max_length=20, blank=True, help_text="bKash/Nagad number")
    payout_account_holder = models.CharField(max_length=150, blank=True)

    def save(self, *args, **kwargs):
        if self.verification_status == "rejected":
            self.is_verified = False
        elif self.verification_status == "verified":
            self.is_verified = True
        else:
            self.is_verified = bool(self.is_verified)
        super().save(*args, **kwargs)

    def __str__(self):
        status_badge = " [Verified BMDC Doctor]" if self.is_verified else " [Pending Verification]"
        return (self.user.get_full_name() or self.user.email or self.user.username) + status_badge


class AppNotification(models.Model):
    NOTIFICATION_TYPES = [
        ("booking", "Doctor Appointment Booking"),
        ("dose_reminder", "Dose Reminder"),
        ("followup_reminder", "Follow-up Reminder"),
        ("prescription_issued", "New Prescription Issued"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=150)
    message = models.TextField()
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPES, default="booking")
    link_url = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Notification for {self.user}: {self.title}"


class AIProvider(models.Model):
    PROVIDER_CHOICES = [
        ("gemini", "Google Gemini"),
        ("groq", "Groq Cloud"),
        ("openai", "OpenAI"),
        ("deepseek", "DeepSeek"),
        ("openrouter", "OpenRouter"),
        ("custom", "Custom OpenAI-compatible"),
    ]

    name = models.CharField(max_length=100, help_text="Friendly name for this API config")
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    api_key = models.CharField(max_length=200, help_text="API key (stored encrypted in production)")
    model_name = models.CharField(max_length=100, default="gemini-2.0-flash", help_text="Model identifier e.g. gemini-2.0-flash, llama-3.3-70b-versatile")
    base_url = models.CharField(max_length=500, blank=True, help_text="Custom base URL for OpenAI-compatible APIs (for Groq, DeepSeek, Custom)")
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=100, help_text="Lower number = higher priority. Tried first.")
    max_requests_per_minute = models.PositiveIntegerField(default=60, help_text="Rate limit for this provider")
    current_usage_count = models.PositiveIntegerField(default=0, help_text="Usage in current minute window")
    last_used_at = models.DateTimeField(null=True, blank=True)
    success_count = models.PositiveIntegerField(default=0)
    failure_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "created_at"]

    def __str__(self):
        status = "✅ Active" if self.is_active else "❌ Inactive"
        return f"{self.name} ({self.get_provider_display()}) — {status} — Priority: {self.priority}"

    def record_success(self):
        self.success_count += 1
        self.current_usage_count += 1
        self.last_used_at = timezone.now()
        self.save(update_fields=["success_count", "current_usage_count", "last_used_at"])

    def record_failure(self):
        self.failure_count += 1
        self.last_used_at = timezone.now()
        self.save(update_fields=["failure_count", "last_used_at"])

    def reset_usage_if_needed(self):
        """Reset usage counter if last_used_at was more than 1 minute ago."""
        if self.last_used_at and (timezone.now() - self.last_used_at).total_seconds() > 60:
            self.current_usage_count = 0
            self.save(update_fields=["current_usage_count"])

    @property
    def is_available(self):
        if not self.is_active:
            return False
        self.reset_usage_if_needed()
        return self.current_usage_count < self.max_requests_per_minute

    @property
    def success_rate(self):
        total = self.success_count + self.failure_count
        if total == 0:
            return 100.0
        return round((self.success_count / total) * 100, 1)

