from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import never_cache_auth
from accounts.models import Patient
from carebridge.ai_services import GeminiAIService
from doctors.models import Appointment
from patient.models import HealthMetric, PatientHealthReport
from prescriptions.models import FollowUp, Prescription


@never_cache_auth
@login_required
def patient_list(request):
    doctor = getattr(request.user, "doctor_profile", None)
    query = request.GET.get("q", "").strip()
    verification_filter = request.GET.get("verification", "").strip()
    district_filter = request.GET.get("district", "").strip()
    prescription_filter = request.GET.get("has_prescription", "").strip()
    sort_by = request.GET.get("sort", "name").strip()

    patients_qs = Patient.objects.select_related("user").all()

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

    all_districts = Patient.objects.values_list("district", flat=True).distinct().order_by("district")

    return render(
        request,
        "doctors/patient_list.html",
        {
            "patients": patients,
            "page_obj": page_obj,
            "query": query,
            "verification_filter": verification_filter,
            "district_filter": district_filter,
            "prescription_filter": prescription_filter,
            "sort_by": sort_by,
            "districts": [(d, d) for d in all_districts if d],
        },
    )


@never_cache_auth
@login_required
def patient_detail(request, patient_id):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Only doctors can view patient details.")
        return redirect("doctors:dashboard")

    patient = get_object_or_404(Patient, pk=patient_id)
    patient_name = patient.user.get_full_name() or patient.user.email
    summary_language = request.GET.get("lang") or "en"

    prescriptions = (
        Prescription.objects.filter(doctor=doctor, patient=patient)
        .prefetch_related("items__medicine", "follow_up")
        .order_by("-issued_at")
    )

    all_patient_rx = (
        Prescription.objects.filter(patient=patient)
        .select_related("doctor__user")
        .prefetch_related("items__medicine")
        .order_by("-issued_at")
    )

    history_parts = []
    for rx in all_patient_rx:
        doc_name = f"Dr. {rx.doctor.user.get_full_name()}" if rx.doctor and rx.doctor.user else "Doctor"
        medicines = ", ".join(item.medicine.brand_name for item in rx.items.all()) or "None"
        instructions = rx.doctor_notes or rx.advice_rules or "N/A"
        history_parts.append(
            f"Prescription #{rx.pk} on {rx.issued_at.strftime('%Y-%m-%d')} ({doc_name}): Medicines: {medicines}. Instructions: {instructions}"
        )

    recent_reports = PatientHealthReport.objects.filter(patient=patient).order_by("-date_performed")[:5]
    for rep in recent_reports:
        history_parts.append(
            f"Report '{rep.title}' ({rep.get_report_type_display()}) on {rep.date_performed}: {rep.result_description or 'No notes'}"
        )

    history_text = "\n".join(history_parts) if history_parts else "No previous prescription or report history available."

    latest = HealthMetric.objects.filter(patient=patient).order_by("-logged_at").first()
    metrics_parts = []
    if latest:
        if latest.blood_pressure_sys and latest.blood_pressure_dia:
            metrics_parts.append(f"BP: {latest.blood_pressure_sys}/{latest.blood_pressure_dia} mmHg")
        if latest.blood_sugar_fasting:
            metrics_parts.append(f"Glucose: {latest.blood_sugar_fasting} mmol/L")
        if latest.pulse_rate:
            metrics_parts.append(f"Pulse: {latest.pulse_rate} bpm")
        if latest.weight_kg:
            metrics_parts.append(f"Weight: {latest.weight_kg} kg")
    metrics_summary = "; ".join(metrics_parts) if metrics_parts else "No recent vitals on file."

    cache_key = f"patient_ai_summary_{patient.pk}_{summary_language}"
    ai_summary = request.session.get(cache_key)
    if not ai_summary or request.GET.get("refresh_ai") == "1":
        try:
            ai_summary = GeminiAIService.generate_clinical_summary(
                patient_name=patient_name,
                history_text=history_text,
                metrics_summary=metrics_summary,
                language=summary_language,
            )
            if ai_summary:
                request.session[cache_key] = ai_summary
        except Exception:
            ai_summary = request.session.get(cache_key) or "Clinical summary currently unavailable."

    reports_qs = PatientHealthReport.objects.filter(patient=patient).order_by("-date_performed")
    reports = list(reports_qs[:20])

    prescriptions_paginator = Paginator(prescriptions, 10)
    rx_page = request.GET.get("rx_page")
    prescriptions_page = prescriptions_paginator.get_page(rx_page)

    patient_age = None
    if patient.date_of_birth:
        today = timezone.localdate()
        patient_age = today.year - patient.date_of_birth.year - ((today.month, today.day) < (patient.date_of_birth.month, patient.date_of_birth.day))

    today = timezone.localdate()
    now = timezone.localtime(timezone.now())
    tz = timezone.get_current_timezone()

    can_create_prescription = False
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
        if window_start <= now <= window_end and not Prescription.objects.filter(appointment=apt).exists():
            can_create_prescription = True
            break

    if not can_create_prescription:
        can_create_prescription = FollowUp.objects.filter(
            prescription__doctor=doctor,
            prescription__patient=patient,
            status="upcoming",
            scheduled_date=today,
        ).exists()

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
        "summary_language": summary_language,
        "prescriptions_page": prescriptions_page,
        "has_active_prescription": has_active_prescription,
        "can_create_prescription": can_create_prescription,
        "missed_followups": missed_followups,
        "missed_appointments": missed_appointments,
    })
