from django.db import models
from django.utils import timezone
from accounts.models import Doctor, Patient


class Medicine(models.Model):
    generic_name = models.CharField(max_length=150)
    brand_name = models.CharField(max_length=150)
    form = models.CharField(max_length=50, help_text="e.g. Tablet, Capsule, Syrup, Injection")
    manufacturer = models.CharField(max_length=150, blank=True, help_text="e.g. Square, Incepta, Beximco")

    def __str__(self):
        return f"{self.brand_name} ({self.generic_name})" if self.brand_name else self.generic_name


class Prescription(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("scheduled", "Scheduled"),
        ("expired", "Expired"),
    ]

    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="prescriptions")
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="prescriptions")
    appointment = models.ForeignKey("doctors.Appointment", on_delete=models.SET_NULL, null=True, blank=True, related_name="prescriptions", help_text="Appointment this prescription is linked to")
    chief_complaints = models.TextField(blank=True, help_text="e.g. Fever x 3 days, dry cough")
    diagnosis = models.CharField(max_length=255, blank=True, help_text="e.g. Acute Bronchitis")
    tests_investigations = models.TextField(blank=True, help_text="Clinical tests e.g. CBC, Serum Creatinine")
    advice_rules = models.TextField(blank=True, help_text="Advice & lifestyle rules")
    doctor_notes = models.TextField(blank=True)
    next_followup_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    issued_at = models.DateTimeField(auto_now_add=True)
    activates_at = models.DateTimeField(null=True, blank=True, help_text="Time when prescription becomes active (10 min before appointment)")
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Time when prescription becomes locked (4 hours after creation)")
    is_locked = models.BooleanField(default=False, help_text="Whether prescription editing is disabled")

    @property
    def tests_list(self):
        if not self.tests_investigations:
            return []
        return [t.strip() for t in self.tests_investigations.splitlines() if t.strip()]

    @property
    def advice_list(self):
        if not self.advice_rules:
            return []
        return [a.strip() for a in self.advice_rules.splitlines() if a.strip()]

    @property
    def is_edit_locked(self):
        """Prescription editing is locked 4 hours after creation.

        Checks both the stored is_locked flag AND the time-based expiry
        (expires_at = issued_at + 4 hours). This ensures old prescriptions
        cannot be edited even if is_locked was never set to True.
        """
        if self.is_locked:
            return True
        if self.expires_at and timezone.now() > self.expires_at:
            return True
        return False

    def save(self, *args, **kwargs):
        if self.appointment and not self.activates_at:
            apt_datetime = timezone.datetime.combine(
                self.appointment.appointment_date,
                self.appointment.start_time,
            )
            apt_datetime = timezone.make_aware(apt_datetime)
            self.activates_at = apt_datetime - timezone.timedelta(minutes=10)
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(hours=4)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Prescription #{self.pk or 'new'} ({self.patient})"


class PrescriptionItem(models.Model):
    MEAL_CHOICES = [
        ("before_meal", "Before meal / খাবার আগে"),
        ("after_meal", "After meal / খাবার পরে"),
        ("with_meal", "With meal / খাবারের সাথে"),
        ("anytime", "Anytime / যেকোনো সময়"),
    ]

    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="items")
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE)
    dosage = models.CharField(max_length=100, help_text="e.g. 1 tablet, 5ml syrup")
    frequency = models.PositiveIntegerField(default=1, help_text="Times per day")
    timing_relation_to_meal = models.CharField(max_length=20, choices=MEAL_CHOICES, default="after_meal")
    duration_days = models.PositiveIntegerField(default=1)
    special_instructions = models.TextField(blank=True)

    @property
    def plain_language(self):
        parts = [self.dosage, f"{self.frequency} time(s) per day", f"for {self.duration_days} day(s)"]
        if self.special_instructions:
            parts.append(self.special_instructions)
        return " | ".join(parts)

    def __str__(self):
        return f"{self.medicine} x {self.dosage}"


class AIPrescriptionScan(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending Processing"),
        ("completed", "Successfully Extracted"),
        ("failed", "Extraction Failed"),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="prescription_scans")
    image = models.ImageField(upload_to="prescription_scans/")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    raw_ocr_text = models.TextField(blank=True)
    extracted_json = models.JSONField(null=True, blank=True, help_text="Structured medicine list extracted by Gemini Vision AI")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Prescription Scan #{self.id} for {self.patient}"


class FollowUp(models.Model):
    STATUS_CHOICES = [
        ("upcoming", "Upcoming"),
        ("completed", "Completed"),
        ("missed", "Missed"),
        ("booking_required", "Booking Required"),
    ]

    prescription = models.OneToOneField(Prescription, on_delete=models.CASCADE, related_name="follow_up")
    scheduled_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="upcoming")
    notification_sent = models.BooleanField(default=False, help_text="Whether booking notification was sent to patient")
    booking_deadline = models.DateField(null=True, blank=True, help_text="Reference deadline (4 days from follow-up)")
    is_booking_confirmed = models.BooleanField(default=False, help_text="Whether patient has booked appointment for follow-up")

    @property
    def date(self):
        return self.scheduled_date

    def save(self, *args, **kwargs):
        if not self.booking_deadline or self.booking_deadline > self.scheduled_date:
            self.booking_deadline = self.scheduled_date
        super().save(*args, **kwargs)

    def should_send_notification(self):
        """Check if notification should be sent to the patient.

        Notification is sent 4 days before the follow-up scheduled_date,
        giving the patient advance notice to book their appointment before
        the booking deadline (scheduled_date + 4 days).

        If today >= (scheduled_date - 4 days), a reminder notification is created
        prompting the patient to book their follow-up appointment.
        """
        if self.notification_sent:
            return False
        today = timezone.localdate()
        # Notify 4 days before the follow-up date (or immediately if that's already passed)
        notification_date = self.scheduled_date - timezone.timedelta(days=4)
        return today >= notification_date

    def __str__(self):
        return f"Follow-up for {self.prescription}"


