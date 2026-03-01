from django.db import models
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
    ]

    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="prescriptions")
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="prescriptions")
    chief_complaints = models.TextField(blank=True, help_text="e.g. Fever x 3 days, dry cough")
    diagnosis = models.CharField(max_length=255, blank=True, help_text="e.g. Acute Bronchitis")
    tests_investigations = models.TextField(blank=True, help_text="Clinical tests e.g. CBC, Serum Creatinine")
    advice_rules = models.TextField(blank=True, help_text="Advice & lifestyle rules")
    doctor_notes = models.TextField(blank=True)
    next_followup_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    issued_at = models.DateTimeField(auto_now_add=True)

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
    ]

    prescription = models.OneToOneField(Prescription, on_delete=models.CASCADE, related_name="follow_up")
    scheduled_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="upcoming")

    @property
    def date(self):
        return self.scheduled_date

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
