from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect, render, reverse
from django.utils import timezone

from accounts.decorators import never_cache_auth
from accounts.models import AppNotification, News
from doctors.models import Appointment
from prescriptions.models import FollowUp, Prescription

from .appointments import _auto_detect_missed_for_doctor, _auto_mark_missed_today


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

    patient_rows.sort(key=lambda x: (x.get("has_prescription", False), x["patient"]["id"]), reverse=True)

    total_patients = len(seen_patient_ids)
    today_appointments = Appointment.objects.filter(doctor=doctor, appointment_date=today).count()
    pending_appointments = Appointment.objects.filter(doctor=doctor, status="pending").count()
    upcoming_followups = FollowUp.objects.filter(prescription__doctor=doctor, status="upcoming").count()

    today_appointments_qs = Appointment.objects.filter(
        doctor=doctor,
        appointment_date=today,
        status__in=["pending", "confirmed"],
    ).select_related("patient__user").order_by("start_time")

    urgent_actions = []

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

    calendar_start = today - timezone.timedelta(days=60)
    calendar_end = today + timezone.timedelta(days=90)

    doctor_calendar_appointments = Appointment.objects.filter(
        doctor=doctor,
        appointment_date__gte=calendar_start,
        appointment_date__lte=calendar_end,
    ).exclude(status="cancelled").select_related("patient__user").order_by("appointment_date", "start_time")

    doctor_calendar_followups = FollowUp.objects.filter(
        prescription__doctor=doctor,
        scheduled_date__gte=calendar_start,
        scheduled_date__lte=calendar_end,
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
def notifications(request):
    notifications_qs = AppNotification.objects.filter(user=request.user).order_by("-created_at")
    unread_qs = notifications_qs.filter(is_read=False)
    unread_qs.update(is_read=True)

    filter_type = request.GET.get("type", "all").strip()
    if filter_type != "all":
        notifications_qs = notifications_qs.filter(notification_type=filter_type)

    from django.core.paginator import Paginator
    paginator = Paginator(notifications_qs, 15)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "doctors/notifications.html", {
        "items": page_obj,
        "notifications": page_obj,
        "filter_type": filter_type,
        "page_obj": page_obj,
    })