import re


def get_active_dose_slots(dosage_str, frequency=1):
    """
    Parses dosage string notation (e.g. '1+0+1', '1 + 1 + 1', '1+0+0', '1+1+1+1')
    Returns a list of dicts with 'time', 'label_bn', 'label_en', 'amount' for active doses.
    """
    dosage_clean = (dosage_str or "").strip()
    
    # Try splitting by '+' or '-'
    delimiters = r'[\+\-]'
    parts = [p.strip() for p in re.split(delimiters, dosage_clean) if p.strip()]
    
    # Standard 3-slot pattern (Morning, Afternoon, Night)
    if len(parts) == 3:
        slots_3 = [
            {"time": "08:00:00", "label_en": "Morning Dose", "label_bn": "সকালের ডোজ"},
            {"time": "14:00:00", "label_en": "Afternoon Dose", "label_bn": "দুপুরের ডোজ"},
            {"time": "20:00:00", "label_en": "Night Dose", "label_bn": "রাতের ডোজ"},
        ]
        active = []
        for idx, val in enumerate(parts):
            val_clean = val.lower().replace("tablet", "").replace("tab", "").strip()
            if val_clean != "0" and val_clean != "o" and any(c.isdigit() or c in "½¼¾." for c in val_clean):
                slot = dict(slots_3[idx])
                slot["amount"] = val
                active.append(slot)
        if active:
            return active

    # Standard 4-slot pattern (Morning, Noon, Evening, Night)
    elif len(parts) == 4:
        slots_4 = [
            {"time": "08:00:00", "label_en": "Morning Dose", "label_bn": "সকালের ডোজ"},
            {"time": "13:00:00", "label_en": "Noon Dose", "label_bn": "দুপুরের ডোজ"},
            {"time": "18:00:00", "label_en": "Evening Dose", "label_bn": "সন্ধ্যার ডোজ"},
            {"time": "22:00:00", "label_en": "Night Dose", "label_bn": "রাতের ডোজ"},
        ]
        active = []
        for idx, val in enumerate(parts):
            val_clean = val.lower().replace("tablet", "").replace("tab", "").strip()
            if val_clean != "0" and val_clean != "o" and any(c.isdigit() or c in "½¼¾." for c in val_clean):
                slot = dict(slots_4[idx])
                slot["amount"] = val
                active.append(slot)
        if active:
            return active

    # Fallback based on integer frequency if no '+' notation found
    freq = max(1, min(frequency or 1, 4))
    fallback_map = {
        1: [
            {"time": "20:00:00", "label_en": "Night Dose", "label_bn": "রাতের ডোজ", "amount": dosage_clean or "1 dose"},
        ],
        2: [
            {"time": "08:00:00", "label_en": "Morning Dose", "label_bn": "সকালের ডোজ", "amount": dosage_clean or "1 dose"},
            {"time": "20:00:00", "label_en": "Night Dose", "label_bn": "রাতের ডোজ", "amount": dosage_clean or "1 dose"},
        ],
        3: [
            {"time": "08:00:00", "label_en": "Morning Dose", "label_bn": "সকালের ডোজ", "amount": dosage_clean or "1 dose"},
            {"time": "14:00:00", "label_en": "Afternoon Dose", "label_bn": "দুপুরের ডোজ", "amount": dosage_clean or "1 dose"},
            {"time": "20:00:00", "label_en": "Night Dose", "label_bn": "রাতের ডোজ", "amount": dosage_clean or "1 dose"},
        ],
        4: [
            {"time": "08:00:00", "label_en": "Morning Dose", "label_bn": "সকালের ডোজ", "amount": dosage_clean or "1 dose"},
            {"time": "14:00:00", "label_en": "Afternoon Dose", "label_bn": "দুপুরের ডোজ", "amount": dosage_clean or "1 dose"},
            {"time": "18:00:00", "label_en": "Evening Dose", "label_bn": "সন্ধ্যার ডোজ", "amount": dosage_clean or "1 dose"},
            {"time": "20:00:00", "label_en": "Night Dose", "label_bn": "রাতের ডোজ", "amount": dosage_clean or "1 dose"},
        ],
    }
    return fallback_map.get(freq, fallback_map[1])


class ReminderSchedule(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("taken", "Taken"),
        ("skipped", "Skipped"),
    ]

    prescription_item = models.ForeignKey(
        PrescriptionItem,
        on_delete=models.CASCADE,
        related_name="reminder_schedules",
    )
    scheduled_date = models.DateField()
    reminder_time = models.TimeField(null=True, blank=True, help_text="Specific dose time (e.g. 08:00:00)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    taken_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["scheduled_date", "reminder_time"]

    @property
    def time_label(self):
        if not self.reminder_time:
            return {"bn": "আজকের ডোজ", "en": "Dose"}
        h = self.reminder_time.hour
        if 5 <= h < 12:
            return {"bn": "সকালের ডোজ", "en": "Morning Dose"}
        elif 12 <= h < 17:
            return {"bn": "দুপুরের ডোজ", "en": "Afternoon Dose"}
        elif 17 <= h < 20:
            return {"bn": "সন্ধ্যার ডোজ", "en": "Evening Dose"}
        else:
            return {"bn": "রাতের ডোজ", "en": "Night Dose"}

    def __str__(self):
        return f"Reminder for {self.prescription_item} on {self.scheduled_date}"
