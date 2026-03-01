from django.db import models
from accounts.models import Doctor, Patient


class DoctorSchedule(models.Model):
    DAY_CHOICES = [
        ("monday", "Monday"),
        ("tuesday", "Tuesday"),
        ("wednesday", "Wednesday"),
        ("thursday", "Thursday"),
        ("friday", "Friday"),
        ("saturday", "Saturday"),
        ("sunday", "Sunday"),
    ]

    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="schedules")
    day_of_week = models.CharField(max_length=15, choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    slot_duration_minutes = models.PositiveIntegerField(default=20)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["day_of_week", "start_time"]

    def __str__(self):
        return f"{self.doctor} — {self.get_day_of_week_display()} ({self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')})"


class Appointment(models.Model):
    TYPE_CHOICES = [
        ("in_person", "In-Person Chamber"),
        ("video_online", "Online Video Consultation"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending Payment"),
        ("confirmed", "Confirmed"),
        ("completed", "Completed / Visited"),
        ("missed", "Missed / No-Show"),
        ("cancelled", "Cancelled"),
        ("cancellation_pending", "Cancellation Pending Approval"),
        ("refunded", "Refunded"),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="appointments")
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="appointments")
    appointment_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField(null=True, blank=True, help_text="Auto-calculated from slot duration, editable")
    consultation_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="in_person")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    chief_complaint = models.TextField(blank=True, help_text="Patient symptoms or reason for visit")
    notes = models.TextField(blank=True, help_text="Doctor notes after consultation")
    fee_bdt = models.DecimalField(max_digits=8, decimal_places=2, default=500.00)
    payment_status = models.CharField(max_length=20, choices=[("pending", "Pending"), ("paid", "Paid"), ("refunded", "Refunded")], default="pending")
    payment_method = models.CharField(max_length=50, blank=True, help_text="bKash / SSLCommerz / Cash")
    transaction_id = models.CharField(max_length=100, blank=True)
    paid_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    refund_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    refund_status = models.CharField(max_length=20, choices=[("none", "No Refund"), ("partial", "Partial Refund"), ("full", "Full Refund")], default="none")
    platform_fee_bdt = models.DecimalField(max_digits=8, decimal_places=2, default=0, help_text="3% platform fee")
    net_doctor_payout_bdt = models.DecimalField(max_digits=8, decimal_places=2, default=0, help_text="Amount after platform fee and refunds")
    cancellation_requested_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    cancellation_approved = models.BooleanField(default=False)
    edit_count = models.PositiveIntegerField(default=0, help_text="Number of times patient has edited this booking")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.payment_status == "paid" and float(self.fee_bdt or 0) > 0:
            from decimal import Decimal
            fee = Decimal(str(self.fee_bdt))
            refund = Decimal(str(self.refund_amount))
            self.platform_fee_bdt = (fee * Decimal("0.03")).quantize(Decimal("0.01"))
            self.net_doctor_payout_bdt = fee - self.platform_fee_bdt - refund
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["-appointment_date", "-start_time"]

    def __str__(self):
        return f"Appointment #{self.id}: {self.patient} with {self.doctor} on {self.appointment_date}"
