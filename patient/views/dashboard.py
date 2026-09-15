from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from accounts.decorators import never_cache_auth
from accounts.models import AppNotification, News
from doctors.models import Appointment, DoctorSchedule
from patient.models import HealthMetric
from prescriptions.models import FollowUp, Prescription, ReminderSchedule

from .prescriptions import _ensure_dose_schedules


@never_cache_auth
@login_required
def dashboard(request):
    patient = getattr(request.user, "patient_profile", None)
    today = timezone.localdate()
    now = timezone.localtime(timezone.now())

    _ensure_dose_schedules(patient)

    # Auto-mark today's past appointments as missed once the appointment window has passed
    try:
        from doctors.views import _auto_mark_missed_today
        _auto_mark_missed_today(patient=patient)
    except Exception:
        pass

    # Prescription timing evaluator
    for rx in Prescription.objects.filter(patient=patient):
        updated = False
        if rx.activates_at and now >= rx.activates_at and rx.status == "scheduled":
            rx.status = "active"
            updated = True
        if rx.expires_at and now >= rx.expires_at and not rx.is_locked:
            rx.is_locked = True
            updated = True
        if updated:
            rx.save(update_fields=["status", "is_locked"])

    # Follow-up auto-completion evaluator
    all_followups = FollowUp.objects.filter(prescription__patient=patient)
    for fu in all_followups:
        doc = fu.prescription.doctor
        has_rx = Prescription.objects.filter(
            doctor=doc,
            patient=patient,
            issued_at__date__gte=fu.scheduled_date
        ).exists()

        if has_rx and fu.status != "completed":
            fu.status = "completed"
            fu.save()
        elif fu.scheduled_date < today and fu.status == "upcoming":
            fu.status = "missed"
            fu.save()

    active_rx = (
        Prescription.objects.filter(patient=patient, is_locked=False, status__in=["scheduled", "active"])
        .select_related("doctor__user")
        .prefetch_related("items__medicine", "items__reminder_schedules")
        .first()
    )

    next_follow_up = (
        FollowUp.objects.filter(prescription__patient=patient, status="upcoming")
        .select_related("prescription__doctor__user")
        .order_by("scheduled_date")
        .first()
    )

    followups_needing_booking = FollowUp.objects.filter(
        prescription__patient=patient,
        status="upcoming",
        is_booking_confirmed=False,
    ).select_related("prescription__doctor__user").order_by("scheduled_date")[:5]

    overdue_followups = FollowUp.objects.filter(
        prescription__patient=patient,
        status__in=["upcoming", "missed"],
        is_booking_confirmed=False,
        scheduled_date__lt=today,
    ).select_related("prescription__doctor__user").order_by("scheduled_date")[:5]

    # Today's appointments for the "Today's Appointments" dashboard section
    current_appointments = Appointment.objects.filter(
        patient=patient,
        appointment_date=today,
        status__in=["pending", "confirmed", "completed", "cancellation_pending", "missed"],
    ).select_related("doctor__user").order_by("start_time")

    has_any_booking = Appointment.objects.filter(patient=patient).exists()

    # Upcoming future appointments
    upcoming_appointments = Appointment.objects.filter(
        patient=patient,
        appointment_date__gt=today,
        status__in=["pending", "confirmed"],
    ).select_related("doctor__user").order_by("appointment_date", "start_time")[:5]

    all_upcoming_appointments = Appointment.objects.filter(
        patient=patient,
        appointment_date__gte=today,
        status__in=["pending", "confirmed"],
    ).select_related("doctor__user").order_by("appointment_date", "start_time")

    upcoming_appointment = all_upcoming_appointments.first()
    upcoming_appointments_count = all_upcoming_appointments.count()

    # Doses for today
    doses_today = ReminderSchedule.objects.filter(
        prescription_item__prescription__patient=patient,
        scheduled_date=today,
    ).select_related("prescription_item__medicine").order_by("reminder_time")

    schedules_today = (
        active_rx.items.all()
        if active_rx
        else []
    )

    recent_prescriptions = (
        Prescription.objects.filter(patient=patient)
        .select_related("doctor__user")
        .order_by("-issued_at")[:5]
    )

    vitals = HealthMetric.objects.filter(patient=patient).order_by("-logged_at").first()

    # Calendar data - 90 days past to 365 days future
    calendar_start = today - timezone.timedelta(days=90)
    calendar_end = today + timezone.timedelta(days=365)

    calendar_appointments = Appointment.objects.filter(
        patient=patient,
        appointment_date__gte=calendar_start,
        appointment_date__lte=calendar_end,
        status__in=["pending", "confirmed"],
    ).select_related("doctor__user").order_by("appointment_date", "start_time")

    calendar_followups = FollowUp.objects.filter(
        prescription__patient=patient,
        scheduled_date__gte=calendar_start,
        scheduled_date__lte=calendar_end,
        status__in=["upcoming", "missed"],
    ).select_related("prescription__doctor__user").order_by("scheduled_date")

    calendar_doses = ReminderSchedule.objects.filter(
        prescription_item__prescription__patient=patient,
        scheduled_date__gte=calendar_start,
        scheduled_date__lte=calendar_end,
        status="pending",
    ).select_related("prescription_item__medicine").order_by("scheduled_date", "reminder_time")[:100]

    refund_notifications = AppNotification.objects.filter(
        user=request.user,
        notification_type="booking",
    ).filter(
        Q(title__icontains="refund") | Q(title__icontains="cancel") | Q(title__icontains="Cancellation")
    ).order_by("-created_at")[:5]

    upcoming_followups_list = (
        FollowUp.objects.filter(prescription__patient=patient, status="upcoming")
        .select_related("prescription__doctor__user")
        .order_by("scheduled_date")[:5]
    )

    latest_rx_for_summary = (
        Prescription.objects.filter(patient=patient)
        .select_related("doctor__user")
        .prefetch_related("items__medicine")
        .first()
    )

    recent_notifications = AppNotification.objects.filter(user=request.user).order_by("-created_at")[:5]
    news_list = News.objects.filter(is_active=True, target_audience__in=["all", "patients"]).order_by("-created_at")[:5]

    return render(
        request,
        "patient/dashboard.html",
        {
            "patient": patient,
            "active_rx": active_rx,
            "next_follow_up": next_follow_up,
            "followups_needing_booking": followups_needing_booking,
            "overdue_followups": overdue_followups,
            "current_appointments": current_appointments,
            "has_any_booking": has_any_booking,
            "upcoming_appointments": upcoming_appointments,
            "upcoming_appointment": upcoming_appointment,
            "upcoming_appointments_count": upcoming_appointments_count,
            "all_upcoming_appointments": all_upcoming_appointments[:10],
            "doses_today": doses_today,
            "schedules_today": schedules_today,
            "recent_prescriptions": recent_prescriptions,
            "vitals": vitals,
            "calendar_appointments": calendar_appointments,
            "calendar_followups": calendar_followups,
            "calendar_doses": calendar_doses,
            "refund_notifications": refund_notifications,
            "upcoming_followups_list": upcoming_followups_list,
            "latest_rx_for_summary": latest_rx_for_summary,
            "recent_notifications": recent_notifications,
            "news_list": news_list,
        },
    )


@never_cache_auth
@login_required
def notifications(request):
    notifications_qs = AppNotification.objects.filter(user=request.user).order_by("-created_at")
    notifications_qs.filter(is_read=False).update(is_read=True)

    filter_type = request.GET.get("type", "all").strip()
    if filter_type != "all":
        notifications_qs = notifications_qs.filter(notification_type=filter_type)

    from django.core.paginator import Paginator
    paginator = Paginator(notifications_qs, 15)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "patient/notifications.html", {
        "items": page_obj,
        "notifications": page_obj,
        "filter_type": filter_type,
        "page_obj": page_obj,
    })
