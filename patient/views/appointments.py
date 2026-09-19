from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Min, Max, Q
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.utils import timezone

from accounts.decorators import never_cache_auth
from accounts.models import AppNotification, Doctor
from doctors.models import Appointment, DoctorSchedule


@never_cache_auth
@login_required
def appointments(request):
    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        messages.error(request, "Only patient profiles can view appointment list.")
        return redirect("home")

    status_filter = request.GET.get("status", "").strip()
    filter_type = request.GET.get("filter_type", "").strip()
    filter_value = request.GET.get("filter_value", "").strip()
    filter_month = request.GET.get("filter_month", "").strip()
    filter_year = request.GET.get("filter_year", "").strip()

    base_qs = Appointment.objects.filter(patient=patient).select_related("doctor__user", "doctor").order_by("-appointment_date", "-start_time")

    from doctors.views import _auto_mark_missed_today
    _auto_mark_missed_today(patient=patient)

    if status_filter:
        if status_filter == "upcoming":
            base_qs = base_qs.filter(status__in=["pending", "confirmed"])
        elif status_filter in ["pending", "confirmed", "completed", "cancelled", "missed", "cancellation_pending"]:
            base_qs = base_qs.filter(status=status_filter)

    # Date / Month / Year Filtering
    if filter_type == "date" and filter_value:
        base_qs = base_qs.filter(appointment_date=filter_value)
    elif filter_type == "month" and filter_month:
        try:
            m_val = int(filter_month)
            base_qs = base_qs.filter(appointment_date__month=m_val)
            if filter_year:
                base_qs = base_qs.filter(appointment_date__year=int(filter_year))
        except ValueError:
            pass
    elif filter_type == "year" and filter_year:
        try:
            base_qs = base_qs.filter(appointment_date__year=int(filter_year))
        except ValueError:
            pass

    # Build years and months dropdowns based on patient appointments
    all_apts = Appointment.objects.filter(patient=patient)
    date_aggregates = all_apts.aggregate(
        min_date=Min("appointment_date"),
        max_date=Max("appointment_date"),
    )

    current_year = timezone.localdate().year
    min_year = date_aggregates["min_date"].year if date_aggregates.get("min_date") else current_year - 2
    max_year = date_aggregates["max_date"].year if date_aggregates.get("max_date") else current_year + 1
    years = list(range(min(min_year, current_year), max(max_year, current_year) + 1))

    months = [
        ("01", "January"), ("02", "February"), ("03", "March"), ("04", "April"),
        ("05", "May"), ("06", "June"), ("07", "July"), ("08", "August"),
        ("09", "September"), ("10", "October"), ("11", "November"), ("12", "December"),
    ]

    selected_month = filter_month if filter_type == "month" else ""
    selected_year = filter_year if (filter_type in ["month", "year"]) else ""

    paginator = Paginator(base_qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    today = timezone.localdate()
    now_local = timezone.localtime(timezone.now())
    tz = timezone.get_current_timezone()

    for apt in page_obj:
        apt_dt = timezone.make_aware(
            timezone.datetime.combine(apt.appointment_date, apt.start_time), tz
        )
        hours_until = (apt_dt - now_local).total_seconds() / 3600
        apt.hours_until = hours_until
        apt.can_cancel = (
            hours_until > 24
            and apt.status not in ("cancelled", "completed", "missed", "refunded", "cancellation_pending")
            and apt.payment_status == "paid"
        )

    return render(request, "patient/appointments.html", {
        "appointments": page_obj,
        "status_filter": status_filter,
        "today": today,
        "page_obj": page_obj,
        "filter_type": filter_type,
        "filter_value": filter_value,
        "filter_month": filter_month,
        "filter_year": filter_year,
        "years": sorted(years, reverse=True),
        "months": months,
        "selected_month": selected_month,
        "selected_year": selected_year,
    })


@never_cache_auth
@login_required
def appointment_detail_patient(request, appointment_id):
    patient = getattr(request.user, "patient_profile", None)
    appointment = get_object_or_404(Appointment, pk=appointment_id, patient=patient)

    now_local = timezone.localtime(timezone.now())
    tz = timezone.get_current_timezone()
    apt_datetime = timezone.make_aware(
        timezone.datetime.combine(appointment.appointment_date, appointment.start_time), tz
    )
    hours_until = (apt_datetime - now_local).total_seconds() / 3600
    appointment.hours_until = hours_until
    appointment.can_cancel = (
        hours_until > 24
        and appointment.status not in ("cancelled", "completed", "missed", "refunded", "cancellation_pending")
        and appointment.payment_status == "paid"
    )

    return render(request, "patient/appointment_detail.html", {
        "appointment": appointment,
    })


@never_cache_auth
@login_required
def request_cancellation(request, appointment_id):
    patient = getattr(request.user, "patient_profile", None)
    appointment = get_object_or_404(Appointment, pk=appointment_id, patient=patient)

    tz = timezone.get_current_timezone()
    now_local = timezone.localtime(timezone.now())
    apt_datetime = timezone.make_aware(
        timezone.datetime.combine(appointment.appointment_date, appointment.start_time), tz
    )
    hours_until = (apt_datetime - now_local).total_seconds() / 3600

    if hours_until <= 24:
        messages.error(request, "Cancellation is disabled within 24 hours or less of the appointment start time.")
        return redirect("patient:appointment_detail", appointment_id=appointment.pk)

    if appointment.payment_status != "paid":
        messages.error(request, "Cancellation is only permitted after payment has been verified.")
        return redirect("patient:appointment_detail", appointment_id=appointment.pk)

    if appointment.status in ("cancelled", "completed", "missed", "refunded"):
        messages.error(request, f"This appointment is already {appointment.get_status_display()} and cannot be cancelled.")
        return redirect("patient:appointment_detail", appointment_id=appointment.pk)

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        appointment.status = "cancelled"
        appointment.cancellation_reason = reason
        appointment.cancellation_requested_at = timezone.now()

        if appointment.payment_status == "paid":
            from accounts.models import SiteSettings
            settings_obj = SiteSettings.get_solo()
            comm_rate = Decimal(str(settings_obj.platform_commission_rate or "15.00")) / Decimal("100")
            refund_pct = Decimal(str(settings_obj.patient_refund_percentage or "35.00")) / Decimal("100")
            display_pct = settings_obj.patient_refund_percentage

            site_charge = (appointment.fee_bdt * comm_rate).quantize(Decimal("0.01"))
            remaining_money = max(Decimal("0.00"), appointment.fee_bdt - site_charge)
            refund_amount = (remaining_money * refund_pct).quantize(Decimal("0.01"))

            appointment.refund_status = "partial"
            appointment.refund_amount = refund_amount
            appointment.payment_status = "refunded"
            appointment.platform_fee_bdt = site_charge
            appointment.net_doctor_payout_bdt = Decimal("0.00")
            appointment.save()

            patient.balance = (patient.balance or Decimal("0")) + refund_amount
            patient.save(update_fields=["balance"])

            AppNotification.objects.create(
                user=patient.user,
                title="✓ Cancellation Confirmed — Refund Credited",
                message=f"Your appointment on {appointment.appointment_date} was cancelled. A refund of {refund_amount} BDT ({display_pct}%) has been credited to your CareBridge wallet. Site charge: {site_charge} BDT deducted.",
                notification_type="booking",
                link_url=reverse("patient:appointments"),
            )
            AppNotification.objects.create(
                user=appointment.doctor.user,
                title="Appointment Cancelled by Patient",
                message=f"Patient {patient.user.get_full_name() or patient.user.username} cancelled appointment on {appointment.appointment_date}. Refund: {refund_amount} BDT ({display_pct}%) processed.",
                notification_type="booking",
                link_url=reverse("doctors:appointment_list"),
            )
            messages.success(request, f"✓ Appointment cancelled. A refund of {refund_amount} BDT ({display_pct}%) has been credited to your wallet. Refund receipt is available for download.")
        else:
            appointment.save()

            AppNotification.objects.create(
                user=appointment.doctor.user,
                title="Appointment Cancelled by Patient",
                message=f"Patient {patient.user.get_full_name() or patient.user.username} cancelled their appointment for {appointment.appointment_date}.",
                notification_type="booking",
                link_url=reverse("doctors:appointment_list"),
            )
            messages.success(request, "✓ Appointment cancelled successfully.")

        return redirect("patient:appointments")

    return render(request, "patient/request_cancellation.html", {
        "appointment": appointment,
        "hours_until": hours_until,
    })


@never_cache_auth
@login_required
def submit_payment_appeal(request, appointment_id):
    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        messages.error(request, "Access restricted.")
        return redirect("home")

    appointment = get_object_or_404(Appointment, pk=appointment_id, patient=patient)

    appeal_reason = ""
    if request.method == "POST":
        appeal_reason = request.POST.get("appeal_reason", "").strip()
    elif request.method == "GET":
        appeal_reason = "Overdue payment verification - patient appeal"

    appointment.is_payment_appeal_requested = True
    appointment.payment_appeal_requested_at = timezone.now()
    appointment.payment_appeal_reason = appeal_reason
    appointment.payment_appeal_status = "pending"
    appointment.save()

    from django.contrib.auth.models import User
    admin_users = User.objects.filter(is_superuser=True)
    for admin in admin_users:
        AppNotification.objects.create(
            user=admin,
            title="🚨 Overdue Payment Verification Appeal Submitted",
            message=f"Patient {patient.user.get_full_name()} submitted a payment appeal for Appointment #{appointment.id} with Dr. {appointment.doctor.user.get_full_name()}. Overdue payment proof requires Admin resolution.",
            notification_type="booking",
            link_url=reverse("accounts:admin_unverified_dashboard"),
        )

    messages.success(request, "✓ Payment verification appeal sent to CareBridge Admin. An administrator will review your payment proof and process your refund or confirm your appointment.")
    return redirect("patient:appointment_detail", appointment_id=appointment.pk)


@never_cache_auth
@login_required
def edit_appointment(request, appointment_id):
    patient = getattr(request.user, "patient_profile", None)
    appointment = get_object_or_404(Appointment, pk=appointment_id, patient=patient)

    if appointment.edit_count >= 3:
        messages.error(request, "You have reached the maximum allowed changes (3 edits) for this appointment.")
        return redirect("patient:appointment_detail", appointment_id=appointment.pk)

    if appointment.status in ("cancelled", "completed", "missed"):
        messages.error(request, "Cannot edit a cancelled, completed, or missed appointment.")
        return redirect("patient:appointment_detail", appointment_id=appointment.pk)

    schedules = DoctorSchedule.objects.filter(doctor=appointment.doctor, is_active=True).order_by("day_of_week", "start_time")

    if request.method == "POST":
        new_date_str = request.POST.get("appointment_date")
        new_time_str = request.POST.get("start_time")
        consultation_type = request.POST.get("consultation_type", appointment.consultation_type)

        if new_date_str and new_time_str:
            try:
                new_date = timezone.datetime.strptime(new_date_str, "%Y-%m-%d").date()
                new_time = timezone.datetime.strptime(new_time_str, "%H:%M").time()

                if new_date < timezone.localdate():
                    messages.error(request, "Cannot select a past date.")
                    return redirect("patient:edit_appointment", appointment_id=appointment.pk)

                conflicting = Appointment.objects.filter(
                    doctor=appointment.doctor,
                    appointment_date=new_date,
                    start_time=new_time,
                    status__in=["pending", "confirmed"],
                ).exclude(pk=appointment.pk).exists()

                if conflicting:
                    messages.error(request, "That time slot is already booked. Please select another slot.")
                    return redirect("patient:edit_appointment", appointment_id=appointment.pk)

                appointment.appointment_date = new_date
                appointment.start_time = new_time
                appointment.end_time = (
                    timezone.datetime.combine(new_date, new_time) + timezone.timedelta(minutes=30)
                ).time()
                appointment.consultation_type = consultation_type
                appointment.edit_count += 1
                appointment.save()

                AppNotification.objects.create(
                    user=appointment.doctor.user,
                    title="Appointment Rescheduled by Patient",
                    message=f"Patient {patient.user.get_full_name()} rescheduled appointment to {new_date.strftime('%d %b %Y')} at {new_time.strftime('%I:%M %p')}. (Edit {appointment.edit_count}/3)",
                    notification_type="booking",
                    link_url=reverse("doctors:appointment_detail", kwargs={"appointment_id": appointment.pk}),
                )

                messages.success(request, f"Appointment successfully updated! ({appointment.edit_count}/3 edits used)")
                return redirect("patient:appointment_detail", appointment_id=appointment.pk)
            except ValueError:
                messages.error(request, "Invalid date or time format.")

    return render(request, "patient/edit_appointment.html", {
        "appointment": appointment,
        "schedules": schedules,
        "remaining_edits": 3 - appointment.edit_count,
    })


def _generate_slots(start_time, end_time, slot_duration, doctor, date, blocked_before_time=None, exclude_appointment_id=None):
    """Generate available appointment time slots for a given doctor on a given date."""
    from datetime import datetime, timedelta
    slots = []
    current = datetime.combine(date, start_time)
    end = datetime.combine(date, end_time)
    while current + timedelta(minutes=slot_duration) <= end:
        slot_end = current + timedelta(minutes=slot_duration)
        is_booked = Appointment.objects.filter(
            doctor=doctor,
            appointment_date=date,
            status__in=["pending", "confirmed"],
            start_time=current.time(),
        )
        if exclude_appointment_id:
            is_booked = is_booked.exclude(pk=exclude_appointment_id)

        is_booked_flag = is_booked.exists()
        is_past_flag = False

        if blocked_before_time and current.time() < blocked_before_time:
            is_past_flag = True

        available = (not is_booked_flag) and (not is_past_flag)

        slots.append({
            "date": date.strftime("%Y-%m-%d"),
            "start": current.strftime("%I:%M %p"),
            "start_raw": current.strftime("%H:%M"),
            "end": slot_end.strftime("%I:%M %p"),
            "available": available,
            "is_booked": is_booked_flag,
            "is_past": is_past_flag,
        })
        current = slot_end
    return slots


@never_cache_auth
@login_required
def book_doctor(request, doctor_id):
    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        messages.error(request, "Only patients can book appointments.")
        return redirect("patient:doctor_list")

    doctor = get_object_or_404(Doctor, pk=doctor_id)

    from prescriptions.models import FollowUp
    followup_id = request.GET.get("followup_id") or request.POST.get("followup_id")
    followup = None
    if followup_id:
        followup = FollowUp.objects.filter(pk=followup_id, prescription__patient=patient).first()

    schedules = DoctorSchedule.objects.filter(doctor=doctor, is_active=True).order_by("day_of_week", "start_time")

    if request.method == "POST":
        appointment_date = request.POST.get("appointment_date")
        start_time = request.POST.get("start_time")
        consultation_type = request.POST.get("consultation_type", "in_person")
        if consultation_type not in ["in_person", "video_online"]:
            consultation_type = "in_person"
        chief_complaint = request.POST.get("chief_complaint", "").strip()

        if not appointment_date or not start_time:
            messages.error(request, "Please select date and time.")
            return redirect("patient:book_doctor", doctor_id=doctor.pk)

        from datetime import datetime, timedelta
        try:
            apt_date = datetime.strptime(appointment_date, "%Y-%m-%d").date()
        except ValueError:
            messages.error(request, "Invalid date format.")
            return redirect("patient:book_doctor", doctor_id=doctor.pk)

        day_name = apt_date.strftime("%A").lower()
        schedule = DoctorSchedule.objects.filter(doctor=doctor, day_of_week=day_name, is_active=True).first()
        slot_duration = schedule.slot_duration_minutes if schedule else 30

        try:
            start_dt = datetime.strptime(start_time, "%H:%M").time()
        except ValueError:
            try:
                start_dt = datetime.strptime(start_time, "%I:%M %p").time()
            except ValueError:
                try:
                    start_dt = datetime.strptime(start_time, "%H:%M:%S").time()
                except ValueError:
                    messages.error(request, "Invalid time format.")
                    return redirect("patient:book_doctor", doctor_id=doctor.pk)

        end_dt = (datetime.combine(apt_date, start_dt) + timedelta(minutes=slot_duration)).time()

        if apt_date < timezone.localdate():
            messages.error(request, "Cannot book appointments in the past.")
            return redirect("patient:book_doctor", doctor_id=doctor.pk)

        existing = Appointment.objects.filter(
            doctor=doctor,
            appointment_date=apt_date,
            status__in=["pending", "confirmed"],
        ).filter(start_time__lt=end_dt, end_time__gt=start_dt)

        if existing.exists():
            messages.error(request, "This time slot has already been booked. Please select another slot.")
            return redirect("patient:book_doctor", doctor_id=doctor.pk)

        fee = doctor.consultation_fee or Decimal("500.00")
        platform_fee = Decimal("15.00")
        net_doctor = fee - platform_fee

        appointment = Appointment.objects.create(
            patient=patient,
            doctor=doctor,
            appointment_date=apt_date,
            start_time=start_dt,
            end_time=end_dt,
            consultation_type=consultation_type,
            chief_complaint=chief_complaint,
            fee_bdt=fee,
            platform_fee_bdt=platform_fee,
            net_doctor_payout_bdt=net_doctor,
            status="pending",
            payment_status="pending",
        )

        AppNotification.objects.create(
            user=doctor.user,
            title="🗓️ New Appointment Booking",
            message=f"Patient {request.user.get_full_name() or request.user.email} has booked an appointment on {apt_date} at {start_dt.strftime('%I:%M %p')}.",
            notification_type="booking",
            link_url=reverse("doctors:appointment_detail", kwargs={"appointment_id": appointment.pk}),
        )

        AppNotification.objects.create(
            user=request.user,
            title="✓ Appointment Booking Request Sent",
            message=f"Your booking request with Dr. {doctor.user.get_full_name() or doctor.user.username} on {apt_date} at {start_dt.strftime('%I:%M %p')} has been sent.",
            notification_type="booking",
            link_url=reverse("patient:notifications"),
        )

        messages.success(request, f"Appointment booked successfully for {apt_date.strftime('%d %b %Y')} at {start_dt.strftime('%I:%M %p')}. Please complete payment.")

        if followup and not followup.is_booking_confirmed:
            followup.is_booking_confirmed = True
            followup.save(update_fields=["is_booking_confirmed"])

        return redirect("accounts:payment_process", appointment_id=appointment.pk)

    import json
    from datetime import datetime, timedelta
    from collections import OrderedDict
    today = timezone.localdate()
    now = timezone.localtime()
    max_date = today + timedelta(days=60)
    current_time = now.time()

    available_slots = []
    for i in range(61):
        date = today + timedelta(days=i)
        day_name = date.strftime("%A").lower()
        day_schedules = DoctorSchedule.objects.filter(doctor=doctor, day_of_week=day_name, is_active=True)
        for sch in day_schedules:
            blocked = current_time if date == today else None
            slots = _generate_slots(sch.start_time, sch.end_time, sch.slot_duration_minutes, doctor, date, blocked_before_time=blocked)
            available_slots.extend(slots)

    grouped_slots_dict = OrderedDict()
    for slot in available_slots:
        key = slot["date"]
        grouped_slots_dict.setdefault(key, []).append(slot)

    date_options = []
    for date_str, slots in grouped_slots_dict.items():
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        avail_count = sum(1 for s in slots if s.get("available"))
        date_options.append({
            "date": date_str,
            "display": dt.strftime("%A, %d %b %Y"),
            "short_day": dt.strftime("%a"),
            "short_date": dt.strftime("%d %b"),
            "avail_count": avail_count,
            "slots": slots
        })

    grouped_slots_json = json.dumps(grouped_slots_dict)

    return render(request, "patient/book_appointment.html", {
        "doctor": doctor,
        "schedules": schedules,
        "available_slots": available_slots,
        "grouped_slots": grouped_slots_dict,
        "grouped_slots_json": grouped_slots_json,
        "date_options": date_options,
        "today": today,
        "max_date": max_date,
    })

