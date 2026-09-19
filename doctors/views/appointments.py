import os
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.utils import timezone

from accounts.decorators import never_cache_auth
from accounts.models import AppNotification, SiteSettings
from doctors.models import Appointment
from prescriptions.models import Prescription


def _auto_detect_missed_for_doctor(doctor):
    """Auto-detect past appointments that were never completed with a prescription or marked visited/missed."""
    today = timezone.localdate()
    past_unresolved = Appointment.objects.filter(
        doctor=doctor,
        appointment_date__lt=today,
        status__in=["confirmed", "pending"],
    ).select_related("patient__user")

    for apt in past_unresolved:
        has_rx = apt.prescriptions.exists() or Prescription.objects.filter(
            doctor=doctor,
            patient=apt.patient,
            issued_at__date=apt.appointment_date,
        ).exists()
        if not has_rx:
            apt.status = "missed"
            apt.save(update_fields=["status"])
            AppNotification.objects.create(
                user=apt.patient.user,
                title="Appointment Marked as Missed",
                message=f"Your appointment on {apt.appointment_date.strftime('%d %b %Y')} with Dr. {doctor.user.get_full_name() or doctor.user.username} was marked as missed. Please reschedule if needed.",
                notification_type="booking",
                link_url=reverse("patient:doctor_list"),
            )


def _auto_mark_missed_today(doctor=None, patient=None):
    """Auto-mark today's appointments as missed if appointment start_time + 4 hours has passed without prescription."""
    now = timezone.localtime(timezone.now())
    today = now.date()
    tz = timezone.get_current_timezone()
    today_unresolved = Appointment.objects.filter(
        appointment_date=today,
        status__in=["confirmed", "pending"],
    ).select_related("patient__user", "doctor__user")

    if doctor:
        today_unresolved = today_unresolved.filter(doctor=doctor)
    if patient:
        today_unresolved = today_unresolved.filter(patient=patient)

    for apt in today_unresolved:
        apt_start_dt = timezone.make_aware(
            timezone.datetime.combine(apt.appointment_date, apt.start_time),
            tz
        )
        if now >= apt_start_dt + timezone.timedelta(hours=4):
            has_rx = apt.prescriptions.exists() or Prescription.objects.filter(
                doctor=apt.doctor,
                patient=apt.patient,
                issued_at__date=today,
            ).exists()
            if not has_rx:
                apt.status = "missed"
                apt.save(update_fields=["status"])
                AppNotification.objects.create(
                    user=apt.patient.user,
                    title="Appointment Marked as Missed",
                    message=f"Your appointment today ({apt.start_time.strftime('%I:%M %p')}) with Dr. {apt.doctor.user.get_full_name() or apt.doctor.user.username} was automatically marked as missed as the 4-hour window passed without a prescription. Please reschedule if needed.",
                    notification_type="booking",
                    link_url=reverse("patient:doctor_list"),
                )



