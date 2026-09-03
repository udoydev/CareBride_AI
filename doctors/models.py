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
    PAYMENT_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("refunded", "Refunded"),
    ]
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default="pending")
    payment_method = models.CharField(max_length=50, blank=True, help_text="bKash / SSLCommerz / Cash")
    transaction_id = models.CharField(max_length=100, blank=True)
    paid_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    refund_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    REFUND_STATUS_CHOICES = [
        ("none", "No Refund"),
        ("partial", "Partial Refund"),
        ("full", "Full Refund"),
    ]
    refund_status = models.CharField(max_length=20, choices=REFUND_STATUS_CHOICES, default="none")
    platform_fee_bdt = models.DecimalField(max_digits=8, decimal_places=2, default=0, help_text="3% platform fee")
    net_doctor_payout_bdt = models.DecimalField(max_digits=8, decimal_places=2, default=0, help_text="Amount after platform fee and refunds")
    cancellation_requested_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    cancellation_approved = models.BooleanField(default=False)
    edit_count = models.PositiveIntegerField(default=0, help_text="Number of times patient has edited this booking")
    payment_proof = models.FileField(upload_to="payment_proofs/", null=True, blank=True, help_text="Transaction screenshot or proof")
    payment_notes = models.TextField(blank=True, help_text="Patient notes about payment")
    payment_verified = models.BooleanField(default=False)
    payment_verified_at = models.DateTimeField(null=True, blank=True)
    payment_verified_by = models.ForeignKey(Doctor, null=True, blank=True, on_delete=models.SET_NULL, related_name="verified_payments")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """Auto-compute platform fee and doctor payout on save.

        - platform_fee_bdt = fee × commission_rate (from SiteSettings, default 3%)
        - net_doctor_payout_bdt = fee - platform_fee - refund_amount
        - Both are 0 if the appointment is not yet paid
        - If a doctor cancels (reject action), platform_fee_bdt is manually set to 0
        """
        from decimal import Decimal
        from accounts.models import SiteSettings
        # Get the configurable commission rate from SiteSettings singleton (default 3%)
        settings_obj = SiteSettings.get_solo()
        rate = Decimal(str(settings_obj.platform_commission_rate or "3.00")) / Decimal("100")
        # Parse fee and refund as Decimal for precise financial math
        fee = Decimal(str(self.fee_bdt or 0))
        refund = Decimal(str(self.refund_amount or 0))

        if self.payment_status in ("paid", "refunded"):
            if self.refund_status == "full" or (self.refund_amount and self.refund_amount >= fee):
                # Full refund (e.g. doctor cancelled): no site commission, no doctor payout
                self.platform_fee_bdt = Decimal("0.00")
                self.net_doctor_payout_bdt = Decimal("0.00")
            else:
                # Paid or partial refund: site retains its commission, doctor gets remaining fee minus refund
                self.platform_fee_bdt = (fee * rate).quantize(Decimal("0.01"))
                self.net_doctor_payout_bdt = max(Decimal("0.00"), fee - self.platform_fee_bdt - refund)
        else:
            # Unpaid or pending payment: no commission or payout
            self.platform_fee_bdt = Decimal("0.00")
            self.net_doctor_payout_bdt = Decimal("0.00")

        super().save(*args, **kwargs)

    class Meta:
        ordering = ["-appointment_date", "-start_time"]

    def __str__(self):
        return f"Appointment #{self.id}: {self.patient} with {self.doctor} on {self.appointment_date}"
