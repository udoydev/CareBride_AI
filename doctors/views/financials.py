import io
import os
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone

from accounts.decorators import never_cache_auth
from doctors.models import Appointment


@never_cache_auth
@login_required
def doctor_financial_report(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Only doctors can view financial reports.")
        return redirect("home")

    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()
    status_filter = request.GET.get("status", "").strip()
    search_query = request.GET.get("q", "").strip()
    export_format = (request.GET.get("export") or "pdf").lower().strip()

    paid_appointments = Appointment.objects.filter(
        doctor=doctor,
        payment_status="paid"
    ).select_related("patient__user").order_by("-appointment_date", "-start_time")

    cancelled_appointments = Appointment.objects.filter(
        doctor=doctor,
        status="cancelled"
    ).select_related("patient__user").order_by("-appointment_date", "-start_time")

    all_appointments = Appointment.objects.filter(doctor=doctor).select_related("patient__user")

    if start_date:
        try:
            d_start = datetime.strptime(start_date, "%Y-%m-%d").date()
            paid_appointments = paid_appointments.filter(appointment_date__gte=d_start)
            cancelled_appointments = cancelled_appointments.filter(appointment_date__gte=d_start)
            all_appointments = all_appointments.filter(appointment_date__gte=d_start)
        except ValueError:
            pass

    if end_date:
        try:
            d_end = datetime.strptime(end_date, "%Y-%m-%d").date()
            paid_appointments = paid_appointments.filter(appointment_date__lte=d_end)
            cancelled_appointments = cancelled_appointments.filter(appointment_date__lte=d_end)
            all_appointments = all_appointments.filter(appointment_date__lte=d_end)
        except ValueError:
            pass

    if status_filter:
        if status_filter == "paid":
            all_appointments = all_appointments.filter(payment_status="paid")
        elif status_filter == "refunded":
            all_appointments = all_appointments.filter(Q(status="cancelled") | Q(payment_status="refunded"))
        else:
            all_appointments = all_appointments.filter(status=status_filter)

    if search_query:
        search_q = (
            Q(patient__user__first_name__icontains=search_query) |
            Q(patient__user__last_name__icontains=search_query) |
            Q(patient__user__email__icontains=search_query) |
            Q(patient__phone_number__icontains=search_query)
        )
        paid_appointments = paid_appointments.filter(search_q)
        cancelled_appointments = cancelled_appointments.filter(search_q)
        all_appointments = all_appointments.filter(search_q)

    all_appointments = all_appointments.order_by("-appointment_date", "-start_time")

    total_gross = paid_appointments.aggregate(Sum("fee_bdt"))["fee_bdt__sum"] or Decimal("0.00")
    total_platform_fee = paid_appointments.aggregate(Sum("platform_fee_bdt"))["platform_fee_bdt__sum"] or Decimal("0.00")
    total_net_payout = paid_appointments.aggregate(Sum("net_doctor_payout_bdt"))["net_doctor_payout_bdt__sum"] or Decimal("0.00")
    total_refunds = cancelled_appointments.aggregate(Sum("refund_amount"))["refund_amount__sum"] or Decimal("0.00")

    if export_format == "csv":
        import csv
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="doctor_financial_report_{timezone.localdate()}.csv"'

        writer = csv.writer(response)
        writer.writerow(["CareBridge AI Doctor Financial Report"])
        writer.writerow([f"Doctor: Dr. {request.user.get_full_name() or request.user.username}"])
        writer.writerow([f"Date Range: {start_date or 'All time'} to {end_date or 'All time'}"])
        writer.writerow([])
        writer.writerow(["Summary Metrics"])
        writer.writerow(["Total Gross Bookings (BDT)", f"{total_gross:.2f}"])
        writer.writerow(["Total Platform Commission (BDT)", f"{total_platform_fee:.2f}"])
        writer.writerow(["Total Patient Refunds (BDT)", f"{total_refunds:.2f}"])
        writer.writerow(["Total Net Payout (BDT)", f"{total_net_payout:.2f}"])
        writer.writerow([])
        writer.writerow(["Appointments Breakdown"])
        writer.writerow(["Appointment ID", "Date", "Patient Name", "Consultation Fee (BDT)", "Platform Fee (BDT)", "Net Doctor Payout (BDT)", "Status"])

        for apt in all_appointments:
            p_name = apt.patient.user.get_full_name() or apt.patient.user.username
            writer.writerow([
                apt.pk,
                apt.appointment_date,
                p_name,
                f"{apt.fee_bdt:.2f}",
                f"{apt.platform_fee_bdt:.2f}",
                f"{apt.net_doctor_payout_bdt:.2f}",
                apt.get_status_display(),
            ])

        return response

    # Default PDF Report Generation
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics, ttfonts
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
    )
    styles = getSampleStyleSheet()

    teal = colors.HexColor("#0f766e")
    dark = colors.HexColor("#1c1917")
    slate = colors.HexColor("#57534e")
    light_bg = colors.HexColor("#f0fdfa")

    title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=16, textColor=teal, spaceAfter=2, leading=20, fontName=pdf_font_name)
    subtitle_style = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=9, textColor=slate, spaceAfter=8, leading=12, fontName=pdf_font_name)
    header_style = ParagraphStyle("header", parent=styles["Normal"], fontSize=8, textColor=colors.white, fontName=pdf_font_name)
    cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, textColor=dark, leading=11, fontName=pdf_font_name)

    elements = []
    elements.append(Paragraph("CareBridge AI — Doctor Practice & Financial Report", title_style))
    doctor_name = doctor.user.get_full_name() or doctor.user.username
    elements.append(Paragraph(
        f"Doctor: <b>Dr. {doctor_name}</b> | Specialty: <b>{doctor.specialty or 'General'}</b> | Date: <b>{timezone.localdate().strftime('%d %b %Y')}</b>",
        subtitle_style
    ))

    # Summary box metrics table
    summary_data = [
        [
            Paragraph("<b>Total Gross Bookings</b>", cell_style),
            Paragraph("<b>Platform Commission</b>", cell_style),
            Paragraph("<b>Total Refunds</b>", cell_style),
            Paragraph("<b>Net Doctor Payout</b>", cell_style),
        ],
        [
            Paragraph(f"<b>BDT {total_gross:,.2f}</b>", cell_style),
            Paragraph(f"<b>BDT {total_platform_fee:,.2f}</b>", cell_style),
            Paragraph(f"<b>BDT {total_refunds:,.2f}</b>", cell_style),
            Paragraph(f"<b>BDT {total_net_payout:,.2f}</b>", cell_style),
        ]
    ]
    summary_table = Table(summary_data, colWidths=[46 * mm, 46 * mm, 46 * mm, 46 * mm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), light_bg),
        ('BOX', (0, 0), (-1, -1), 1, teal),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#ccfbf1")),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 10))

    table_data = [
        [
            Paragraph("<b>Date</b>", header_style),
            Paragraph("<b>Patient Name</b>", header_style),
            Paragraph("<b>Fee</b>", header_style),
            Paragraph("<b>Platform Fee</b>", header_style),
            Paragraph("<b>Net Payout</b>", header_style),
            Paragraph("<b>Status</b>", header_style),
        ]
    ]

    total_fee = Decimal("0.00")
    total_platform = Decimal("0.00")
    total_payout = Decimal("0.00")

    for apt in all_appointments:
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
            Paragraph(apt.get_status_display(), cell_style),
        ])

    table_data.append([
        Paragraph("<b>TOTALS</b>", cell_style),
        Paragraph("", cell_style),
        Paragraph(f"<b>BDT {total_fee:,.2f}</b>", cell_style),
        Paragraph(f"<b>BDT {total_platform:,.2f}</b>", cell_style),
        Paragraph(f"<b>BDT {total_payout:,.2f}</b>", cell_style),
        Paragraph("", cell_style),
    ])

    col_widths = [30 * mm, 60 * mm, 30 * mm, 30 * mm, 30 * mm, 24 * mm]
    t = Table(table_data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), teal),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.HexColor("#e7e5e4")),
        ('BACKGROUND', (0, -1), (-1, -1), light_bg),
        ('LINEABOVE', (0, -1), (-1, -1), 1, teal),
    ]))
    elements.append(t)

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="doctor_financial_report_{timezone.localdate()}.pdf"'
    return response
