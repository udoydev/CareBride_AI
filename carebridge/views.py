from django.conf import settings
from django.shortcuts import redirect, render
from django.utils import translation, timezone
from django.views.static import serve as static_serve
from decimal import Decimal
from datetime import datetime, timedelta
from django.contrib import messages

from accounts.models import Patient, Doctor, AppNotification, AIProvider, SiteSettings, News
from doctors.models import Appointment
from prescriptions.models import Prescription, FollowUp, ReminderSchedule
from patient.models import PatientVisit, PatientHealthReport
from carebridge.reports_utils import compute_appointment_report, export_report_pdf, export_report_xlsx
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404
from django.db.models import Sum


def home(request):
    if request.user.is_authenticated:
        if request.user.is_superuser or request.user.is_staff:
            return redirect("admin:index")
        if hasattr(request.user, "doctor_profile") and request.user.doctor_profile:
            if not request.user.doctor_profile.is_verified:
                return redirect("accounts:verification_pending")
            return redirect("doctors:dashboard")
        if hasattr(request.user, "patient_profile") and request.user.patient_profile:
            if not request.user.patient_profile.is_verified:
                return redirect("accounts:verification_pending")
            return redirect("patient:dashboard")
    return render(request, "home.html")


def custom_404(request, exception=None):
  return render(request, '404.html', status=404)


def set_site_language(request, lang):
    next_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or "/home/"
    target_lang = "bn" if lang == "bn" else "en"

    request.session["site_lang"] = target_lang
    request.session[getattr(translation, "LANGUAGE_SESSION_KEY", "_language")] = target_lang
    translation.activate(target_lang)

    if request.user.is_authenticated:
        if hasattr(request.user, "patient_profile") and request.user.patient_profile:
            patient = request.user.patient_profile
            patient.preferred_language = target_lang
            patient.save(update_fields=["preferred_language"])
        elif hasattr(request.user, "doctor_profile") and request.user.doctor_profile:
            doctor = request.user.doctor_profile
            if hasattr(doctor, "preferred_language"):
                doctor.preferred_language = target_lang
                doctor.save(update_fields=["preferred_language"])

    response = redirect(next_url)
    response.set_cookie(
        getattr(settings, "LANGUAGE_COOKIE_NAME", "django_language"),
        target_lang,
        max_age=365 * 24 * 60 * 60,
    )
    return response


