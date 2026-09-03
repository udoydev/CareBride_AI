import os
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Min, Max, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.utils import timezone

from accounts.decorators import never_cache_auth
from accounts.models import AppNotification, Doctor, News, Patient
from carebridge.ai_services import GeminiAIService
from doctors.models import Appointment, DoctorSchedule
from prescriptions.models import FollowUp, Medicine, Prescription, PrescriptionItem, ReminderSchedule


@never_cache_auth
@login_required
def dashboard(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        return render(request, "doctors/dashboard.html", {"rows": []})

    today = timezone.localdate()
    now = timezone.localtime(timezone.now())
    _auto_detect_missed_for_doctor(doctor)
    _auto_mark_missed_today(doctor=doctor)

    # Automatic Follow-up Status Evaluator
    followups = FollowUp.objects.filter(prescription__doctor=doctor)
    for fu in followups:
        has_new_prescription = Prescription.objects.filter(
            doctor=doctor,
            patient=fu.prescription.patient,
            issued_at__date__gte=fu.scheduled_date
        ).exists()

        if has_new_prescription and fu.status != "completed":
            fu.status = "completed"
            fu.save()
        elif fu.scheduled_date < today and fu.status == "upcoming":
            fu.status = "missed"
            fu.save()

    # Prescription Timing Evaluator
    prescriptions_qs = Prescription.objects.filter(doctor=doctor)
    for rx in prescriptions_qs:
        updated = False
        if rx.activates_at and now >= rx.activates_at and rx.status == "scheduled":
            rx.status = "active"
            updated = True
        if rx.expires_at and now >= rx.expires_at and not rx.is_locked:
            rx.is_locked = True
            updated = True
        if updated:
            rx.save(update_fields=["status", "is_locked"])

    patient_rows = []
    prescriptions = (
        Prescription.objects.filter(doctor=doctor)
        .select_related("patient__user")
        .prefetch_related("items__medicine", "follow_up")
        .order_by("-issued_at")
    )

    seen_patient_ids = set()
    for prescription in prescriptions:
        patient = prescription.patient
        if patient.pk in seen_patient_ids:
            continue
        seen_patient_ids.add(patient.pk)
        follow_up = getattr(prescription, "follow_up", None)
        adherence = None
        if follow_up:
            if follow_up.status == "completed":
                adherence = 100
            elif follow_up.status == "missed":
                adherence = 40
            else:
                adherence = 85

        patient_rows.append({
            "patient": {
                "id": patient.pk,
                "name": patient.user.get_full_name() or patient.user.email,
                "avatar": patient.avatar.url if patient.avatar else None,
                "district": patient.district or "Dhaka",
            },
            "adherence": adherence,
            "follow_up": follow_up,
            "has_prescription": True,
        })

    # Also include patients with appointments but no prescriptions yet
    appointment_patients = Appointment.objects.filter(
        doctor=doctor,
        patient__is_verified=True,
    ).select_related("patient__user").order_by("-appointment_date", "-start_time")
    
    for apt in appointment_patients:
        patient = apt.patient
        if patient.pk in seen_patient_ids:
            continue
        seen_patient_ids.add(patient.pk)
        
        patient_rows.append({
            "patient": {
                "id": patient.pk,
                "name": patient.user.get_full_name() or patient.user.email,
                "avatar": patient.avatar.url if patient.avatar else None,
                "district": patient.district or "Dhaka",
            },
            "adherence": None,
            "follow_up": None,
            "has_prescription": False,
            "last_appointment": apt,
        })

    # Sort: patients with prescriptions first, then by most recent
    patient_rows.sort(key=lambda x: (x.get("has_prescription", False), x["patient"]["id"]), reverse=True)

    # Stats
    total_patients = len(seen_patient_ids)
    today_appointments = Appointment.objects.filter(doctor=doctor, appointment_date=today).count()
    pending_appointments = Appointment.objects.filter(doctor=doctor, status="pending").count()
    upcoming_followups = FollowUp.objects.filter(prescription__doctor=doctor, status="upcoming").count()

    # Today's appointments timeline
    today_appointments_qs = Appointment.objects.filter(
        doctor=doctor,
        appointment_date=today,
        status__in=["pending", "confirmed"],
    ).select_related("patient__user").order_by("start_time")

    # Urgent actions
    urgent_actions = []
    
    # Pending appointments awaiting payment
    pending_payment_appointments = Appointment.objects.filter(
        doctor=doctor,
        status="pending",
        appointment_date__gte=today,
    ).select_related("patient__user").order_by("appointment_date", "start_time")[:5]
    for apt in pending_payment_appointments:
        urgent_actions.append({
            "type": "payment_pending",
            "message": f"Payment pending from {apt.patient.user.get_full_name() or apt.patient.user.email}",
            "appointment": apt,
            "url": reverse("doctors:appointment_list") + f"?status=pending",
        })

    # Appointments that need attendance action (past today's appointments not completed/missed)
    action_needed_appointments = Appointment.objects.filter(
        doctor=doctor,
        appointment_date=today,
        status__in=["confirmed", "pending"],
    ).select_related("patient__user").order_by("start_time")[:5]
    for apt in action_needed_appointments:
        urgent_actions.append({
            "type": "mark_attendance",
            "message": f"Mark {apt.patient.user.get_full_name() or apt.patient.user.email} as visited or missed",
            "appointment": apt,
            "url": reverse("doctors:appointment_list") + "?status=today",
        })

    # Prescriptions expiring soon (within next 24 hours)
    expiring_prescriptions = Prescription.objects.filter(
        doctor=doctor,
        status="active",
        expires_at__lte=now + timezone.timedelta(hours=24),
        is_locked=False,
    ).select_related("patient__user").order_by("expires_at")[:5]
    for rx in expiring_prescriptions:
        urgent_actions.append({
            "type": "prescription_expiring",
            "message": f"Prescription for {rx.patient.user.get_full_name() or rx.patient.user.email} expires soon",
            "prescription": rx,
            "url": reverse("doctors:prescription_detail", args=[rx.pk]),
        })

    # Missed follow-ups needing attention
    missed_followups = FollowUp.objects.filter(
        prescription__doctor=doctor,
        status="missed",
    ).select_related("prescription__patient__user").order_by("scheduled_date")[:5]
    for fu in missed_followups:
        urgent_actions.append({
            "type": "missed_followup",
            "message": f"Missed follow-up with {fu.prescription.patient.user.get_full_name() or fu.prescription.patient.user.email}",
            "follow_up": fu,
            "url": reverse("doctors:patient_detail", args=[fu.prescription.patient.pk]),
        })

    stats = {
        "total_patients": total_patients,
        "today_appointments": today_appointments,
        "pending_appointments": pending_appointments,
        "upcoming_followups": upcoming_followups,
    }

    refund_notifications = AppNotification.objects.filter(
        user=request.user,
        notification_type="booking",
    ).filter(
        Q(title__icontains="refund") | Q(title__icontains="cancel") | Q(title__icontains="Cancellation")
    ).order_by("-created_at")[:5]

    # Doctor calendar data - next 30 days
    calendar_start = today
    calendar_end = today + timezone.timedelta(days=30)
    
    doctor_calendar_appointments = Appointment.objects.filter(
        doctor=doctor,
        appointment_date__gte=calendar_start,
        appointment_date__lte=calendar_end,
        status__in=["pending", "confirmed"],
    ).select_related("patient__user").order_by("appointment_date", "start_time")
    
    doctor_calendar_followups = FollowUp.objects.filter(
        prescription__doctor=doctor,
        scheduled_date__gte=calendar_start,
        scheduled_date__lte=calendar_end,
        status__in=["upcoming", "missed"],
    ).select_related("prescription__patient__user").order_by("scheduled_date")

    doctor_name = doctor.user.get_full_name() or doctor.user.email
    news_list = News.objects.filter(is_active=True, target_audience__in=["all", "doctors"]).order_by("-created_at")[:5]
    return render(request, "doctors/dashboard.html", {
        "rows": patient_rows,
        "today": today,
        "stats": stats,
        "doctor_name": doctor_name,
        "doctor": doctor,
        "has_patients": bool(patient_rows),
        "refund_notifications": refund_notifications,
        "today_appointments": today_appointments_qs,
        "urgent_actions": urgent_actions,
        "expiring_prescriptions": expiring_prescriptions,
        "doctor_calendar_appointments": doctor_calendar_appointments,
        "doctor_calendar_followups": doctor_calendar_followups,
        "news_list": news_list,
    })


@never_cache_auth
@login_required
def patient_list(request):
    doctor = getattr(request.user, "doctor_profile", None)
    query = request.GET.get("q", "").strip()
    verification_filter = request.GET.get("verification", "").strip()
    district_filter = request.GET.get("district", "").strip()
    prescription_filter = request.GET.get("has_prescription", "").strip()
    sort_by = request.GET.get("sort", "name").strip()

    patients_qs = Patient.objects.select_related("user").filter(is_verified=True)

    if query:
        patients_qs = patients_qs.filter(
            Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(user__email__icontains=query)
            | Q(phone_number__icontains=query)
        )

    if verification_filter == "verified":
        patients_qs = patients_qs.filter(is_verified=True)
    elif verification_filter == "pending":
        patients_qs = patients_qs.filter(is_verified=False)

    if district_filter:
        patients_qs = patients_qs.filter(district=district_filter)

    if prescription_filter == "yes":
        patients_qs = patients_qs.filter(prescriptions__doctor=doctor).distinct()
    elif prescription_filter == "no":
        patients_qs = patients_qs.exclude(prescriptions__doctor=doctor)

    if sort_by == "newest":
        patients_qs = patients_qs.order_by("-user__date_joined")
    elif sort_by == "oldest":
        patients_qs = patients_qs.order_by("user__date_joined")
    elif sort_by == "district":
        patients_qs = patients_qs.order_by("district", "user__first_name")
    else:
        patients_qs = patients_qs.order_by("user__first_name", "user__last_name")

    paginator = Paginator(patients_qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    patients = [
        {
            "id": p.pk,
            "name": p.user.get_full_name() or p.user.email,
            "district": p.district or "Dhaka",
            "phone": p.phone_number or "N/A",
            "avatar": p.avatar.url if p.avatar else None,
            "is_verified": p.is_verified,
            "date_joined": p.user.date_joined.strftime("%Y-%m-%d"),
        }
        for p in page_obj
    ]

    districts = [
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

    return render(request, "doctors/patient_list.html", {
        "patients": patients,
        "query": query,
        "verification_filter": verification_filter,
        "district_filter": district_filter,
        "prescription_filter": prescription_filter,
        "sort_by": sort_by,
        "districts": districts,
        "page_obj": page_obj,
    })


@never_cache_auth
@login_required
def update_followup_status(request, followup_id):
    doctor = getattr(request.user, "doctor_profile", None)
    follow_up = get_object_or_404(FollowUp, pk=followup_id, prescription__doctor=doctor)
    new_status = request.GET.get("status") or request.POST.get("status")
    if new_status in {"completed", "missed", "upcoming"}:
        follow_up.status = new_status
        follow_up.save()
        messages.success(request, f"✓ Follow-up status updated to '{new_status.capitalize()}'.")
    return redirect("doctors:dashboard")


@never_cache_auth
@login_required
def patient_detail(request, patient_id):
    """Doctor's patient detail view showing medical history, prescriptions,
    follow-ups, and health reports.

    Context includes:
      - Patient information and age
      - Medical history summary (AI-generated from vitals/reports)
      - Paginated prescriptions list
      - Patient health reports
      - has_active_prescription: controls 'Create Prescription' button visibility
      - missed_followups: history of missed follow-ups for this patient
    """
    from patient.models import PatientHealthReport
    doctor = getattr(request.user, "doctor_profile", None)
    patient = get_object_or_404(Patient, pk=patient_id)
    prescription_qs = (
        Prescription.objects.filter(patient=patient)
        .select_related("patient__user", "doctor__user")
        .prefetch_related("items__medicine", "follow_up")
        .order_by("-issued_at")
    )
    prescriptions = []
    for prescription in prescription_qs:
        prescriptions.append({
            "id": prescription.pk,
            "date": prescription.issued_at.strftime("%Y-%m-%d"),
            "status": prescription.get_status_display(),
            "doctor": prescription.doctor.user.get_full_name() or prescription.doctor.user.username,
            "items": [f"{item.medicine} — {item.dosage} ({item.frequency}x/day)" for item in prescription.items.all()],
            "follow_up": getattr(prescription, "follow_up", None),
            "is_locked": prescription.is_locked,
            "activates_at": prescription.activates_at,
            "expires_at": prescription.expires_at,
        })

    patient_name = patient.user.get_full_name() or patient.user.email
    summary_language = request.GET.get("lang") or request.session.get("site_lang") or "en"
    if summary_language not in {"bn", "en"}:
        summary_language = "en"

    recent_prescriptions = Prescription.objects.filter(patient=patient).select_related("doctor__user").order_by("-issued_at")[:5]
    recent_visits = patient.visits.select_related("doctor__user").order_by("-visited_at")[:5]
    recent_reports = PatientHealthReport.objects.filter(patient=patient).order_by("-date_performed")[:5]

    history_parts = []
    if recent_prescriptions:
        history_parts.append("Recent prescriptions:")
        for rx in recent_prescriptions:
            history_parts.append(f"- {rx.issued_at.strftime('%Y-%m-%d')}: {rx.diagnosis or rx.chief_complaints or 'General consultation'} with Dr. {rx.doctor.user.get_full_name() or rx.doctor.user.username}")
    if recent_visits:
        history_parts.append("Recent visit vitals:")
        for v in recent_visits:
            vitals = []
            if v.heart_rate: vitals.append(f"HR {v.heart_rate} bpm")
            if v.blood_pressure_systolic and v.blood_pressure_diastolic: vitals.append(f"BP {v.blood_pressure_systolic}/{v.blood_pressure_diastolic}")
            if v.temperature_celsius: vitals.append(f"Temp {v.temperature_celsius}°C")
            if v.weight_kg: vitals.append(f"Weight {v.weight_kg}kg")
            if v.height_cm: vitals.append(f"Height {v.height_cm}cm")
            if v.oxygen_saturation: vitals.append(f"SpO2 {v.oxygen_saturation}%")
            vitals_str = ", ".join(vitals) if vitals else "No vitals recorded"
            history_parts.append(f"- {v.visited_at.strftime('%Y-%m-%d')}: {vitals_str} with Dr. {v.doctor.user.get_full_name() or v.doctor.user.username}")
    if recent_reports:
        history_parts.append("Recent reports:")
        for r in recent_reports:
            history_parts.append(f"- {r.date_performed}: {r.title} ({r.get_report_type_display()})")

    history_text = "\n".join(history_parts) if history_parts else "No detailed medical history available yet."

    metrics_parts = []
    if recent_visits:
        latest = recent_visits.first()
        if latest.heart_rate: metrics_parts.append(f"Heart rate: {latest.heart_rate} bpm")
        if latest.blood_pressure_systolic and latest.blood_pressure_diastolic: metrics_parts.append(f"BP: {latest.blood_pressure_systolic}/{latest.blood_pressure_diastolic} mmHg")
        if latest.temperature_celsius: metrics_parts.append(f"Temperature: {latest.temperature_celsius}°C")
        if latest.weight_kg: metrics_parts.append(f"Weight: {latest.weight_kg} kg")
        if latest.height_cm: metrics_parts.append(f"Height: {latest.height_cm} cm")
        if latest.oxygen_saturation: metrics_parts.append(f"SpO2: {latest.oxygen_saturation}%")
    metrics_summary = "; ".join(metrics_parts) if metrics_parts else "No recent vitals on file."

    ai_summary = GeminiAIService.generate_clinical_summary(
        patient_name=patient_name,
        history_text=history_text,
        metrics_summary=metrics_summary,
        language=summary_language,
    )

    from patient.models import PatientHealthReport
    reports_qs = PatientHealthReport.objects.filter(patient=patient).order_by("-date_performed")
    reports = list(reports_qs[:20])

    prescriptions_paginator = Paginator(prescriptions, 10)
    rx_page = request.GET.get("rx_page")
    prescriptions_page = prescriptions_paginator.get_page(rx_page)

    patient_age = None
    if patient.date_of_birth:
        today = timezone.localdate()
        patient_age = today.year - patient.date_of_birth.year - ((today.month, today.day) < (patient.date_of_birth.month, patient.date_of_birth.day))

    has_active_prescription = Prescription.objects.filter(
        patient=patient,
        is_locked=False,
        status__in=["scheduled", "active"],
    ).exists()

    missed_followups = FollowUp.objects.filter(
        prescription__doctor=doctor,
        prescription__patient=patient,
        status="missed",
    ).select_related("prescription").order_by("-scheduled_date")[:10]

    # Missed appointments (no prescription created) — show as additional history
    missed_appointments = Appointment.objects.filter(
        doctor=doctor,
        patient=patient,
        status="missed",
        prescriptions__isnull=True,
    ).order_by("-appointment_date")[:10]

    return render(request, "doctors/patient_detail.html", {
        "patient": {
            "id": patient.pk,
            "name": patient_name,
            "avatar": patient.avatar.url if patient.avatar else None,
            "gender": patient.gender,
            "date_of_birth": patient.date_of_birth,
            "age": patient_age,
        },
        "prescriptions": prescriptions_page,
        "reports": reports,
        "adherence": 100 if prescriptions else None,
        "ai_summary": ai_summary,
        "prescriptions_page": prescriptions_page,
        "has_active_prescription": has_active_prescription,
        "missed_followups": missed_followups,
        "missed_appointments": missed_appointments,
    })


@never_cache_auth
@login_required
def create_prescription(request, patient_id):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Only verified doctor profiles can write prescriptions.")
        return redirect("doctors:dashboard")

    patient = get_object_or_404(Patient, pk=patient_id)

    # Check if doctor has appointment or upcoming follow-up with this patient for today
    today = timezone.localdate()
    now = timezone.localtime(timezone.now())
    tz = timezone.get_current_timezone()

    # Prescription can be created within a 8-hour window:
    # FROM 4 hours BEFORE the appointment start time
    # TO 4 hours AFTER the appointment start time.
    eligibility_appointment = None
    todays_appointments = Appointment.objects.filter(
        doctor=doctor,
        patient=patient,
        appointment_date=today,
        status__in=["pending", "confirmed"],
    ).order_by("start_time")
    for apt in todays_appointments:
        apt_start = timezone.make_aware(timezone.datetime.combine(apt.appointment_date, apt.start_time), tz)
        window_start = apt_start - timezone.timedelta(hours=4)
        window_end = apt_start + timezone.timedelta(hours=4)
        if window_start <= now <= window_end:
            eligibility_appointment = apt
            break

    has_appointment = eligibility_appointment is not None

    # Prevent creating a new prescription if one already exists for this appointment
    if eligibility_appointment and Prescription.objects.filter(appointment=eligibility_appointment).exists():
        messages.error(request, "A prescription has already been created for this appointment.")
        return redirect("doctors:patient_detail", patient_id=patient.pk)

    # Follow-ups scheduled for today can still be prescribed (no fixed time window)
    has_upcoming_followup = FollowUp.objects.filter(
        prescription__doctor=doctor,
        prescription__patient=patient,
        status="upcoming",
        scheduled_date=today,
    ).exists()

    if not has_appointment and not has_upcoming_followup:
        messages.error(request, "Prescription can only be created within 4 hours after appointment time")
        return redirect("doctors:patient_detail", patient_id=patient.pk)

    # Use the appointment that falls within the prescription window for timing
    appointment = eligibility_appointment

    if request.method == "POST":
        chief_complaints = request.POST.get("chief_complaints", "").strip()
        diagnosis = request.POST.get("diagnosis", "").strip()
        doctor_notes = request.POST.get("doctor_notes", "").strip()
        follow_up_date_str = request.POST.get("follow_up_date", "").strip()

        patient_age = request.POST.get("patient_age", "").strip()
        patient_gender = request.POST.get("patient_gender", "").strip()
        patient_email = request.POST.get("patient_email", "").strip()
        patient_phone = request.POST.get("patient_phone", "").strip()

        if patient_gender:
            patient.gender = patient_gender
        if patient_email:
            patient.user.email = patient_email
            patient.user.save(update_fields=["email"])
        if patient_phone:
            patient.phone_number = patient_phone
        if patient_age:
            try:
                age_val = int(patient_age)
                today = timezone.localdate()
                dob = today.replace(year=today.year - age_val)
                patient.date_of_birth = dob
            except (ValueError, TypeError):
                pass
        patient.save(update_fields=["gender", "phone_number", "date_of_birth"] + (["user"] if patient_email else []))

        # Dynamic lists
        med_names = request.POST.getlist("med_name[]")
        med_dosages = request.POST.getlist("med_dosage[]")
        med_frequencies = request.POST.getlist("med_frequency[]")
        med_timings = request.POST.getlist("med_timing[]")
        med_durations = request.POST.getlist("med_duration[]")
        med_notes_list = request.POST.getlist("med_notes[]")

        test_names = [t.strip() for t in request.POST.getlist("test_name[]") if t.strip()]
        advice_rules = [a.strip() for a in request.POST.getlist("advice_rule[]") if a.strip()]

        fu_date = None
        if follow_up_date_str:
            try:
                fu_date = timezone.datetime.strptime(follow_up_date_str, "%Y-%m-%d").date()
            except ValueError:
                fu_date = None

        # Calculate timing
        now = timezone.localtime(timezone.now())
        tz = timezone.get_current_timezone()
        expires_at = now + timezone.timedelta(hours=4)
        activates_at = None
        if appointment:
            apt_datetime = timezone.datetime.combine(
                appointment.appointment_date,
                appointment.start_time,
            )
            apt_datetime = timezone.make_aware(apt_datetime, tz)
            activates_at = apt_datetime - timezone.timedelta(minutes=10)

        new_status = "scheduled" if activates_at and now < activates_at else "active"

        # Supersede previous active prescriptions only if new one is active
        if new_status == "active":
            Prescription.objects.filter(patient=patient, status="active").update(status="completed")

        # Create Prescription Instance
        prescription = Prescription.objects.create(
            doctor=doctor,
            patient=patient,
            appointment=appointment,
            chief_complaints=chief_complaints,
            diagnosis=diagnosis,
            tests_investigations="\n".join(test_names),
            advice_rules="\n".join(advice_rules),
            doctor_notes=doctor_notes,
            next_followup_date=fu_date,
            status=new_status,
            activates_at=activates_at,
            expires_at=expires_at,
            is_locked=False,
        )

        # Save visit vitals if any provided
        from patient.models import PatientVisit
        vitals_fields = [
            "heart_rate", "blood_pressure_systolic", "blood_pressure_diastolic",
            "temperature_celsius", "weight_kg", "height_cm", "oxygen_saturation", "visit_notes"
        ]
        has_vitals = any(request.POST.get(f) for f in vitals_fields)
        if has_vitals:
            PatientVisit.objects.create(
                patient=patient,
                appointment=appointment,
                prescription=prescription,
                doctor=doctor,
                heart_rate=request.POST.get("heart_rate") or None,
                blood_pressure_systolic=request.POST.get("blood_pressure_systolic") or None,
                blood_pressure_diastolic=request.POST.get("blood_pressure_diastolic") or None,
                temperature_celsius=request.POST.get("temperature_celsius") or None,
                weight_kg=request.POST.get("weight_kg") or None,
                height_cm=request.POST.get("height_cm") or None,
                oxygen_saturation=request.POST.get("oxygen_saturation") or None,
                visit_notes=request.POST.get("visit_notes", "").strip(),
            )

        # Loop and save medicines
        for i, name in enumerate(med_names):
            name_clean = name.strip()
            if not name_clean:
                continue
            dosage = med_dosages[i].strip() if i < len(med_dosages) and med_dosages[i].strip() else "1 tablet"
            try:
                freq = int(med_frequencies[i]) if i < len(med_frequencies) else 2
            except (ValueError, TypeError):
                freq = 2
            timing = med_timings[i].strip() if i < len(med_timings) and med_timings[i].strip() else "after_meal"
            try:
                duration = int(med_durations[i]) if i < len(med_durations) else 7
            except (ValueError, TypeError):
                duration = 7
            notes = med_notes_list[i].strip() if i < len(med_notes_list) else ""

            med_obj, _ = Medicine.objects.get_or_create(
                brand_name=name_clean,
                defaults={"generic_name": name_clean, "form": "tablet"}
            )

            item_obj = PrescriptionItem.objects.create(
                prescription=prescription,
                medicine=med_obj,
                dosage=dosage,
                frequency=freq,
                timing_relation_to_meal=timing,
                duration_days=duration,
                special_instructions=notes,
            )

            # Auto-generate daily dose schedules for the full duration based on exact dosage notation
            from prescriptions.models import get_active_dose_slots
            today_date = timezone.localdate()
            active_slots = get_active_dose_slots(dosage, freq)
            for day_offset in range(max(1, duration)):
                sch_date = today_date + timezone.timedelta(days=day_offset)
                for slot in active_slots:
                    ReminderSchedule.objects.get_or_create(
                        prescription_item=item_obj,
                        scheduled_date=sch_date,
                        reminder_time=slot["time"],
                        defaults={"status": "pending"}
                    )

        # Auto-complete any existing upcoming follow-ups for this patient with this doctor
        FollowUp.objects.filter(
            prescription__doctor=doctor,
            prescription__patient=patient,
            status="upcoming"
        ).update(status="completed")

        # Auto-complete any pending/confirmed appointments for this doctor+patient on the appointment date
        if appointment:
            Appointment.objects.filter(
                doctor=doctor,
                patient=patient,
                status__in=["pending", "confirmed"],
                appointment_date=appointment.appointment_date,
            ).update(status="completed")

        # Save new FollowUp object if date selected
        if fu_date:
            follow_up = FollowUp.objects.create(
                prescription=prescription,
                scheduled_date=fu_date,
                status="upcoming",
                booking_deadline=fu_date + timezone.timedelta(days=4),
            )

        messages.success(request, f"✓ Medical Prescription #{prescription.pk} issued successfully for {patient.user.get_full_name() or patient.user.email}!")
        pdf_url = reverse("doctors:download_prescription", kwargs={"prescription_id": prescription.pk})
        patient_detail_url = reverse("doctors:patient_detail", kwargs={"patient_id": patient.pk})
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Prescription Issued</title>
            <script>
                window.onload = function() {{
                    window.open('{pdf_url}', '_blank');
                    window.location.href = '{patient_detail_url}';
                }};
            </script>
        </head>
        <body>
            <p>Prescription issued successfully. Opening PDF in new tab...</p>
        </body>
        </html>
        """
        return HttpResponse(html)

    # GET request - check available appointment for context
    available_appointment = appointment
    return render(request, "doctors/create_prescription.html", {
        "patient": patient,
        "patient_name": patient.user.get_full_name() or patient.user.email,
        "doctor": doctor,
        "has_confirmed_appointment": has_appointment,
        "has_upcoming_followup": has_upcoming_followup,
        "available_appointment": available_appointment,
    })


@never_cache_auth
@login_required
def edit_prescription(request, prescription_id):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Only verified doctor profiles can edit prescriptions.")
        return redirect("doctors:dashboard")

    prescription = get_object_or_404(Prescription, pk=prescription_id, doctor=doctor)

    if prescription.is_locked:
        messages.error(request, "This prescription is locked and can no longer be edited. The 4-hour editing window has expired.")
        return redirect("doctors:prescription_detail", prescription_id=prescription.pk)

    patient = prescription.patient
    now = timezone.localtime(timezone.now())

    if request.method == "POST":
        prescription.chief_complaints = request.POST.get("chief_complaints", "").strip()
        prescription.diagnosis = request.POST.get("diagnosis", "").strip()
        prescription.doctor_notes = request.POST.get("doctor_notes", "").strip()
        prescription.tests_investigations = "\n".join([t.strip() for t in request.POST.getlist("test_name[]") if t.strip()])
        prescription.advice_rules = "\n".join([a.strip() for a in request.POST.getlist("advice_rule[]") if a.strip()])
        prescription.save()

        PrescriptionItem.objects.filter(prescription=prescription).delete()

        med_names = request.POST.getlist("med_name[]")
        med_dosages = request.POST.getlist("med_dosage[]")
        med_frequencies = request.POST.getlist("med_frequency[]")
        med_timings = request.POST.getlist("med_timing[]")
        med_durations = request.POST.getlist("med_duration[]")
        med_notes_list = request.POST.getlist("med_notes[]")

        for i, name in enumerate(med_names):
            name_clean = name.strip()
            if not name_clean:
                continue
            dosage = med_dosages[i].strip() if i < len(med_dosages) and med_dosages[i].strip() else "1 tablet"
            try:
                freq = int(med_frequencies[i]) if i < len(med_frequencies) else 2
            except (ValueError, TypeError):
                freq = 2
            timing = med_timings[i].strip() if i < len(med_timings) and med_timings[i].strip() else "after_meal"
            try:
                duration = int(med_durations[i]) if i < len(med_durations) else 7
            except (ValueError, TypeError):
                duration = 7
            notes = med_notes_list[i].strip() if i < len(med_notes_list) else ""

            med_obj, _ = Medicine.objects.get_or_create(
                brand_name=name_clean,
                defaults={"generic_name": name_clean, "form": "tablet"}
            )
            PrescriptionItem.objects.create(
                prescription=prescription,
                medicine=med_obj,
                dosage=dosage,
                frequency=freq,
                timing_relation_to_meal=timing,
                duration_days=duration,
                special_instructions=notes,
            )

        messages.success(request, f"✓ Prescription #{prescription.pk} updated successfully.")
        return redirect("doctors:prescription_detail", prescription_id=prescription.pk)

    existing_items = prescription.items.select_related("medicine").all()
    return render(request, "doctors/edit_prescription.html", {
        "prescription": prescription,
        "patient": patient,
        "patient_name": patient.user.get_full_name() or patient.user.email,
        "doctor": doctor,
        "existing_items": existing_items,
        "is_edit": True,
    })


@never_cache_auth
@login_required
def notifications(request):
    from accounts.models import AppNotification
    notifications_qs = AppNotification.objects.filter(user=request.user)
    items = list(notifications_qs[:30])
    notifications_qs.filter(is_read=False).update(is_read=True)
    return render(request, "doctors/notifications.html", {"items": items})


@never_cache_auth
@login_required
def history(request):
    doctor = getattr(request.user, "doctor_profile", None)
    activity = []
    page_obj = None
    if doctor:
        qs = Prescription.objects.filter(doctor=doctor).select_related("patient__user").order_by("-issued_at")
        paginator = Paginator(qs, 20)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)
        for prescription in page_obj:
            activity.append({
                "date": prescription.issued_at.strftime("%Y-%m-%d"),
                "action": f"Issued prescription for {prescription.patient.user.get_full_name() or prescription.patient.user.email}",
                "prescription_id": prescription.pk,
            })
    return render(request, "doctors/history.html", {"activity": activity, "page_obj": page_obj})


@never_cache_auth
@login_required
def profile_edit(request):
    doctor = getattr(request.user, "doctor_profile", None)
    categories = ["General Physician", "Cardiologist", "Dermatologist", "Pediatrician", "Orthopedic", "Gastroenterologist", "Neurologist", "ENT Specialist"]

    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()
        specialty = request.POST.get("specialty", "General Physician").strip()
        clinic_name = request.POST.get("clinic_name", "").strip()
        location_text = request.POST.get("location_text", "").strip()
        bio = request.POST.get("bio", "").strip()
        experience_years = request.POST.get("experience_years", "").strip()
        consultation_fee = request.POST.get("consultation_fee", "").strip()
        designation = request.POST.get("designation", "").strip()
        degrees = request.POST.get("degrees", "").strip()
        bmdc_registration_year = request.POST.get("bmdc_registration_year", "").strip()

        errors = []
        if not experience_years:
            errors.append("Experience years is required.")
        if not consultation_fee:
            errors.append("Consultation fee is required.")

        if full_name:
            names = full_name.split(" ", 1)
            request.user.first_name = names[0]
            request.user.last_name = names[1] if len(names) > 1 else ""
            request.user.save()

        if doctor:
            doctor.specialty = specialty
            doctor.clinic_name = clinic_name
            doctor.location_text = location_text
            doctor.bio = bio
            doctor.designation = designation
            doctor.degrees = degrees
            try:
                doctor.experience_years = int(experience_years) if experience_years else 0
            except (ValueError, TypeError):
                errors.append("Experience years must be a valid number.")
            try:
                doctor.consultation_fee = Decimal(consultation_fee) if consultation_fee else Decimal("0")
            except (ValueError, TypeError):
                errors.append("Consultation fee must be a valid amount.")
            try:
                doctor.bmdc_registration_year = int(bmdc_registration_year) if bmdc_registration_year else None
            except (ValueError, TypeError):
                errors.append("BMDC Registration Year must be a valid number.")

            if request.FILES.get("avatar"):
                old_avatar = doctor.avatar
                doctor.avatar = request.FILES.get("avatar")
                doctor.avatar_updated_at = timezone.now()
                if old_avatar and old_avatar.name != doctor.avatar.name:
                    old_avatar.delete(save=False)
            doctor.save()

        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect("doctors:profile_edit")

        messages.success(request, "✓ Doctor profile updated successfully.")
        return redirect("doctors:profile_edit")

    doctor_payload = {
        "name": request.user.get_full_name() or request.user.email,
        "specialty": doctor.specialty if doctor else "General Physician",
        "bio": doctor.bio if doctor else "",
        "clinic_name": doctor.clinic_name if doctor else "",
        "location_text": doctor.location_text if doctor else "",
        "experience_years": doctor.experience_years if doctor else 0,
        "consultation_fee": doctor.consultation_fee if doctor else 0,
        "avatar": doctor.avatar.url if (doctor and doctor.avatar) else None,
        "avatar_updated_at": doctor.avatar_updated_at if doctor else None,
        "designation": doctor.designation if doctor else "",
        "degrees": doctor.degrees if doctor else "",
        "bmdc_registration_year": doctor.bmdc_registration_year if doctor else None,
    }
    return render(request, "doctors/profile_edit.html", {"doctor": doctor_payload, "categories": categories})


@never_cache_auth
@login_required
def download_prescription(request, prescription_id):
    from prescriptions.views import _build_prescription_pdf
    prescription = get_object_or_404(Prescription, pk=prescription_id)
    buffer = _build_prescription_pdf(prescription)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = f"inline; filename=prescription_{prescription.pk}.pdf"
    return response


@never_cache_auth
@login_required
def prescription_detail(request, prescription_id):
    prescription = get_object_or_404(Prescription, pk=prescription_id)
    summary_language = request.GET.get("lang") or request.session.get("site_lang") or "en"
    if summary_language not in {"bn", "en"}:
        summary_language = "en"

    from patient.services import summarize_prescription
    summary_payload = summarize_prescription(prescription, summary_language)

    # Check if prescription is locked (4 hours editing window expired)
    now = timezone.localtime(timezone.now())
    is_locked = prescription.is_locked or (prescription.expires_at and now > prescription.expires_at)

    # Build deep_analysis structured data for the template
    is_bn = summary_language == "bn"
    items = list(prescription.items.select_related("medicine").all())

    # Medicine breakdown
    medicines_breakdown = []
    for item in items:
        generic_name = item.medicine.generic_name if item.medicine.generic_name else ""
        dosage = item.dosage or "1 tablet"
        frequency = f"{item.frequency}x/day" if item.frequency else "2x/day"
        duration = f"{item.duration_days} days" if item.duration_days else "7 days"
        timing_label = item.get_timing_relation_to_meal_display()
        medicines_breakdown.append({
            "name": item.medicine.brand_name,
            "generic": generic_name,
            "purpose": item.medicine.form or "As prescribed",
            "how_to_take": f"{dosage} ({frequency}) — {timing_label}",
            "duration_guidance": duration,
            "side_effects": [item.special_instructions or "None documented"],
        })

    # Static guidance sections (fallback when AI is unavailable)
    diet_interactions = []
    lifestyle_tips = []
    warning_signs = []

    if is_bn:
        diet_interactions = [
            "কোনো ওষুধ খাবারের সঙ্গে নির্দিষ্ট সময়ে নিন — খালি পেটে বা খাবার পরিষ্কারে গুরুত্ব দিন।",
            "কফি, চা বা অ্যাল�হলজনিত খাদ্য ও পদার্থ এড়িয়ে চলুন।",
        ]
        lifestyle_tips = [
            "নির্ধারিত সময়ে ওষুধ নিন — একই সময়ে সেবন করুন।",
            "পর্যাপ্ত পরিমাণে পানি পান করুন (৮-১০ গ্লাস)।",
            "ডাক্তারের পরামর্শ ব্যতিয়ে কোনো ওষুধ বন্ধ করবেন না।",
        ]
        warning_signs = [
            "ত্বকে লাল ফোঁটা, চুল পড়ে যাওয়া, বা অস্বাভাবিক দুর্বলতা হলে ডাক্তারের সঙ্গে যোগাযোগ করুন।",
            "অস্বাভাবিক বুক ব্যথা, আকস্মিক শ্বাসকষ্ট বা চেতনাহীনতায় জরুরি হাসপাতালে যান।",
        ]
        follow_up_guidance = "আগামী ফলো-আপ অয়েগে এই ওষুধের তালিকা, সাম্প্রতির উপসর্গ এবং ডাক্তারের টিপসহ নোট নিয়ে আসুন।"
    else:
        diet_interactions = [
            "Take medications at consistent times — with or without food as indicated.",
            "Avoid caffeine, alcohol, and grapefruit juice unless approved by your doctor.",
        ]
        lifestyle_tips = [
            "Take medications exactly as prescribed — set daily alarms.",
            "Drink plenty of water (8-10 glasses daily).",
            "Do not stop or change dosage without consulting your doctor.",
        ]
        warning_signs = [
            "Seek immediate medical attention for skin rash, hives, or sudden dizziness.",
            "For severe chest pain or loss of consciousness, go to the nearest ER.",
        ]
        follow_up_guidance = "Bring this medication list, recent symptoms, and any questions to your next follow-up appointment."

    deep_analysis = {
        "overview": summary_payload.get("overview", ""),
        "medicines_breakdown": medicines_breakdown,
        "diet_interactions": diet_interactions,
        "lifestyle_tips": lifestyle_tips,
        "warning_signs": warning_signs,
        "follow_up_guidance": follow_up_guidance,
    }

    return render(request, "patient/prescription_detail.html", {
        "prescription": prescription,
        "summary_text": summary_payload.get("text", ""),
        "summary_overview": summary_payload.get("overview", ""),
        "summary_schedule": summary_payload.get("schedule", ""),
        "summary_precautions": summary_payload.get("precautions", ""),
        "summary_warnings": summary_payload.get("warnings", ""),
        "summary_source": summary_payload.get("source", "local"),
        "summary_language": summary_language,
        "deep_analysis": deep_analysis,
        "is_locked": is_locked,
    })


@never_cache_auth
@login_required
def schedule_management(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Only doctors can manage schedules.")
        return redirect("home")

    if request.method == "POST":
        day = request.POST.get("day_of_week")
        start = request.POST.get("start_time")
        end = request.POST.get("end_time")
        slot = request.POST.get("slot_duration_minutes", 20)
        if day and start and end:
            DoctorSchedule.objects.update_or_create(
                doctor=doctor,
                day_of_week=day,
                defaults={
                    "start_time": start,
                    "end_time": end,
                    "slot_duration_minutes": int(slot),
                    "is_active": True,
                },
            )
            messages.success(request, "Schedule updated successfully.")
        return redirect("doctors:schedule_management")

    schedules = DoctorSchedule.objects.filter(doctor=doctor).order_by("day_of_week", "start_time")
    days = DoctorSchedule.DAY_CHOICES
    return render(request, "doctors/schedule_management.html", {"schedules": schedules, "days": days})


@never_cache_auth
@login_required
def delete_schedule(request, schedule_id):
    doctor = getattr(request.user, "doctor_profile", None)
    schedule = get_object_or_404(DoctorSchedule, pk=schedule_id, doctor=doctor)
    schedule.delete()
    messages.success(request, "Schedule removed.")
    return redirect("doctors:schedule_management")


def _auto_detect_missed_for_doctor(doctor):
    """Auto-mark past appointments as 'missed' if no prescription was issued.
    Only applies to appointments whose date has already passed and whose
    status is still 'confirmed' or 'pending'. Sends a notification to the
    patient so they know to rebook."""
    today = timezone.localdate()
    missed_appointments = Appointment.objects.filter(
        doctor=doctor,
        appointment_date__lt=today,
        status__in=["confirmed", "pending"],
    ).select_related("patient__user")
    count = 0
    for apt in missed_appointments:
        has_prescription = Prescription.objects.filter(
            doctor=doctor,
            patient=apt.patient,
            issued_at__date__gte=apt.appointment_date,
        ).exists()
        if not has_prescription:
            apt.status = "missed"
            apt.save(update_fields=["status"])
            AppNotification.objects.create(
                user=apt.patient.user,
                title="Appointment Marked as Missed",
                message=f"Your appointment on {apt.appointment_date.strftime('%d %b %Y')} with Dr. {doctor.user.get_full_name()} was marked as missed (no prescription generated). Please book again if needed.",
                notification_type="booking",
                link_url=reverse("patient:doctor_list"),
            )
            count += 1
    return count


def _auto_mark_missed_today(doctor=None, patient=None):
    """Auto-mark today's appointments as missed once the appointment
    window (start_time + 4h) has passed and no prescription was issued."""
    today = timezone.localdate()
    now = timezone.localtime(timezone.now())
    tz = timezone.get_current_timezone()
    qs = Appointment.objects.all()
    if doctor:
        qs = qs.filter(doctor=doctor)
    if patient:
        qs = qs.filter(patient=patient)
    qs = qs.filter(
        appointment_date=today,
        status__in=["pending", "confirmed"],
    ).select_related("patient__user", "doctor__user")

    for apt in qs:
        apt_start = timezone.make_aware(
            timezone.datetime.combine(apt.appointment_date, apt.start_time), tz
        )
        window_end = apt_start + timezone.timedelta(hours=4)
        if now > window_end and not apt.prescriptions.exists():
            apt.status = "missed"
            apt.save(update_fields=["status"])
            AppNotification.objects.create(
                user=apt.patient.user,
                title="Appointment Marked as Missed",
                message=f"Your appointment on {apt.appointment_date.strftime('%d %b %Y')} with Dr. {apt.doctor.user.get_full_name()} was marked as missed (no prescription generated). Please book again if needed.",
                notification_type="booking",
                link_url=reverse("patient:doctor_list"),
            )
    return None


@never_cache_auth
@login_required
def appointment_list(request):
    """Display the doctor's appointment list with optional filtering.

    Filters: status (pending/confirmed/completed/etc), date, month, or year.
    Includes stats cards (total, pending, completed, etc.) and a 4h prescription
    countdown timer for each pending/confirmed appointment that has started
    but not yet expired or received a prescription.
    """
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Only doctors can view appointments.")
        return redirect("home")

    _auto_detect_missed_for_doctor(doctor)
    _auto_mark_missed_today(doctor=doctor)

    status_filter = request.GET.get("status", "")
    filter_type = request.GET.get("filter_type", "")
    filter_value = request.GET.get("filter_value", "")
    filter_month = request.GET.get("filter_month", "")
    filter_year = request.GET.get("filter_year", "")
    today = timezone.localdate()

    base_qs = Appointment.objects.filter(doctor=doctor).select_related("patient__user").prefetch_related("prescriptions")
    if status_filter == "today":
        appointments = base_qs.filter(appointment_date=today).order_by("-appointment_date", "-start_time")
    elif status_filter == "pending":
        appointments = base_qs.filter(status="pending", payment_status="pending").order_by("-appointment_date", "-start_time")
    elif status_filter == "pending_verification":
        appointments = base_qs.filter(payment_status="pending_verification").order_by("-appointment_date", "-start_time")
    elif status_filter == "missed":
        appointments = base_qs.filter(status="missed").order_by("-appointment_date", "-start_time")
    elif status_filter:
        appointments = base_qs.filter(status=status_filter).order_by("-appointment_date", "-start_time")
    else:
        appointments = base_qs.order_by("-appointment_date", "-start_time")

    if filter_type == "date" and filter_value:
        appointments = appointments.filter(appointment_date=filter_value)
    elif filter_type == "month" and filter_month and filter_year:
        appointments = appointments.filter(appointment_date__startswith=f"{filter_year}-{filter_month}")
    elif filter_type == "year" and filter_year:
        appointments = appointments.filter(appointment_date__startswith=filter_year)

    paginator = Paginator(appointments, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    all_appointments = base_qs
    stats = {
        "total": all_appointments.count(),
        "pending": all_appointments.filter(status="pending", payment_status="pending").count(),
        "pending_verification": all_appointments.filter(payment_status="pending_verification").count(),
        "confirmed": all_appointments.filter(status="confirmed").count(),
        "completed": all_appointments.filter(status="completed").count(),
        "missed": all_appointments.filter(status="missed").count(),
        "cancelled": all_appointments.filter(status="cancelled").count(),
        "cancellation_pending": all_appointments.filter(status="cancellation_pending").count(),
        "today": all_appointments.filter(appointment_date=today).count(),
    }

    # Get distinct years and months for filter dropdowns
    date_aggregates = all_appointments.aggregate(
        min_date=Min("appointment_date"),
        max_date=Max("appointment_date"),
    )
    years = []
    months = []
    if date_aggregates["min_date"] and date_aggregates["max_date"]:
        min_year = date_aggregates["min_date"].year
        max_year = date_aggregates["max_date"].year
        years = list(range(min_year, max_year + 1))
        months = [
            ("01", "January"), ("02", "February"), ("03", "March"), ("04", "April"),
            ("05", "May"), ("06", "June"), ("07", "July"), ("08", "August"),
            ("09", "September"), ("10", "October"), ("11", "November"), ("12", "December"),
        ]

    selected_month = ""
    selected_year = ""
    if filter_type == "month" and filter_month and filter_year:
        selected_month = filter_month
        selected_year = filter_year
    elif filter_type == "year" and filter_year:
        selected_year = filter_year

    # Compute per-appointment timer flags (BDT timezone)
    # - window_end: 4 hours after appointment start (prescription deadline)
    # - time_passed: whether the appointment start time has already occurred
    # - has_prescription: whether a prescription was already created for this appointment
    # - remaining_seconds: countdown to window_end (0 if appointment is in future or prescription exists)
    # - is_window_expired: True if prescription exists, status is terminal, or 4h window elapsed
    now = timezone.localtime(timezone.now())
    tz = timezone.get_current_timezone()
    for apt in page_obj:
        apt_start = timezone.make_aware(timezone.datetime.combine(apt.appointment_date, apt.start_time), tz)
        apt_end = timezone.make_aware(timezone.datetime.combine(apt.appointment_date, apt.end_time or apt.start_time), tz)
        # 4-hour prescription window: starts at appointment start time, ends 4h later
        apt.window_end = apt_start + timezone.timedelta(hours=4)
        # Timer only shows after appointment time has passed
        apt.time_passed = now > apt_start
        # If a prescription exists, the window requirement is satisfied
        apt.has_prescription = apt.prescriptions.exists()
        # Remaining seconds for countdown (0 if not yet started or prescription done)
        apt.remaining_seconds = max(0, int((apt.window_end - now).total_seconds())) if apt.time_passed and not apt.has_prescription else 0
        # Window considered expired if: prescription exists, terminal status, or 4h elapsed
        apt.is_window_expired = apt.has_prescription or apt.status in ("completed", "missed", "cancelled", "refunded") or (now > apt.window_end and apt.status in ("pending", "confirmed", "cancellation_pending"))

    return render(request, "doctors/appointment_list.html", {
        "appointments": page_obj,
        "status_filter": status_filter,
        "stats": stats,
        "today": today,
        "page_obj": page_obj,
        "filter_type": filter_type,
        "filter_value": filter_value,
        "filter_month": filter_month,
        "filter_year": filter_year,
        "years": years,
        "months": months,
        "selected_month": selected_month,
        "selected_year": selected_year,
    })


@never_cache_auth
@login_required
def appointment_detail(request, appointment_id):
    if request.user.is_staff or request.user.is_superuser:
        appointment = get_object_or_404(Appointment, pk=appointment_id)
    else:
        doctor = getattr(request.user, "doctor_profile", None)
        appointment = get_object_or_404(Appointment, pk=appointment_id, doctor=doctor)

    if request.method == "POST":
        # Once a prescription is created for this appointment, the status is locked.
        if appointment.prescriptions.exists():
            messages.error(request, "This appointment was completed via a prescription and its status can no longer be changed.")
            return redirect("doctors:appointment_detail", appointment_id=appointment.pk)

        previous_status = appointment.status
        new_status = request.POST.get("status", appointment.status)
        appointment.notes = request.POST.get("notes", appointment.notes)

        # Doctor-initiated cancellation: full refund, no platform fee
        if new_status == "cancelled" and previous_status != "cancelled":
            appointment.status = "cancelled"
            appointment.notes = request.POST.get("notes", appointment.notes)
            if appointment.payment_status == "paid":
                appointment.refund_status = "full"
                appointment.refund_amount = appointment.fee_bdt
                appointment.payment_status = "refunded"
                appointment.platform_fee_bdt = Decimal("0.00")
                appointment.net_doctor_payout_bdt = Decimal("0.00")
                appointment.save()

                patient = appointment.patient
                patient.balance = (patient.balance or Decimal("0")) + appointment.refund_amount
                patient.save(update_fields=["balance"])

                AppNotification.objects.create(
                    user=patient.user,
                    title="Appointment Cancelled — Full Refund",
                    message=f"Your appointment on {appointment.appointment_date} with Dr. {doctor.user.get_full_name() or doctor.user.username} was cancelled by the doctor. A full refund of {appointment.refund_amount} BDT has been credited to your wallet.",
                    notification_type="booking",
                    link_url=reverse("patient:appointments"),
                )
                messages.success(request, f"Appointment cancelled. Full refund of {appointment.refund_amount} BDT issued to patient.")
            else:
                appointment.save()
                messages.success(request, "Appointment cancelled.")
        else:
            appointment.status = new_status
            appointment.save()
            messages.success(request, "Appointment updated.")
        return redirect("doctors:appointment_detail", appointment_id=appointment.pk)

    return render(request, "doctors/appointment_detail.html", {"appointment": appointment})


@never_cache_auth
@login_required
@never_cache_auth
@login_required
def doctor_financial_report(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Only doctors can view financial reports.")
        return redirect("home")

    appointments = Appointment.objects.filter(doctor=doctor).select_related("patient__user").order_by("-appointment_date", "-start_time")

    import io
    from decimal import Decimal
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.pdfbase import pdfmetrics, ttfonts

    pdf_font_name = "Helvetica"
    for font_path in [
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\solaimanlipi.ttf",
        r"C:\Windows\Fonts\kalpurush.ttf",
    ]:
        if os.path.exists(font_path):
            try:
                font_obj = ttfonts.TTFont("pdf_unicode_font", font_path)
                pdfmetrics.registerFont(font_obj)
                pdfmetrics.registerFontFamily(
                    "pdf_unicode_font",
                    normal="pdf_unicode_font",
                    bold="pdf_unicode_font",
                    italic="pdf_unicode_font",
                    boldItalic="pdf_unicode_font",
                )
                pdf_font_name = "pdf_unicode_font"
                break
            except Exception:
                continue

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm, leftMargin=15 * mm, rightMargin=15 * mm)
    styles = getSampleStyleSheet()

    teal = colors.HexColor("#0f766e")
    dark = colors.HexColor("#1c1917")
    slate = colors.HexColor("#57534e")
    light_bg = colors.HexColor("#f0fdfa")

    title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=18, textColor=teal, spaceAfter=2, leading=22, fontName=pdf_font_name)
    subtitle_style = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=9, textColor=slate, spaceAfter=10, leading=12, fontName=pdf_font_name)
    header_style = ParagraphStyle("header", parent=styles["Normal"], fontSize=8, textColor=colors.white, fontName=pdf_font_name)
    cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, textColor=dark, leading=11, fontName=pdf_font_name)

    elements = []
    elements.append(Paragraph("Doctor Financial & Payout Statement", title_style))
    elements.append(Paragraph(f"Doctor: <b>Dr. {request.user.get_full_name()}</b> (#DOC-{doctor.id}) | Date: <b>{timezone.localdate().strftime('%d %b %Y')}</b>", subtitle_style))

    table_data = [
        [
            Paragraph("<b>Date</b>", header_style),
            Paragraph("<b>Patient Name</b>", header_style),
            Paragraph("<b>Fee</b>", header_style),
            Paragraph("<b>Platform Fee</b>", header_style),
            Paragraph("<b>Net Payout</b>", header_style),
            Paragraph("<b>Payment Status</b>", header_style),
        ]
    ]

    total_fee = Decimal("0.00")
    total_platform = Decimal("0.00")
    total_payout = Decimal("0.00")

    for apt in appointments:
        fee = Decimal(str(apt.fee_bdt or 0))
        plat = Decimal(str(apt.platform_fee_bdt or 0))
        payout = Decimal(str(apt.net_doctor_payout_bdt or 0))

        total_fee += fee
        total_platform += plat
        total_payout += payout

        patient_name = apt.patient.user.get_full_name() or apt.patient.user.username

        table_data.append([
            Paragraph(apt.appointment_date.strftime("%d %b %Y"), cell_style),
            Paragraph(patient_name, cell_style),
            Paragraph(f"BDT {fee:,.2f}", cell_style),
            Paragraph(f"BDT {plat:,.2f}", cell_style),
            Paragraph(f"BDT {payout:,.2f}", cell_style),
            Paragraph(apt.get_payment_status_display(), cell_style),
        ])

    table_data.append([
        Paragraph("<b>TOTALS</b>", cell_style),
        Paragraph("", cell_style),
        Paragraph(f"<b>BDT {total_fee:,.2f}</b>", cell_style),
        Paragraph(f"<b>BDT {total_platform:,.2f}</b>", cell_style),
        Paragraph(f"<b>BDT {total_payout:,.2f}</b>", cell_style),
        Paragraph("", cell_style),
    ])

    col_widths = [25 * mm, 50 * mm, 30 * mm, 30 * mm, 30 * mm, 20 * mm]
    t = Table(table_data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), teal),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.HexColor("#e7e5e4")),
        ('BACKGROUND', (0, -1), (-1, -1), light_bg),
        ('LINEABOVE', (0, -1), (-1, -1), 1, teal),
    ]))
    elements.append(t)

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'inline; filename="doctor_financial_report.pdf"'
    return response


def _credit_refund_to_patient(appointment):
    """Credit the appointment refund amount to the patient's wallet balance
    and notify them. Only refunds from pending/confirmed appointments are credited."""
    if appointment.status not in ("pending", "confirmed", "cancellation_pending", "cancelled"):
        return
    patient = appointment.patient
    refund = appointment.refund_amount or Decimal("0")
    if refund <= 0:
        return
    patient.balance = (patient.balance or Decimal("0")) + refund
    patient.save(update_fields=["balance"])
    AppNotification.objects.create(
        user=patient.user,
        title="Refund Credited to Wallet",
        message=f"A refund of {refund} BDT has been credited to your CareBridge wallet balance for the appointment on {appointment.appointment_date}.",
        notification_type="booking",
        link_url=reverse("patient:appointments"),
    )


@never_cache_auth
@login_required
def approve_cancellation(request, appointment_id):
    """Doctor approves or rejects a patient's cancellation request.

    - Approve: 35% refund to patient, full platform commission retained by site,
      doctor loses their payout for this appointment.
    - Reject: appointment returns to original status, no refund.
    """
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("home")

    appointment = get_object_or_404(Appointment, pk=appointment_id, doctor=doctor)

    if appointment.status != "cancellation_pending":
        messages.error(request, "This appointment does not have a pending cancellation.")
        return redirect("doctors:appointment_detail", appointment_id=appointment.pk)

    if request.method == "POST":
        action = request.POST.get("action")
        reason = request.POST.get("reason", "").strip()

        if action == "approve":
            appointment.status = "cancelled"
            appointment.cancellation_approved = True
            
            if appointment.payment_status in ("paid", "refunded"):
                from accounts.models import SiteSettings
                settings_obj = SiteSettings.get_solo()
                rate = Decimal(str(settings_obj.platform_commission_rate or "3.00")) / Decimal("100")
                site_charge = (appointment.fee_bdt * rate).quantize(Decimal("0.01"))
                remaining_money = max(Decimal("0.00"), appointment.fee_bdt - site_charge)
                appointment.refund_status = "partial"
                appointment.refund_amount = (remaining_money * Decimal("0.35")).quantize(Decimal("0.01"))
                appointment.payment_status = "refunded"
                appointment.save()

                patient = appointment.patient
                patient.balance = (patient.balance or Decimal("0")) + appointment.refund_amount
                patient.save(update_fields=["balance"])

                AppNotification.objects.create(
                    user=patient.user,
                    title="Refund Credited to Wallet",
                    message=f"A refund of {appointment.refund_amount} BDT has been credited to your CareBridge wallet balance for the appointment on {appointment.appointment_date}.",
                    notification_type="booking",
                    link_url=reverse("patient:appointments"),
                )
            else:
                appointment.refund_status = "none"
                appointment.refund_amount = Decimal("0.00")
                appointment.save()

            AppNotification.objects.create(
                user=appointment.patient.user,
                title="Cancellation Approved",
                message=f"Your cancellation for {appointment.appointment_date} was approved. Refund: {appointment.refund_amount} BDT (35%) has been processed.",
                notification_type="booking",
                link_url=reverse("patient:appointments"),
            )
            AppNotification.objects.create(
                user=request.user,
                title="Cancellation Approved — Refund Issued",
                message=f"You approved cancellation for {appointment.patient.user.get_full_name()} on {appointment.appointment_date}. Patient refunded {appointment.refund_amount} BDT (35%). Your payout adjusted.",
                notification_type="booking",
                link_url=reverse("doctors:appointment_list"),
            )
            messages.success(request, f"Cancellation approved. Patient refunded {appointment.refund_amount} BDT (35%).")
        elif action == "reject":
            appointment.status = "confirmed"
            appointment.cancellation_approved = False
            appointment.save(update_fields=["status", "cancellation_approved"])

            AppNotification.objects.create(
                user=appointment.patient.user,
                title="Cancellation Request Rejected",
                message=f"Your cancellation request for appointment on {appointment.appointment_date} was rejected by Dr. {doctor.user.get_full_name() or doctor.user.username}. The appointment remains scheduled.",
                notification_type="booking",
                link_url=reverse("patient:appointments"),
            )
            AppNotification.objects.create(
                user=request.user,
                title="Cancellation Request Rejected",
                message=f"You rejected the cancellation request for {appointment.patient.user.get_full_name()} on {appointment.appointment_date}. Appointment remains active.",
                notification_type="booking",
                link_url=reverse("doctors:appointment_list"),
            )
            messages.warning(request, "Cancellation request rejected. Appointment remains active.")

        return redirect("doctors:appointment_detail", appointment_id=appointment.pk)

    return render(request, "doctors/approve_cancellation.html", {"appointment": appointment})


@never_cache_auth
@login_required
def mark_attendance(request, appointment_id):
    """Mark an appointment as 'visited' (completed) or 'missed' by the doctor.
    If a prescription already exists for this appointment, the status cannot
    be changed — the prescription controls the appointment outcome."""
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("home")

    appointment = get_object_or_404(Appointment, pk=appointment_id, doctor=doctor)

    if request.method == "POST":
        # Once a prescription is created for this appointment, the status is locked.
        if appointment.prescriptions.exists():
            messages.error(request, "This appointment was completed via a prescription and its status can no longer be changed.")
            return redirect("doctors:appointment_list")

        action = request.POST.get("action")
        if action == "visited":
            appointment.status = "completed"
            appointment.save(update_fields=["status"])
            messages.success(request, f"Marked {appointment.patient.user.get_full_name()} as visited.")
        elif action == "missed":
            appointment.status = "missed"
            appointment.save(update_fields=["status"])

            AppNotification.objects.create(
                user=appointment.patient.user,
                title="Appointment Missed",
                message=f"You missed your appointment on {appointment.appointment_date.strftime('%d %b %Y')} with Dr. {request.user.get_full_name()}. Please reschedule if needed.",
                notification_type="booking",
                link_url=reverse("patient:doctor_list"),
            )
            messages.warning(request, f"Marked {appointment.patient.user.get_full_name()} as missed. Notification sent.")

    return redirect("doctors:appointment_list")


@never_cache_auth
@login_required
def auto_detect_missed(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("home")

    today = timezone.localdate()
    cutoff = today

    missed_appointments = Appointment.objects.filter(
        doctor=doctor,
        appointment_date__lt=cutoff,
        status__in=["confirmed", "pending"],
    ).select_related("patient__user")

    count = 0
    for apt in missed_appointments:
        has_prescription = Prescription.objects.filter(
            doctor=doctor,
            patient=apt.patient,
            issued_at__date__gte=apt.appointment_date,
        ).exists()

        if not has_prescription:
            apt.status = "missed"
            apt.save(update_fields=["status"])

            AppNotification.objects.create(
                user=apt.patient.user,
                title="Appointment Marked as Missed",
                message=f"Your appointment on {apt.appointment_date.strftime('%d %b %Y')} with Dr. {request.user.get_full_name()} was marked as missed (no prescription generated). Please book again if needed.",
                notification_type="booking",
                link_url=reverse("patient:doctor_list"),
            )
            count += 1

    messages.success(request, f"Auto-detected and marked {count} appointment(s) as missed.")
    return redirect("doctors:appointment_list")


@never_cache_auth
@login_required
def appointment_report(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("home")

    today = timezone.localdate()
    appointments = Appointment.objects.filter(doctor=doctor).select_related("patient__user")

    total = appointments.count()
    visited = appointments.filter(status="completed").count()
    missed = appointments.filter(status="missed").count()
    cancelled = appointments.filter(status="cancelled").count()
    pending = appointments.filter(status="pending").count()
    confirmed = appointments.filter(status="confirmed").count()

    visit_rate = (visited / total * 100) if total > 0 else 0
    missed_rate = (missed / total * 100) if total > 0 else 0
    cancelled_rate = (cancelled / total * 100) if total > 0 else 0

    report_data = {
        "total": total,
        "visited": visited,
        "missed": missed,
        "cancelled": cancelled,
        "pending": pending,
        "confirmed": confirmed,
        "visit_rate": round(visit_rate, 1),
        "missed_rate": round(missed_rate, 1),
        "cancelled_rate": round(cancelled_rate, 1),
        "appointments": appointments.order_by("-appointment_date", "-start_time")[:100],
    }

    return render(request, "doctors/appointment_report.html", report_data)


@never_cache_auth
@login_required
@never_cache_auth
@login_required
def appointment_report_export(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("home")

    appointments = Appointment.objects.filter(doctor=doctor).select_related("patient__user").order_by("-appointment_date", "-start_time")

    import io
    from decimal import Decimal
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.pdfbase import pdfmetrics, ttfonts

    pdf_font_name = "Helvetica"
    for font_path in [
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\solaimanlipi.ttf",
        r"C:\Windows\Fonts\kalpurush.ttf",
    ]:
        if os.path.exists(font_path):
            try:
                font_obj = ttfonts.TTFont("pdf_unicode_font", font_path)
                pdfmetrics.registerFont(font_obj)
                pdfmetrics.registerFontFamily(
                    "pdf_unicode_font",
                    normal="pdf_unicode_font",
                    bold="pdf_unicode_font",
                    italic="pdf_unicode_font",
                    boldItalic="pdf_unicode_font",
                )
                pdf_font_name = "pdf_unicode_font"
                break
            except Exception:
                continue

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm, leftMargin=15 * mm, rightMargin=15 * mm)
    styles = getSampleStyleSheet()

    teal = colors.HexColor("#0f766e")
    dark = colors.HexColor("#1c1917")
    slate = colors.HexColor("#57534e")
    light_bg = colors.HexColor("#f0fdfa")

    title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=18, textColor=teal, spaceAfter=2, leading=22, fontName=pdf_font_name)
    subtitle_style = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=9, textColor=slate, spaceAfter=10, leading=12, fontName=pdf_font_name)
    header_style = ParagraphStyle("header", parent=styles["Normal"], fontSize=8, textColor=colors.white, fontName=pdf_font_name)
    cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, textColor=dark, leading=11, fontName=pdf_font_name)

    elements = []
    elements.append(Paragraph("Doctor Appointment Activity Report", title_style))
    elements.append(Paragraph(f"Doctor: <b>Dr. {request.user.get_full_name()}</b> (#DOC-{doctor.id}) | Date: <b>{timezone.localdate().strftime('%d %b %Y')}</b>", subtitle_style))

    table_data = [
        [
            Paragraph("<b>Date</b>", header_style),
            Paragraph("<b>Patient Name</b>", header_style),
            Paragraph("<b>Phone</b>", header_style),
            Paragraph("<b>Status</b>", header_style),
            Paragraph("<b>Type</b>", header_style),
            Paragraph("<b>Fee</b>", header_style),
        ]
    ]

    for apt in appointments:
        patient_name = apt.patient.user.get_full_name() or apt.patient.user.username
        phone = apt.patient.phone_number or "N/A"
        fee = Decimal(str(apt.fee_bdt or 0))

        table_data.append([
            Paragraph(apt.appointment_date.strftime("%d %b %Y"), cell_style),
            Paragraph(patient_name, cell_style),
            Paragraph(phone, cell_style),
            Paragraph(apt.get_status_display(), cell_style),
            Paragraph(apt.get_consultation_type_display(), cell_style),
            Paragraph(f"BDT {fee:,.2f}", cell_style),
        ])

    col_widths = [25 * mm, 55 * mm, 30 * mm, 25 * mm, 25 * mm, 20 * mm]
    t = Table(table_data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), teal),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor("#e7e5e4")),
    ]))
    elements.append(t)

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'inline; filename="doctor_appointment_report.pdf"'
    return response
    return response


@never_cache_auth
@login_required
def reports(request):
    from datetime import datetime
    from carebridge.reports_utils import (
        compute_appointment_report,
        export_report_xlsx,
        export_report_pdf,
    )

    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Only doctors can view reports.")
        return redirect("home")

    export_format = request.GET.get("export")
    status_filter = request.GET.get("status", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()
    cols_param = request.GET.get("cols", "").strip()
    selected_columns = [c.strip() for c in cols_param.split(",") if c.strip()] if cols_param else None

    base_qs = Appointment.objects.filter(doctor=doctor).select_related("patient__user", "doctor__user")
    if start_date:
        try:
            base_qs = base_qs.filter(appointment_date__gte=datetime.strptime(start_date, "%Y-%m-%d").date())
        except ValueError:
            pass
    if end_date:
        try:
            base_qs = base_qs.filter(appointment_date__lte=datetime.strptime(end_date, "%Y-%m-%d").date())
        except ValueError:
            pass
    if status_filter:
        base_qs = base_qs.filter(status=status_filter)

    if export_format == "pdf":
        metrics = compute_appointment_report(base_qs)
        metrics["generated_on"] = timezone.localtime(timezone.now()).strftime("%d %b %Y, %I:%M %p")
        return export_report_pdf(
            base_qs,
            metrics,
            f"CareBridge Doctor Report — Dr. {request.user.get_full_name()}",
            "doctor_report.pdf",
            columns=selected_columns,
            doctor=doctor,
            start_date=start_date,
            end_date=end_date,
            owner_type="doctor",
        )

    metrics = compute_appointment_report(base_qs)
    return render(request, "doctors/reports.html", {
        "metrics": metrics,
        "status_filter": status_filter,
        "start_date": start_date,
        "end_date": end_date,
        "status_choices": Appointment.STATUS_CHOICES,
        "doctor_name": request.user.get_full_name() or request.user.email,
    })


@never_cache_auth
@login_required
def verify_payment(request, appointment_id):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Only doctors can verify payments.")
        return redirect("home")

    appointment = get_object_or_404(Appointment, pk=appointment_id, doctor=doctor)

    if appointment.payment_status != "pending_verification":
        messages.info(request, "This appointment payment is already verified or not pending verification.")
        return redirect("doctors:appointment_list")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "approve":
            appointment.payment_status = "paid"
            appointment.payment_verified = True
            appointment.payment_verified_at = timezone.now()
            appointment.payment_verified_by = doctor
            appointment.status = "confirmed"
            appointment.paid_amount = appointment.fee_bdt
            from accounts.models import SiteSettings
            from decimal import Decimal
            commission_rate = Decimal(str(SiteSettings.get_solo().platform_commission_rate or "3.00")) / Decimal("100")
            appointment.platform_fee_bdt = (appointment.fee_bdt * commission_rate).quantize(Decimal("0.01"))
            appointment.net_doctor_payout_bdt = appointment.fee_bdt - appointment.platform_fee_bdt
            appointment.save()

            AppNotification.objects.create(
                user=appointment.patient.user,
                title="✓ Payment Verified & Booking Confirmed",
                message=f"Your payment for appointment on {appointment.appointment_date} has been verified. Booking is now confirmed.",
                notification_type="booking",
                link_url=reverse("patient:appointment_detail", kwargs={"appointment_id": appointment.pk}),
            )
            messages.success(request, "Payment verified. Appointment confirmed.")
        elif action == "reject":
            appointment.payment_status = "pending"
            appointment.payment_verified = False
            appointment.save()

            AppNotification.objects.create(
                user=appointment.patient.user,
                title="Payment Verification Failed",
                message=f"Your payment proof for appointment on {appointment.appointment_date} was not accepted. Please submit correct proof or contact support.",
                notification_type="booking",
                link_url=reverse("patient:appointments"),
            )
            messages.error(request, "Payment proof rejected. Patient will be notified to re-submit.")

        return redirect("doctors:appointment_list")

    return render(request, "doctors/verify_payment.html", {
        "appointment": appointment,
    })


