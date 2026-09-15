from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from accounts.decorators import never_cache_auth
from doctors.models import Appointment
from prescriptions.models import FollowUp, Prescription, ReminderSchedule


@never_cache_auth
@login_required
def patient_analytics_view(request):
    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        messages.error(request, "Access restricted to patients.")
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

    base_qs = Appointment.objects.filter(patient=patient).select_related("doctor__user")

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
            Q(doctor__user__first_name__icontains=search_query) |
            Q(doctor__user__last_name__icontains=search_query) |
            Q(doctor__specialty__icontains=search_query)
        )

    all_appointments = base_qs.order_by("-appointment_date", "-start_time")
    completed = all_appointments.filter(status="completed")
    cancelled = all_appointments.filter(status="cancelled")
    paid = all_appointments.filter(payment_status="paid")

    total_spent = paid.aggregate(total=Sum("fee_bdt"))["total"] or 0
    total_refunds = cancelled.aggregate(total=Sum("refund_amount"))["total"] or 0
    net_spent = total_spent - total_refunds

    doses_qs = ReminderSchedule.objects.filter(prescription_item__prescription__patient=patient)
    total_doses = doses_qs.count()
    taken_doses = doses_qs.filter(status="taken").count()
    adherence_rate = round((taken_doses / total_doses * 100), 1) if total_doses > 0 else 0

    recent_appointments = all_appointments[:50]

    return render(request, "patient/analytics.html", {
        "total_appointments": all_appointments.count(),
        "completed_count": completed.count(),
        "cancelled_count": cancelled.count(),
        "total_spent": total_spent,
        "total_refunds": total_refunds,
        "net_spent": net_spent,
        "adherence_rate": adherence_rate,
        "recent_appointments": recent_appointments,
        "start_date": start_date,
        "end_date": end_date,
        "status_filter": status_filter,
        "search_query": search_query,
        "date_preset": date_preset,
    })


