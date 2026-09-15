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
    max_patients = models.PositiveIntegerField(default=10)
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
        ("pending_verification", "Pending Verification"),
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
    platform_fee_bdt = models.DecimalField(max_digits=8, decimal_places=2, default=0, help_text="15% platform fee")
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
    
    # Payment Appeal Fields (for Overdue Payment Verification Appeals)
    is_payment_appeal_requested = models.BooleanField(default=False)
    payment_appeal_reason = models.TextField(blank=True)
    payment_appeal_submitted_at = models.DateTimeField(null=True, blank=True)
    PAYMENT_APPEAL_STATUS_CHOICES = [
        ("none", "No Appeal"),
        ("pending", "Pending Admin Review"),
        ("approved_refund", "Approved Full Refund"),
        ("approved_payment", "Verified & Confirmed"),
        ("rejected", "Rejected"),
    ]
    payment_appeal_status = models.CharField(
        max_length=20, choices=PAYMENT_APPEAL_STATUS_CHOICES, default="none"
    )
    payment_appeal_admin_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_appeal_pending(self):
        """Returns True ONLY if an appeal is actively pending admin review and appointment is not cancelled/refunded."""
        if not self.is_payment_appeal_requested:
            return False
        if self.payment_appeal_status != "pending":
            return False
        if self.status in ["cancelled", "refunded"] or self.payment_status == "refunded":
            return False
        return True

    @property
    def is_verification_overdue(self):
        """Returns True if payment verification is overdue:
        - Immediately True if appointment is today or within 24 hours of appointment start time.
        - True if pending_verification has elapsed > 24 hours since submission.
        """
        if self.status in ["cancelled", "refunded"] or self.payment_status in ["paid", "refunded"]:
            return False
        if self.payment_status != "pending_verification":
            return False
        from django.utils import timezone
        import datetime
        now = timezone.localtime(timezone.now())
        apt_dt = timezone.make_aware(
            datetime.datetime.combine(self.appointment_date, self.start_time),
            timezone.get_current_timezone()
        )
        # Urgent booking: appointment is within 24 hours or in the past -> overdue immediately
        if apt_dt <= now + datetime.timedelta(hours=24):
            return True
        # Standard booking: 24 hours after payment proof submission
        ref_time = timezone.localtime(self.updated_at or self.created_at)
        if (now - ref_time) >= datetime.timedelta(hours=24):
            return True
        return False

    @property
    def hours_remaining_verification(self):
        """Returns integer hours remaining before payment verification is overdue (max 24h)."""
        if hasattr(self, "_hours_remaining_verification"):
            return self._hours_remaining_verification
        if self.payment_status != "pending_verification":
            return 0
        from django.utils import timezone
        import datetime
        now = timezone.localtime(timezone.now())
        apt_dt = timezone.make_aware(
            datetime.datetime.combine(self.appointment_date, self.start_time),
            timezone.get_current_timezone()
        )
        if apt_dt <= now + datetime.timedelta(hours=24):
            return 0
        ref_time = timezone.localtime(self.updated_at or self.created_at)
        elapsed = (now - ref_time).total_seconds() / 3600
        remaining = int(24 - elapsed)
        return max(0, remaining)

    @hours_remaining_verification.setter
    def hours_remaining_verification(self, value):
        self._hours_remaining_verification = value

    @property
    def verification_overdue(self):
        """Alias for is_verification_overdue."""
        if hasattr(self, "_verification_overdue"):
            return self._verification_overdue
        return self.is_verification_overdue

    @verification_overdue.setter
    def verification_overdue(self, value):
        self._verification_overdue = value

    def save(self, *args, **kwargs):
        """Auto-compute platform fee and doctor payout on save, and sync appeal status."""
        if self.payment_appeal_status == "approved_refund":
            self.payment_status = "refunded"
            self.status = "cancelled"
            if not self.refund_status or self.refund_status == "none":
                self.refund_status = "full"
            if not self.refund_amount:
                self.refund_amount = self.fee_bdt
        elif self.payment_appeal_status == "approved_payment":
            self.payment_status = "paid"
            if self.status == "pending":
                self.status = "confirmed"

        from decimal import Decimal
        from accounts.models import SiteSettings
        # Get the configurable commission rate from SiteSettings singleton (default 15%)
        settings_obj = SiteSettings.get_solo()
        rate = Decimal(str(settings_obj.platform_commission_rate or "15.00")) / Decimal("100")
        # Parse fee and refund as Decimal for precise financial math
        fee = Decimal(str(self.fee_bdt or 0))
        refund = Decimal(str(self.refund_amount or 0))

        if self.payment_status in ("paid", "refunded"):
            if self.refund_status == "full" or (self.refund_amount and self.refund_amount >= fee):
                # Full refund (e.g. doctor cancelled): no site commission, no doctor payout
                self.platform_fee_bdt = Decimal("0.00")
                self.net_doctor_payout_bdt = Decimal("0.00")
            else:
                # Paid or partial refund: preserve historical locked platform_fee_bdt if already set
                if not self.platform_fee_bdt or self.platform_fee_bdt == Decimal("0.00"):
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
