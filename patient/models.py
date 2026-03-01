from django.db import models
from accounts.models import Patient


class ChatSession(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="chat_sessions")
    title = models.CharField(max_length=150, default="New Chat")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Session #{self.pk} — {self.patient}"


class ChatMessage(models.Model):
    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="chat_messages")
    session = models.ForeignKey(ChatSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="messages")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    language = models.CharField(max_length=10, default="bn")
    audio_file = models.FileField(upload_to="voice_logs/", null=True, blank=True)
    ai_model_used = models.CharField(max_length=50, default="gemini-2.5-flash")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.patient} — {self.role} @ {self.created_at:%Y-%m-%d %H:%M}"


class HealthMetric(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="health_metrics")
    blood_pressure_sys = models.PositiveIntegerField(null=True, blank=True, help_text="Systolic BP (e.g. 120)")
    blood_pressure_dia = models.PositiveIntegerField(null=True, blank=True, help_text="Diastolic BP (e.g. 80)")
    blood_sugar_fasting = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="mmol/L")
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    pulse_rate = models.PositiveIntegerField(null=True, blank=True, help_text="BPM")
    logged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-logged_at"]

    def __str__(self):
        return f"Vitals for {self.patient} at {self.logged_at:%Y-%m-%d}"


class MedicalHistory(models.Model):
    patient = models.OneToOneField(Patient, on_delete=models.CASCADE, related_name="medical_history")
    allergies = models.TextField(blank=True, help_text="Drug or food allergies e.g. Penicillin")
    chronic_conditions = models.TextField(blank=True, help_text="Known conditions e.g. Hypertension, Type 2 Diabetes")
    past_surgeries = models.TextField(blank=True)
    family_medical_history = models.TextField(blank=True)

    def __str__(self):
        return f"Medical History — {self.patient}"


class PatientHealthReport(models.Model):
    REPORT_TYPE_CHOICES = [
        ("lab_test", "Lab Test Report"),
        ("external_prescription", "External Doctor Prescription"),
        ("imaging_xray", "X-Ray / MRI / Ultrasound"),
        ("other", "Other Medical Document"),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="health_reports")
    title = models.CharField(max_length=150)
    report_type = models.CharField(max_length=30, choices=REPORT_TYPE_CHOICES, default="lab_test")
    date_performed = models.DateField(help_text="Date when test/consultation was conducted")
    doctor_or_clinic_name = models.CharField(max_length=150, blank=True, help_text="Name of consulting doctor or lab/clinic")
    result_description = models.TextField(blank=True, help_text="Test results summary or medical findings")
    document_file = models.FileField(upload_to="patient_health_reports/", help_text="Uploaded PDF or image document")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_performed", "-created_at"]

    def __str__(self):
        return f"{self.title} ({self.get_report_type_display()}) — {self.patient}"