@never_cache_auth
@login_required
def appointment_list(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Only doctors can view appointment list.")
        return redirect("home")

    today = timezone.localdate()
    _auto_detect_missed_for_doctor(doctor)
    _auto_mark_missed_today(doctor=doctor)

    status_filter = request.GET.get("status", "all").strip()
    filter_type = request.GET.get("filter_type", "quick").strip()
    filter_value = request.GET.get("filter_value", "").strip()
    filter_month = (request.GET.get("filter_month") or request.GET.get("month", "")).strip()
    filter_year = (request.GET.get("filter_year") or request.GET.get("year", "")).strip()

    base_qs = Appointment.objects.filter(doctor=doctor).select_related("patient__user", "patient").order_by("-appointment_date", "-start_time")

    if status_filter == "today":
        base_qs = base_qs.filter(appointment_date=today)
    elif status_filter == "upcoming":
        base_qs = base_qs.filter(appointment_date__gte=today, status__in=["pending", "confirmed"])
    elif status_filter == "confirmed":
        base_qs = base_qs.filter(status="confirmed")
    elif status_filter == "pending_verification":
        base_qs = base_qs.filter(payment_status="pending_verification").exclude(status="cancelled")
    elif status_filter == "cancellation_pending":
        base_qs = base_qs.filter(status="cancellation_pending")
    elif status_filter == "cancelled":
        base_qs = base_qs.filter(status="cancelled")
    elif status_filter == "completed":
        base_qs = base_qs.filter(status="completed")
    elif status_filter == "missed":
        base_qs = base_qs.filter(status="missed")
    elif status_filter == "pending":
        base_qs = base_qs.filter(status="pending")

    if filter_type == "range":
        start_d = request.GET.get("start_date")
        end_d = request.GET.get("end_date")
        if start_d:
            base_qs = base_qs.filter(appointment_date__gte=start_d)
        if end_d:
            base_qs = base_qs.filter(appointment_date__lte=end_d)
    elif filter_type == "date" and filter_value:
        try:
            base_qs = base_qs.filter(appointment_date=filter_value)
        except Exception:
            pass
    elif filter_type == "month" and filter_month:
        try:
            m_val = int(filter_month)
            if filter_year:
                y_val = int(filter_year)
                base_qs = base_qs.filter(appointment_date__year=y_val, appointment_date__month=m_val)
            else:
                base_qs = base_qs.filter(appointment_date__month=m_val)
        except (ValueError, TypeError):
            pass
    elif filter_type == "year" and filter_year:
        try:
            base_qs = base_qs.filter(appointment_date__year=int(filter_year))
        except (ValueError, TypeError):
            pass

    search_q = request.GET.get("q", "").strip()
    if search_q:
        base_qs = base_qs.filter(
            Q(patient__user__first_name__icontains=search_q)
            | Q(patient__user__last_name__icontains=search_q)
            | Q(patient__user__email__icontains=search_q)
            | Q(patient__phone_number__icontains=search_q)
        )

    all_apts = Appointment.objects.filter(doctor=doctor)
    pending_verifs = all_apts.filter(payment_status="pending_verification").exclude(status="cancelled")
    overdue_count = sum(1 for a in pending_verifs if a.is_verification_overdue)

    stats = {
        "all": all_apts.count(),
        "total": all_apts.count(),
        "today": all_apts.filter(appointment_date=today).count(),
        "upcoming": all_apts.filter(appointment_date__gte=today, status__in=["pending", "confirmed"]).count(),
        "confirmed": all_apts.filter(status="confirmed").count(),
        "pending_verification": pending_verifs.count(),
        "cancellation_pending": all_apts.filter(status="cancellation_pending").count(),
        "completed": all_apts.filter(status="completed").count(),
        "missed": all_apts.filter(status="missed").count(),
        "cancelled": all_apts.filter(status="cancelled").count(),
        "pending": all_apts.filter(status="pending").count(),
        "overdue_verification": overdue_count,
    }

    paginator = Paginator(base_qs, 15)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    now = timezone.localtime(timezone.now())
    tz = timezone.get_current_timezone()
    for apt in page_obj:
        apt_start = timezone.make_aware(timezone.datetime.combine(apt.appointment_date, apt.start_time), tz)
        apt.window_end = apt_start + timezone.timedelta(hours=4)
        apt.time_passed = now > apt_start
        apt.has_prescription = apt.prescriptions.exists()
        apt.remaining_seconds = max(0, int((apt.window_end - now).total_seconds())) if (apt.time_passed and not apt.has_prescription and apt.status in ("pending", "confirmed", "cancellation_pending")) else 0
        apt.is_window_expired = apt.has_prescription or apt.status in ("completed", "missed", "cancelled", "refunded") or (now > apt.window_end and apt.status in ("pending", "confirmed", "cancellation_pending"))
        if apt.payment_status == "pending_verification":
            apt.verification_overdue = apt.is_verification_overdue
            apt.hours_remaining_verification = apt.hours_remaining_verification
        else:
            apt.verification_overdue = False
            apt.hours_remaining_verification = 0


    years = range(today.year - 2, today.year + 2)
    months = [
        (1, "January"), (2, "February"), (3, "March"), (4, "April"),
        (5, "May"), (6, "June"), (7, "July"), (8, "August"),
        (9, "September"), (10, "October"), (11, "November"), (12, "December")
    ]

    selected_month = int(filter_month) if filter_month.isdigit() else today.month
    selected_year = int(filter_year) if filter_year.isdigit() else today.year

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

    tz = timezone.get_current_timezone()
    now_local = timezone.localtime(timezone.now())
    apt_datetime = timezone.make_aware(
        timezone.datetime.combine(appointment.appointment_date, appointment.start_time), tz
    )
    hours_until = (apt_datetime - now_local).total_seconds() / 3600
    is_admin = (request.user.is_staff or request.user.is_superuser)

    # Doctor can only cancel IF payment is verified ("paid") AND appointment is >12h away AND not already cancelled/completed/refunded
    can_doctor_cancel = (
        appointment.payment_status == "paid"
        and hours_until > 12
        and appointment.status not in ("cancelled", "completed", "missed", "refunded")
    ) or (is_admin and appointment.status != "cancelled")

    if request.method == "POST":
        is_doctor = (hasattr(request.user, "doctor_profile") and request.user.doctor_profile == appointment.doctor)

        if appointment.payment_status == "pending_verification" and not (is_doctor or is_admin):
            messages.error(request, "Only Admin or assigned Doctor can change appointment status when payment verification is pending.")
            return redirect("doctors:appointment_detail", appointment_id=appointment.pk)

        if appointment.prescriptions.exists() and not (request.user.is_staff or request.user.is_superuser):
            messages.error(request, "This appointment was completed via a prescription and its status can no longer be changed.")
            return redirect("doctors:appointment_detail", appointment_id=appointment.pk)

        previous_status = appointment.status
        new_status = request.POST.get("status", appointment.status)
        appointment.notes = request.POST.get("notes", appointment.notes)

        if new_status == "missed" and previous_status != "missed" and not is_admin:
            messages.error(request, "Missed status cannot be given by doctor. It is automatically assigned after the 4-hour window passes without a prescription.")
            return redirect("doctors:appointment_detail", appointment_id=appointment.pk)

        if new_status == "cancelled" and previous_status != "cancelled":
            if not is_admin:
                if appointment.payment_status != "paid":
                    messages.error(request, "Cancellation is not allowed before payment is verified.")
                    return redirect("doctors:appointment_detail", appointment_id=appointment.pk)
                if hours_until <= 12:
                    messages.error(request, "Cancellation is not allowed within 12 hours or less of the appointment start time.")
                    return redirect("doctors:appointment_detail", appointment_id=appointment.pk)

            appointment.status = "cancelled"
            appointment.notes = request.POST.get("notes", appointment.notes)
            if appointment.payment_status in ("paid", "pending_verification", "pending") or bool(appointment.transaction_id):
                appointment.refund_status = "full"
                appointment.refund_amount = appointment.fee_bdt
                appointment.payment_status = "refunded"
                appointment.platform_fee_bdt = Decimal("0.00")
                appointment.net_doctor_payout_bdt = Decimal("0.00")
                appointment.save()

                patient = appointment.patient
                patient.balance = (patient.balance or Decimal("0")) + appointment.refund_amount
                patient.save(update_fields=["balance"])

                doctor_obj = getattr(request.user, "doctor_profile", appointment.doctor)
                AppNotification.objects.create(
                    user=patient.user,
                    title="Appointment Cancelled — Full Refund",
                    message=f"Your appointment on {appointment.appointment_date} with Dr. {doctor_obj.user.get_full_name() or doctor_obj.user.username} was cancelled by the doctor. A full refund of {appointment.refund_amount} BDT has been credited to your wallet.",
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

    appointment.can_doctor_cancel = can_doctor_cancel
    appointment.hours_until = hours_until
    return render(request, "doctors/appointment_detail.html", {"appointment": appointment})


@never_cache_auth
@login_required
def approve_cancellation(request, appointment_id):
    """Doctor approves or rejects a patient's cancellation request."""
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

        if action == "approve":
            appointment.status = "cancelled"
            appointment.cancellation_approved = True

            if appointment.payment_status in ("paid", "refunded"):
                settings_obj = SiteSettings.get_solo()
                comm_rate = Decimal(str(settings_obj.platform_commission_rate or "15.00")) / Decimal("100")
                refund_pct = Decimal(str(settings_obj.patient_refund_percentage or "35.00")) / Decimal("100")
                display_pct = settings_obj.patient_refund_percentage

                site_charge = (appointment.fee_bdt * comm_rate).quantize(Decimal("0.01"))
                remaining_money = max(Decimal("0.00"), appointment.fee_bdt - site_charge)
                appointment.refund_status = "partial"
                appointment.refund_amount = (remaining_money * refund_pct).quantize(Decimal("0.01"))
                appointment.payment_status = "refunded"
                appointment.save()

                patient = appointment.patient
                patient.balance = (patient.balance or Decimal("0")) + appointment.refund_amount
                patient.save(update_fields=["balance"])

                AppNotification.objects.create(
                    user=patient.user,
                    title="Refund Credited to Wallet",
                    message=f"A refund of {appointment.refund_amount} BDT ({display_pct}%) has been credited to your CareBridge wallet balance for the appointment on {appointment.appointment_date}.",
                    notification_type="booking",
                    link_url=reverse("patient:appointments"),
                )
            else:
                display_pct = SiteSettings.get_solo().patient_refund_percentage
                appointment.refund_status = "none"
                appointment.refund_amount = Decimal("0.00")
                appointment.save()

            AppNotification.objects.create(
                user=appointment.patient.user,
                title="Cancellation Approved",
                message=f"Your cancellation for {appointment.appointment_date} was approved. Refund: {appointment.refund_amount} BDT ({display_pct}%) has been processed.",
                notification_type="booking",
                link_url=reverse("patient:appointments"),
            )
            AppNotification.objects.create(
                user=request.user,
                title="Cancellation Approved — Refund Issued",
                message=f"You approved cancellation for {appointment.patient.user.get_full_name()} on {appointment.appointment_date}. Patient refunded {appointment.refund_amount} BDT ({display_pct}%). Your payout adjusted.",
                notification_type="booking",
                link_url=reverse("doctors:appointment_list"),
            )
            messages.success(request, f"Cancellation approved. Patient refunded {appointment.refund_amount} BDT ({display_pct}%).")
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
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("home")

    appointment = get_object_or_404(Appointment, pk=appointment_id, doctor=doctor)

    if request.method == "POST":
        if appointment.prescriptions.exists():
            messages.error(request, "This appointment was completed via a prescription and its status can no longer be changed.")
            return redirect("doctors:appointment_list")

        action = request.POST.get("action")
        if action == "visited":
            appointment.status = "completed"
            appointment.save(update_fields=["status"])
            messages.success(request, f"Marked {appointment.patient.user.get_full_name()} as visited.")
        elif action == "missed":
            messages.error(request, "Missed status cannot be given by doctor. It is automatically assigned after the 4-hour window passes without a prescription.")

    return redirect("doctors:appointment_list")


@never_cache_auth
@login_required
def auto_detect_missed(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("home")

    _auto_detect_missed_for_doctor(doctor)
    _auto_mark_missed_today(doctor=doctor)

    messages.success(request, "Auto-detected and updated missed appointments as per the 4-hour window rule.")
    return redirect("doctors:appointment_list")



@never_cache_auth
@login_required
def appointment_report(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("home")

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
def appointment_report_export(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("home")

    appointments = Appointment.objects.filter(doctor=doctor).select_related("patient__user").order_by("-appointment_date", "-start_time")

    import io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics, ttfonts
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

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


@never_cache_auth
@login_required
def reports(request):
    from datetime import datetime
    from carebridge.reports_utils import compute_appointment_report, export_report_pdf

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
    appointment = get_object_or_404(Appointment, pk=appointment_id)
    doctor_profile = getattr(request.user, "doctor_profile", None)
    is_doctor = (doctor_profile and doctor_profile == appointment.doctor)
    is_admin = (request.user.is_staff or request.user.is_superuser)

    if not (is_doctor or is_admin):
        messages.error(request, "Only Admin or assigned Doctor can verify payment or change appointment status.")
        return redirect("home")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "approve":
            appointment.payment_status = "paid"
            appointment.payment_verified = True
            appointment.payment_verified_at = timezone.now()
            appointment.payment_verified_by = doctor_profile
            appointment.status = "confirmed"
            appointment.paid_amount = appointment.fee_bdt
            appointment.payment_appeal_status = "approved_payment"
            commission_rate = Decimal(str(SiteSettings.get_solo().platform_commission_rate or "15.00")) / Decimal("100")
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

        elif action in ("full_refund", "refund"):
            refund_amount = appointment.fee_bdt
            appointment.status = "cancelled"
            appointment.payment_status = "refunded"
            appointment.refund_status = "full"
            appointment.refund_amount = refund_amount
            appointment.platform_fee_bdt = Decimal("0.00")
            appointment.net_doctor_payout_bdt = Decimal("0.00")
            appointment.payment_appeal_status = "approved_refund"
            appointment.save()

            patient = appointment.patient
            patient.balance = (patient.balance or Decimal("0.00")) + refund_amount
            patient.save(update_fields=["balance"])

            AppNotification.objects.create(
                user=patient.user,
                title="✓ Full Refund Issued to Wallet",
                message=f"A full refund of {refund_amount} BDT has been credited to your wallet for Appointment #{appointment.id}.",
                notification_type="booking",
                link_url=reverse("patient:appointments"),
            )
            messages.success(request, f"Full refund of {refund_amount} BDT credited to patient's wallet.")

        elif action == "reject":
            appointment.payment_status = "pending"
            appointment.payment_verified = False
            appointment.payment_appeal_status = "rejected"
            appointment.save()

            AppNotification.objects.create(
                user=appointment.patient.user,
                title="Payment Verification Failed",
                message=f"Your payment proof for appointment on {appointment.appointment_date} was not accepted. Please submit correct proof or contact support.",
                notification_type="booking",
                link_url=reverse("patient:appointments"),
            )
            messages.error(request, "Payment proof rejected. Patient will be notified to re-submit.")

        if is_admin:
            return redirect("accounts:admin_unverified_dashboard")
        return redirect("doctors:appointment_list")

    return render(request, "doctors/verify_payment.html", {
        "appointment": appointment,
    })
