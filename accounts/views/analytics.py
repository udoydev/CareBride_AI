from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect, render

from accounts.models import AppNotification, Doctor, Patient
from doctors.models import Appointment, DoctorSchedule
from prescriptions.models import FollowUp, Prescription


@login_required
def doctor_analytics_view(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("home")

    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()
    status_filter = request.GET.get("status", "").strip()
    search_query = request.GET.get("q", "").strip()
    date_preset = request.GET.get("preset", "").strip()

    today = date.today()

    if date_preset == "today":
        start_date = today.strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")
    elif date_preset == "week":
        start_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")
    elif date_preset == "month":
        start_date = today.replace(day=1).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")
    elif date_preset == "year":
        start_date = today.replace(month=1, day=1).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")

    base_qs = Appointment.objects.filter(doctor=doctor).select_related("patient__user", "doctor__user")

    if start_date:
        try:
            d_start = datetime.strptime(start_date, "%Y-%m-%d").date()
            base_qs = base_qs.filter(appointment_date__gte=d_start)
        except ValueError:
            pass

    if end_date:
        try:
            d_end = datetime.strptime(end_date, "%Y-%m-%d").date()
            base_qs = base_qs.filter(appointment_date__lte=d_end)
        except ValueError:
            pass

    if status_filter:
        if status_filter == "paid":
            base_qs = base_qs.filter(payment_status="paid")
        elif status_filter == "refunded":
            base_qs = base_qs.filter(Q(status="cancelled") | Q(payment_status="refunded"))
        else:
            base_qs = base_qs.filter(status=status_filter)

    if search_query:
        base_qs = base_qs.filter(
            Q(patient__user__first_name__icontains=search_query) |
            Q(patient__user__last_name__icontains=search_query) |
            Q(patient__user__email__icontains=search_query) |
            Q(patient__phone_number__icontains=search_query)
        )

    all_appointments = base_qs.order_by("-appointment_date", "-start_time")
    completed = all_appointments.filter(status="completed")
    cancelled = all_appointments.filter(status="cancelled")
    paid = all_appointments.filter(payment_status="paid")

    total_patients = all_appointments.values("patient").distinct().count()
    total_appointments = all_appointments.count()
    completed_count = completed.count()

    total_earnings = paid.aggregate(total=Sum("fee_bdt"))["total"] or 0
    total_refunds = cancelled.aggregate(total=Sum("refund_amount"))["total"] or 0
    platform_fees = paid.aggregate(total=Sum("platform_fee_bdt"))["total"] or 0
    net_earnings = total_earnings - platform_fees - total_refunds

    recent_appointments = all_appointments[:50]

    return render(request, "accounts/doctor_analytics.html", {
        "total_patients": total_patients,
        "total_appointments": total_appointments,
        "completed_count": completed_count,
        "total_earnings": total_earnings,
        "total_refunds": total_refunds,
        "platform_fees": platform_fees,
        "net_earnings": net_earnings,
        "recent_appointments": recent_appointments,
        "start_date": start_date,
        "end_date": end_date,
        "status_filter": status_filter,
        "search_query": search_query,
        "date_preset": date_preset,
    })


@login_required
def admin_analytics_view(request):
    if not request.user.is_superuser:
        messages.error(request, "Access restricted to admin.")
        return redirect("home")

    today = date.today()
    month_start = today.replace(day=1)
    week_start = today - timedelta(days=today.weekday())

    total_doctors = Doctor.objects.count()
    total_patients = Patient.objects.count()
    total_appointments = Appointment.objects.count()
    confirmed_appointments = Appointment.objects.filter(status="confirmed").count()
    completed_appointments = Appointment.objects.filter(status="completed").count()
    cancelled_appointments = Appointment.objects.filter(status="cancelled").count()
    pending_appointments = Appointment.objects.filter(status="pending").count()
    missed_appointments = Appointment.objects.filter(status="missed").count()
    cancellation_pending = Appointment.objects.filter(status="cancellation_pending").count()

    verified_doctors = Doctor.objects.filter(is_verified=True).count()
    verified_patients = Patient.objects.filter(is_verified=True).count()
    pending_doctor_verifications = Doctor.objects.filter(verification_status="pending").count()
    pending_patient_verifications = Patient.objects.filter(verification_status="pending").count()

    total_schedules = DoctorSchedule.objects.filter(is_active=True).count()

    total_prescriptions = Prescription.objects.count()
    total_followups = FollowUp.objects.count()
    upcoming_followups = FollowUp.objects.filter(status="upcoming").count()
    completed_followups = FollowUp.objects.filter(status="completed").count()

    total_notifications = AppNotification.objects.count()
    unread_notifications = AppNotification.objects.filter(is_read=False).count()

    total_revenue = Appointment.objects.filter(payment_status="paid").aggregate(Sum("fee_bdt"))["fee_bdt__sum"] or 0
    site_income = Appointment.objects.filter(payment_status="paid").aggregate(Sum("platform_fee_bdt"))["platform_fee_bdt__sum"] or 0
    month_revenue = Appointment.objects.filter(payment_status="paid").aggregate(Sum("fee_bdt"))["fee_bdt__sum"] or 0
    month_site_income = Appointment.objects.filter(payment_status="paid", appointment_date__gte=month_start).aggregate(Sum("platform_fee_bdt"))["platform_fee_bdt__sum"] or 0
    week_revenue = Appointment.objects.filter(payment_status="paid").aggregate(Sum("fee_bdt"))["fee_bdt__sum"] or 0
    week_site_income = Appointment.objects.filter(payment_status="paid", appointment_date__gte=week_start).aggregate(Sum("platform_fee_bdt"))["platform_fee_bdt__sum"] or 0
    doctor_payout = Appointment.objects.filter(payment_status="paid").aggregate(Sum("net_doctor_payout_bdt"))["net_doctor_payout_bdt__sum"] or 0
    total_refunds = Appointment.objects.filter(refund_amount__gt=0).aggregate(Sum("refund_amount"))["refund_amount__sum"] or 0
    partial_refunds = Appointment.objects.filter(refund_status="partial").count()
    full_refunds = Appointment.objects.filter(refund_status="full").count()
    platform_fees = Appointment.objects.filter(payment_status="paid").aggregate(Sum("platform_fee_bdt"))["platform_fee_bdt__sum"] or 0
    net_profit = platform_fees - total_refunds

    in_person_appointments = Appointment.objects.filter(consultation_type="in_person").count()
    video_appointments = Appointment.objects.filter(consultation_type="video_online").count()

    avg_appointments_per_doctor = round(total_appointments / total_doctors, 1) if total_doctors > 0 else 0
    avg_appointments_per_patient = round(total_appointments / total_patients, 1) if total_patients > 0 else 0

    recent_appointments_qs = Appointment.objects.all().order_by("-created_at")[:50]
    paginator = Paginator(recent_appointments_qs, 10)
    page_number = request.GET.get("page")
    recent_appointments = paginator.get_page(page_number)

    daily_stats = []
    for i in range(7):
        day = today - timedelta(days=i)
        count = Appointment.objects.filter(appointment_date=day).count()
        daily_stats.append({"date": day.strftime("%Y-%m-%d"), "count": count})

    return render(request, "accounts/admin_analytics.html", {
        "total_doctors": total_doctors,
        "total_patients": total_patients,
        "total_appointments": total_appointments,
        "confirmed_appointments": confirmed_appointments,
        "completed_appointments": completed_appointments,
        "cancelled_appointments": cancelled_appointments,
        "pending_appointments": pending_appointments,
        "missed_appointments": missed_appointments,
        "cancellation_pending": cancellation_pending,
        "verified_doctors": verified_doctors,
        "verified_patients": verified_patients,
        "pending_doctor_verifications": pending_doctor_verifications,
        "pending_patient_verifications": pending_patient_verifications,
        "total_schedules": total_schedules,
        "total_prescriptions": total_prescriptions,
        "total_followups": total_followups,
        "upcoming_followups": upcoming_followups,
        "completed_followups": completed_followups,
        "total_notifications": total_notifications,
        "unread_notifications": unread_notifications,
        "total_revenue": total_revenue,
        "month_revenue": month_revenue,
        "week_revenue": week_revenue,
        "site_income": site_income,
        "month_site_income": month_site_income,
        "week_site_income": week_site_income,
        "doctor_payout": doctor_payout,
        "total_refunds": total_refunds,
        "partial_refunds": partial_refunds,
        "full_refunds": full_refunds,
        "platform_fees": platform_fees,
        "net_profit": net_profit,
        "in_person_appointments": in_person_appointments,
        "video_appointments": video_appointments,
        "avg_appointments_per_doctor": avg_appointments_per_doctor,
        "avg_appointments_per_patient": avg_appointments_per_patient,
        "recent_appointments": recent_appointments,
        "daily_stats": daily_stats,
    })