@never_cache_auth
@login_required
def patient_payment_history(request):
    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        messages.error(request, "Only patients can view payment history.")
        return redirect("home")

    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()

    paid_apts = Appointment.objects.filter(
        patient=patient,
        payment_status="paid"
    ).select_related("doctor__user").order_by("-appointment_date")

    cancelled_apts = Appointment.objects.filter(
        patient=patient,
        status="cancelled"
    ).select_related("doctor__user").order_by("-appointment_date")

    if start_date:
        paid_apts = paid_apts.filter(appointment_date__gte=start_date)
        cancelled_apts = cancelled_apts.filter(appointment_date__gte=start_date)
    if end_date:
        paid_apts = paid_apts.filter(appointment_date__lte=end_date)
        cancelled_apts = cancelled_apts.filter(appointment_date__lte=end_date)

    export_format = (request.GET.get("export") or "pdf").lower().strip()
    if export_format == "csv":
        import csv
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="patient_payment_history_{timezone.localdate()}.csv"'

        writer = csv.writer(response)
        writer.writerow(["CareBridge AI Patient Payment & Refund History"])
        writer.writerow([f"Patient: {request.user.get_full_name() or request.user.username}"])
        writer.writerow([f"Date Range: {start_date or 'All time'} to {end_date or 'All time'}"])
        writer.writerow([])
        writer.writerow(["Completed Payments"])
        writer.writerow(["Appointment ID", "Date", "Doctor", "Fee (BDT)", "Status", "Transaction ID"])

        for apt in paid_apts:
            doc_name = f"Dr. {apt.doctor.user.get_full_name() or apt.doctor.user.username}"
            writer.writerow([
                apt.pk,
                apt.appointment_date,
                doc_name,
                f"{apt.fee_bdt:.2f}",
                apt.get_status_display(),
                apt.transaction_id or "N/A",
            ])

        writer.writerow([])
        writer.writerow(["Refunds & Wallet Credits"])
        writer.writerow(["Appointment ID", "Date", "Doctor", "Refund Amount (BDT)", "Refund Status"])

        for apt in cancelled_apts:
            doc_name = f"Dr. {apt.doctor.user.get_full_name() or apt.doctor.user.username}"
            writer.writerow([
                apt.pk,
                apt.appointment_date,
                doc_name,
                f"{apt.refund_amount:.2f}",
                apt.get_refund_status_display(),
            ])

        return response

    # Default: ReportLab PDF Statement
    import io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
    )
    styles = getSampleStyleSheet()

    teal = colors.HexColor("#0f766e")
    dark = colors.HexColor("#1c1917")
    slate = colors.HexColor("#57534e")
    light_bg = colors.HexColor("#f0fdfa")
    line = colors.HexColor("#e7e5e4")

    title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=18, textColor=teal, spaceAfter=2, leading=22)
    subtitle_style = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=9, textColor=slate, spaceAfter=8, leading=13)
    heading_style = ParagraphStyle("heading", parent=styles["Heading2"], fontSize=11, textColor=teal, spaceAfter=4, spaceBefore=8, leading=14)
    normal_style = ParagraphStyle("normal", parent=styles["Normal"], fontSize=8.5, leading=11, textColor=dark)
    header_style = ParagraphStyle("header", parent=styles["Normal"], fontSize=8.5, textColor=colors.white, fontName="Helvetica-Bold")
    small_style = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10, textColor=slate)

    elements = []
    patient_name = request.user.get_full_name() or request.user.username
    date_range_str = f"{start_date or 'Beginning'} to {end_date or 'Present'}"

    elements.append(Paragraph("CareBridge AI — Patient Payment & Billing Statement", title_style))
    elements.append(Paragraph("Official Electronic Healthcare Financial Record", subtitle_style))

    # Patient Meta
    meta_data = [
        [Paragraph("<b>Patient Name</b>", normal_style), Paragraph(patient_name, normal_style),
         Paragraph("<b>Patient ID</b>", normal_style), Paragraph(f"#PAT-{patient.id}", normal_style)],
        [Paragraph("<b>Contact Phone</b>", normal_style), Paragraph(patient.phone_number or "N/A", normal_style),
         Paragraph("<b>Period</b>", normal_style), Paragraph(date_range_str, normal_style)],
        [Paragraph("<b>Statement Date</b>", normal_style), Paragraph(timezone.localdate().strftime("%d %b %Y"), normal_style),
         Paragraph("<b>Total Completed Payments</b>", normal_style), Paragraph(str(paid_apts.count()), normal_style)],
    ]
    meta_table = Table(meta_data, colWidths=[35 * mm, 55 * mm, 40 * mm, 50 * mm])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), light_bg),
        ('BACKGROUND', (2, 0), (2, -1), light_bg),
        ('GRID', (0, 0), (-1, -1), 0.5, line),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 8))

    # Total metrics
    total_paid_bdt = sum(apt.fee_bdt for apt in paid_apts)
    total_refund_bdt = sum(apt.refund_amount for apt in cancelled_apts)
    elements.append(Paragraph(f"<b>Financial Summary:</b> Total Paid: <b>BDT {total_paid_bdt:,.2f}</b> &nbsp;|&nbsp; Total Refunds: <b>BDT {total_refund_bdt:,.2f}</b>", normal_style))
    elements.append(Spacer(1, 8))

    # Paid appointments table
    elements.append(Paragraph("Payment Transactions", heading_style))
    pay_header = [
        Paragraph("<b>Apt #</b>", header_style),
        Paragraph("<b>Date</b>", header_style),
        Paragraph("<b>Doctor</b>", header_style),
        Paragraph("<b>Fee (BDT)</b>", header_style),
        Paragraph("<b>Method</b>", header_style),
        Paragraph("<b>Transaction ID</b>", header_style),
    ]
    pay_rows = [pay_header]
    for apt in paid_apts:
        doc_name = f"Dr. {apt.doctor.user.get_full_name() or apt.doctor.user.username}"
        pay_rows.append([
            Paragraph(f"#{apt.pk}", normal_style),
            Paragraph(apt.appointment_date.strftime("%d %b %Y"), normal_style),
            Paragraph(doc_name, normal_style),
            Paragraph(f"{apt.fee_bdt:,.2f}", normal_style),
            Paragraph(apt.payment_method or "Online", normal_style),
            Paragraph(apt.transaction_id or "Completed", normal_style),
        ])

    if len(pay_rows) > 1:
        pay_table = Table(pay_rows, colWidths=[15 * mm, 25 * mm, 48 * mm, 25 * mm, 25 * mm, 42 * mm])
        pay_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), teal),
            ('GRID', (0, 0), (-1, -1), 0.5, line),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafaf9")]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(pay_table)
    else:
        elements.append(Paragraph("No paid appointment transactions found for this period.", small_style))

    # Refunds section
    if cancelled_apts.exists():
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("Refunds & Wallet Credits", heading_style))
        ref_header = [
            Paragraph("<b>Apt #</b>", header_style),
            Paragraph("<b>Date</b>", header_style),
            Paragraph("<b>Doctor</b>", header_style),
            Paragraph("<b>Refund (BDT)</b>", header_style),
            Paragraph("<b>Status</b>", header_style),
        ]
        ref_rows = [ref_header]
        for apt in cancelled_apts:
            doc_name = f"Dr. {apt.doctor.user.get_full_name() or apt.doctor.user.username}"
            ref_rows.append([
                Paragraph(f"#{apt.pk}", normal_style),
                Paragraph(apt.appointment_date.strftime("%d %b %Y"), normal_style),
                Paragraph(doc_name, normal_style),
                Paragraph(f"{apt.refund_amount:,.2f}", normal_style),
                Paragraph(apt.get_refund_status_display(), normal_style),
            ])
        ref_table = Table(ref_rows, colWidths=[20 * mm, 30 * mm, 60 * mm, 35 * mm, 35 * mm])
        ref_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#be123c")),
            ('GRID', (0, 0), (-1, -1), 0.5, line),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#fff1f2")]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(ref_table)

    elements.append(Spacer(1, 14))
    elements.append(Paragraph("CareBridge AI Telemedicine & Clinical Systems &bull; Automated Computer-Generated Billing Statement", small_style))

    doc.build(elements)
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="patient_payment_history_{timezone.localdate()}.pdf"'
    return response