def media_serve(request, path, document_root=None):
    """Serve media files with cache-busting headers to prevent stale avatar caching."""
    response = static_serve(request, path, document_root=document_root)
    response["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Sum
from decimal import Decimal

from accounts.models import Doctor, Patient
from doctors.models import Appointment
from carebridge.reports_utils import compute_appointment_report, export_report_xlsx, export_report_pdf


@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_reports(request):
    """Admin reports view with filtering and PDF export capabilities."""
    from datetime import datetime

    export_format = request.GET.get("export")
    status_filter = request.GET.get("status", "").strip()
    income_type_filter = request.GET.get("income_type", "").strip()
    doctor_filter = request.GET.get("doctor", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()

    base_qs = Appointment.objects.all().select_related("patient__user", "doctor__user")
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
    if doctor_filter:
        try:
            base_qs = base_qs.filter(doctor_id=int(doctor_filter))
        except ValueError:
            pass
    if income_type_filter == "paid":
        base_qs = base_qs.filter(payment_status="paid")
    elif income_type_filter == "pending_payment":
        base_qs = base_qs.filter(payment_status="pending")
    elif income_type_filter == "cancelled":
        base_qs = base_qs.filter(status="cancelled")
    elif income_type_filter == "completed":
        base_qs = base_qs.filter(status="completed")

    total_patients = Patient.objects.count()
    total_doctors = Doctor.objects.count()
    total_cancellations = Appointment.objects.filter(status="cancelled").count()
    total_refunds = Appointment.objects.filter(status="cancelled").aggregate(total=Sum("refund_amount"))["total"] or Decimal("0")

    if export_format == "pdf":
        metrics = compute_appointment_report(base_qs)
        return export_report_pdf(base_qs, metrics, "CareBridge Site-wide Admin Report", "admin_report.pdf")

    metrics = compute_appointment_report(base_qs)
    return render(request, "admin/reports.html", {
        "metrics": metrics,
        "total_patients": total_patients,
        "total_doctors": total_doctors,
        "total_cancellations": total_cancellations,
        "total_refunds": total_refunds,
        "status_filter": status_filter,
        "income_type_filter": income_type_filter,
        "doctor_filter": doctor_filter,
        "start_date": start_date,
        "end_date": end_date,
        "status_choices": Appointment.STATUS_CHOICES,
        "income_type_choices": [
            ("all", "All Appointments"),
            ("paid", "Paid Only"),
            ("pending_payment", "Pending Payment"),
            ("cancelled", "Cancelled"),
            ("completed", "Completed"),
        ],
        "doctor_choices": Doctor.objects.all().order_by("user__first_name", "user__last_name"),
    })


@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_doctor_report(request, doctor_id):
    """Individual doctor performance report with time range filtering."""
    doctor = get_object_or_404(Doctor, pk=doctor_id)
    doctor_name = doctor.user.get_full_name() or doctor.user.username

    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()

    qs = Appointment.objects.filter(doctor=doctor).select_related("patient__user", "doctor__user")
    if start_date:
        try:
            qs = qs.filter(appointment_date__gte=datetime.strptime(start_date, "%Y-%m-%d").date())
        except ValueError:
            pass
    if end_date:
        try:
            qs = qs.filter(appointment_date__lte=datetime.strptime(end_date, "%Y-%m-%d").date())
        except ValueError:
            pass

    total_appointments = qs.count()
    unique_patients = qs.values("patient").distinct().count()
    completed = qs.filter(status="completed").count()
    missed = qs.filter(status="missed").count()
    cancelled = qs.filter(status="cancelled").count()
    pending = qs.filter(status="pending").count()
    confirmed = qs.filter(status="confirmed").count()

    paid_qs = qs.filter(payment_status="paid")
    total_fees = paid_qs.aggregate(total=Sum("fee_bdt"))["total"] or Decimal("0")
    platform_income = paid_qs.aggregate(total=Sum("platform_fee_bdt"))["total"] or Decimal("0")
    doctor_payout = paid_qs.aggregate(total=Sum("net_doctor_payout_bdt"))["total"] or Decimal("0")
    refunds = qs.filter(status="cancelled").aggregate(total=Sum("refund_amount"))["total"] or Decimal("0")

    prescription_count = Prescription.objects.filter(doctor=doctor).count()
    followup_count = FollowUp.objects.filter(prescription__doctor=doctor).count()

    recent_appointments = qs.order_by("-appointment_date", "-start_time")[:20]

    export_format = request.GET.get("export")
    if export_format == "pdf":
        metrics = compute_appointment_report(qs)
        return export_report_pdf(qs, metrics, f"Doctor Report - Dr. {doctor_name}", f"doctor_{doctor_id}_report.pdf", owner_type="doctor", doctor=doctor)

    context = {
        "doctor": doctor,
        "doctor_name": doctor_name,
        "start_date": start_date,
        "end_date": end_date,
        "total_appointments": total_appointments,
        "unique_patients": unique_patients,
        "completed": completed,
        "missed": missed,
        "cancelled": cancelled,
        "pending": pending,
        "confirmed": confirmed,
        "total_fees": total_fees,
        "platform_income": platform_income,
        "doctor_payout": doctor_payout,
        "refunds": refunds,
        "prescription_count": prescription_count,
        "followup_count": followup_count,
        "recent_appointments": recent_appointments,
    }
    return render(request, "admin/doctor_report.html", context)


@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_doctor_tracking(request):
    """Admin-only doctor tracking page listing all doctors or filtering by selected doctor."""
    from django.db.models import Q

    doctor_id = request.GET.get("doctor", "").strip()
    booking_date_from = request.GET.get("booking_date_from", "").strip()
    booking_date_to = request.GET.get("booking_date_to", "").strip()
    appointment_date_from = request.GET.get("appointment_date_from", "").strip()
    appointment_date_to = request.GET.get("appointment_date_to", "").strip()
    status_filter = request.GET.get("status", "").strip()
    search_query = request.GET.get("q", "").strip()
    group_by = request.GET.get("group_by", "none").strip()
    export_format = request.GET.get("export", "").strip()

    doctors = Doctor.objects.all().order_by("user__first_name", "user__last_name")
    selected_doctor = None
    appointments = Appointment.objects.none()
    stats = {}
    doctor_summary_list = []

    base_qs = Appointment.objects.all().select_related("patient__user", "doctor__user")
    if booking_date_from:
        try:
            base_qs = base_qs.filter(created_at__date__gte=datetime.strptime(booking_date_from, "%Y-%m-%d").date())
        except ValueError:
            pass
    if booking_date_to:
        try:
            base_qs = base_qs.filter(created_at__date__lte=datetime.strptime(booking_date_to, "%Y-%m-%d").date())
        except ValueError:
            pass
    if appointment_date_from:
        try:
            base_qs = base_qs.filter(appointment_date__gte=datetime.strptime(appointment_date_from, "%Y-%m-%d").date())
        except ValueError:
            pass
    if appointment_date_to:
        try:
            base_qs = base_qs.filter(appointment_date__lte=datetime.strptime(appointment_date_to, "%Y-%m-%d").date())
        except ValueError:
            pass
    if status_filter:
        base_qs = base_qs.filter(status=status_filter)
    if search_query:
        base_qs = base_qs.filter(
            Q(patient__user__first_name__icontains=search_query) |
            Q(patient__user__last_name__icontains=search_query) |
            Q(patient__user__email__icontains=search_query) |
            Q(patient__phone_number__icontains=search_query) |
            Q(doctor__user__first_name__icontains=search_query) |
            Q(doctor__user__last_name__icontains=search_query)
        )

    if doctor_id:
        try:
            selected_doctor = Doctor.objects.get(pk=int(doctor_id))
            qs = base_qs.filter(doctor=selected_doctor)
            appointments = qs.order_by("-appointment_date", "-start_time")

            total = appointments.count()
            completed = appointments.filter(status="completed").count()
            missed = appointments.filter(status="missed").count()
            cancelled = appointments.filter(status="cancelled").count()
            pending = appointments.filter(status="pending").count()
            confirmed = appointments.filter(status="confirmed").count()

            paid = appointments.filter(payment_status="paid")
            total_fees = paid.aggregate(total=Sum("fee_bdt"))["total"] or Decimal("0")
            total_platform = paid.aggregate(total=Sum("platform_fee_bdt"))["total"] or Decimal("0")
            total_payout = paid.aggregate(total=Sum("net_doctor_payout_bdt"))["total"] or Decimal("0")
            total_refund = appointments.filter(status="cancelled").aggregate(total=Sum("refund_amount"))["total"] or Decimal("0")

            stats = {
                "total": total,
                "completed": completed,
                "missed": missed,
                "cancelled": cancelled,
                "pending": pending,
                "confirmed": confirmed,
                "total_fees": total_fees,
                "total_platform": total_platform,
                "total_payout": total_payout,
                "total_refund": total_refund,
            }
        except (Doctor.DoesNotExist, ValueError):
            selected_doctor = None

    if not selected_doctor:
        appointments = base_qs.order_by("-appointment_date", "-start_time")
        total = appointments.count()
        completed = appointments.filter(status="completed").count()
        missed = appointments.filter(status="missed").count()
        cancelled = appointments.filter(status="cancelled").count()
        pending = appointments.filter(status="pending").count()
        confirmed = appointments.filter(status="confirmed").count()

        paid = appointments.filter(payment_status="paid")
        total_fees = paid.aggregate(total=Sum("fee_bdt"))["total"] or Decimal("0")
        total_platform = paid.aggregate(total=Sum("platform_fee_bdt"))["total"] or Decimal("0")
        total_payout = paid.aggregate(total=Sum("net_doctor_payout_bdt"))["total"] or Decimal("0")
        total_refund = appointments.filter(status="cancelled").aggregate(total=Sum("refund_amount"))["total"] or Decimal("0")

        stats = {
            "total": total,
            "completed": completed,
            "missed": missed,
            "cancelled": cancelled,
            "pending": pending,
            "confirmed": confirmed,
            "total_fees": total_fees,
            "total_platform": total_platform,
            "total_payout": total_payout,
            "total_refund": total_refund,
        }

        # Build summary for ALL doctors
        for doc in doctors:
            doc_apts = base_qs.filter(doctor=doc)
            d_total = doc_apts.count()
            d_completed = doc_apts.filter(status="completed").count()
            d_cancelled = doc_apts.filter(status="cancelled").count()
            d_paid = doc_apts.filter(payment_status="paid")
            d_fees = d_paid.aggregate(total=Sum("fee_bdt"))["total"] or Decimal("0")
            d_platform = d_paid.aggregate(total=Sum("platform_fee_bdt"))["total"] or Decimal("0")
            d_payout = d_paid.aggregate(total=Sum("net_doctor_payout_bdt"))["total"] or Decimal("0")
            d_refund = doc_apts.filter(status="cancelled").aggregate(total=Sum("refund_amount"))["total"] or Decimal("0")

            doctor_summary_list.append({
                "doctor": doc,
                "id": doc.id,
                "name": doc.user.get_full_name() or doc.user.username,
                "specialty": doc.specialty or "General Physician",
                "phone": doc.phone_number or "N/A",
                "total": d_total,
                "completed": d_completed,
                "cancelled": d_cancelled,
                "fees": d_fees,
                "platform": d_platform,
                "payout": d_payout,
                "refund": d_refund,
            })

    # Calculate 12-Month Monthly Site Income Trend
    today_date = timezone.localdate()
    monthly_trend_labels = []
    monthly_trend_data = []

    for i in range(11, -1, -1):
        m = today_date.month - i
        y = today_date.year
        while m <= 0:
            m += 12
            y -= 1

        m_start = datetime(y, m, 1).date()
        if m == 12:
            m_end = datetime(y + 1, 1, 1).date()
        else:
            m_end = datetime(y, m + 1, 1).date()

        m_paid = appointments.filter(
            created_at__date__gte=m_start,
            created_at__date__lt=m_end,
            payment_status="paid"
        )
        m_income = m_paid.aggregate(total=Sum("platform_fee_bdt"))["total"] or Decimal("0")
        monthly_trend_labels.append(m_start.strftime("%b %Y"))
        monthly_trend_data.append(float(m_income))

    if export_format == "pdf":
        metrics = compute_appointment_report(appointments)
        title = f"Doctor Report - Dr. {selected_doctor.user.get_full_name()}" if selected_doctor else "All Doctors Tracking Report"
        fname = f"doctor_{doctor_id}_tracking.pdf" if selected_doctor else "all_doctors_tracking.pdf"
        return export_report_pdf(appointments, metrics, title, fname, doctor=selected_doctor, owner_type="doctor" if selected_doctor else "generic")

    status_choices = Appointment.STATUS_CHOICES

    return render(request, "admin/doctor_tracking.html", {
        "doctors": doctors,
        "selected_doctor": selected_doctor,
        "appointments": appointments,
        "stats": stats,
        "doctor_summary_list": doctor_summary_list,
        "status_choices": status_choices,
        "doctor_id": doctor_id,
        "booking_date_from": booking_date_from,
        "booking_date_to": booking_date_to,
        "appointment_date_from": appointment_date_from,
        "appointment_date_to": appointment_date_to,
        "status_filter": status_filter,
        "search_query": search_query,
        "group_by": group_by,
        "monthly_trend_labels": monthly_trend_labels,
        "monthly_trend_data": monthly_trend_data,
    })


@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_delete_doctor(request, doctor_id):
    """Admin endpoint to safely delete a doctor account."""
    if request.method == "POST":
        doctor = get_object_or_404(Doctor, pk=doctor_id)
        doctor_name = doctor.user.get_full_name() or doctor.user.username
        user = doctor.user
        doctor.delete()
        if user:
            user.delete()
        messages.success(request, f"Doctor Dr. {doctor_name} (#DOC-{doctor_id}) was successfully deleted.")
    return redirect("admin_doctor_tracking")


