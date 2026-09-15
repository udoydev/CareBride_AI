"""Shared helpers for CareBridge report generation (metrics, PDF and XLSX export)."""
from decimal import Decimal
import io
import os

from django.conf import settings
from django.db.models import Count, Sum
from django.http import HttpResponse

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def compute_appointment_report(appointments):
    """Return a dict of report metrics for a given Appointment queryset.

    Income types:
      - gross_appointment_fees: total fees collected from patients
      - site_commission: platform % (configurable via SiteSettings)
      - doctor_payout: what doctors receive (fee - commission - refund)
      - refunds: total refunded to patients
      - cancellation_fees: fees from cancelled appointments

    Used by both admin reports and doctor reports (owner_type controls layout).
    """
    # Only count appointments that were actually paid
    paid_appointments = appointments.filter(payment_status="paid")
    # Gross fees collected from patients
    income_total = paid_appointments.aggregate(total=Sum("fee_bdt"))["total"] or Decimal("0")
    # Platform commission (site's income)
    site_charge = paid_appointments.aggregate(total=Sum("platform_fee_bdt"))["total"] or Decimal("0")
    # Total refunds issued to patients
    refund_total = appointments.filter(status="cancelled").aggregate(total=Sum("refund_amount"))["total"] or Decimal("0")
    # Net amount paid to doctors (fee - commission - refund)
    revenue = paid_appointments.aggregate(total=Sum("net_doctor_payout_bdt"))["total"] or Decimal("0")
    cancelled_count = appointments.filter(status="cancelled").count()
    patients_seen = appointments.filter(status="completed").values("patient").distinct().count()
    income_breakdown = {
        "gross_appointment_fees": float(income_total),
        "site_commission": float(site_charge),
        "doctor_payout": float(revenue),
        "refunds": float(refund_total),
        "cancellation_fees": float(appointments.filter(status="cancelled").aggregate(total=Sum("fee_bdt"))["total"] or Decimal("0")),
    }

    status_counts = {
        "completed": appointments.filter(status="completed").count(),
        "missed": appointments.filter(status="missed").count(),
        "cancelled": cancelled_count,
        "pending": appointments.filter(status="pending").count(),
        "confirmed": appointments.filter(status="confirmed").count(),
        "cancellation_pending": appointments.filter(status="cancellation_pending").count(),
    }

    total = appointments.count()
    daily = (
        paid_appointments
        .values("appointment_date")
        .annotate(income=Sum("fee_bdt"), site_commission=Sum("platform_fee_bdt"), visits=Count("id"))
        .order_by("appointment_date")
    )
    daily_series = [
        {
            "date": item["appointment_date"].strftime("%Y-%m-%d"),
            "income": float(item["income"] or 0),
            "site_income": float(item["site_commission"] or 0),
            "visits": item["visits"],
        }
        for item in daily
    ]

    return {
        "total": total,
        "patients_seen": patients_seen,
        "income_total": income_total,
        "refund_total": refund_total,
        "site_charge": site_charge,
        "revenue": revenue,
        "cancelled_count": cancelled_count,
        "status_counts": status_counts,
        "daily_series": daily_series,
        "income_breakdown": income_breakdown,
    }


def _autosize(ws):
    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if cell.value is not None:
                    max_length = max(max_length, len(str(cell.value)))
            except Exception:
                pass
        ws.column_dimensions[column].width = min(max_length + 2, 50)


def export_report_xlsx(appointments, title, filename, columns=None):
    """Fallback alias: converts any xlsx report request into professional PDF format."""
    metrics = compute_appointment_report(appointments)
    pdf_filename = filename.replace('.xlsx', '.pdf')
    return export_report_pdf(appointments, metrics, title, pdf_filename, columns=columns)


def export_report_pdf(appointments, metrics, title, filename, columns=None, doctor=None, patient=None, start_date=None, end_date=None, owner_type="generic"):
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    doc = SimpleDocTemplate(response, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm, leftMargin=18 * mm, rightMargin=18 * mm)
    styles = getSampleStyleSheet()

    teal = colors.HexColor("#0f766e")
    dark = colors.HexColor("#1c1917")
    slate = colors.HexColor("#57534e")
    light_bg = colors.HexColor("#f0fdfa")
    line = colors.HexColor("#e7e5e4")

    title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=20, textColor=teal, spaceAfter=2, leading=24)
    subtitle_style = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=10, textColor=slate, spaceAfter=10, leading=14)
    heading_style = ParagraphStyle("heading", parent=styles["Heading3"], fontSize=11, textColor=teal, spaceAfter=4, spaceBefore=10, leading=14)
    normal_style = ParagraphStyle("normal", parent=styles["Normal"], fontSize=9, leading=12, textColor=dark)
    small_style = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=11, textColor=slate)
    footer_style = ParagraphStyle("footer", parent=styles["Normal"], fontSize=8, textColor=slate, alignment=1, leading=10)

    elements = []

    if start_date and end_date:
        date_range = f"{start_date} to {end_date}"
    elif start_date:
        date_range = f"From {start_date}"
    elif end_date:
        date_range = f"Until {end_date}"
    else:
        date_range = "All Time"

    logo_path = os.path.join(settings.BASE_DIR, "carebridge", "static", "images", "logo.png")
    if os.path.exists(logo_path):
        elements.append(Image(logo_path, width=18 * mm, height=18 * mm))
        elements.append(Spacer(1, 4))

    elements.append(Paragraph(title, title_style))
    elements.append(Paragraph("Smart Clinical & Healthcare Portal", subtitle_style))

    if owner_type == "patient" and patient:
        patient_name = patient.user.get_full_name() or patient.user.username
        pat_id = f"#PAT-{patient.id}"
        gender = (patient.gender or "N/A").capitalize()
        district = patient.district or "Dhaka"
        phone = patient.phone_number or "N/A"
        dob = patient.date_of_birth.strftime("%d %b %Y") if patient.date_of_birth else "N/A"

        info_data = [
            [Paragraph("<b>Patient</b>", normal_style), Paragraph(patient_name, normal_style),
             Paragraph("<b>Patient ID</b>", normal_style), Paragraph(pat_id, normal_style)],
            [Paragraph("<b>Gender</b>", normal_style), Paragraph(gender, normal_style),
             Paragraph("<b>Date of Birth</b>", normal_style), Paragraph(dob, normal_style)],
            [Paragraph("<b>District</b>", normal_style), Paragraph(district, normal_style),
             Paragraph("<b>Contact</b>", normal_style), Paragraph(phone, normal_style)],
            [Paragraph("<b>Generated</b>", normal_style), Paragraph(metrics.get("generated_on", ""), normal_style),
             Paragraph("<b>Period</b>", normal_style), Paragraph(date_range or "All time", normal_style)],
        ]
        info_table = Table(info_data, colWidths=[28 * mm, 52 * mm, 28 * mm, 52 * mm])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), light_bg),
            ('BACKGROUND', (2, 0), (2, -1), light_bg),
            ('TEXTCOLOR', (0, 0), (-1, -1), dark),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, line),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 10))
    elif owner_type == "doctor" and doctor:
        doctor_name = doctor.get_full_name()
        designation = getattr(doctor, "designation", "") or doctor.specialty or "General Specialist"
        degrees = getattr(doctor, "degrees", "") or "MBBS, MD"
        reg_number = getattr(doctor, "registration_number", "") or "A-10892"
        clinic = getattr(doctor, "clinic_name", "") or "CareBridge Digital Chamber"
        location = getattr(doctor, "location_text", "") or "Dhaka, Bangladesh"
        phone = getattr(doctor, "phone_number", "") or "+880 1700-000000"
        specialty = doctor.specialty or "General Medicine"

        info_data = [
            [Paragraph("<b>Doctor</b>", normal_style), Paragraph(doctor_name, normal_style),
             Paragraph("<b>Designation</b>", normal_style), Paragraph(designation, normal_style)],
            [Paragraph("<b>Degrees</b>", normal_style), Paragraph(degrees, normal_style),
             Paragraph("<b>Specialty</b>", normal_style), Paragraph(specialty, normal_style)],
            [Paragraph("<b>BMDC Reg</b>", normal_style), Paragraph(reg_number, normal_style),
             Paragraph("<b>Clinic</b>", normal_style), Paragraph(clinic, normal_style)],
            [Paragraph("<b>Location</b>", normal_style), Paragraph(location, normal_style),
             Paragraph("<b>Contact</b>", normal_style), Paragraph(phone, normal_style)],
            [Paragraph("<b>Generated</b>", normal_style), Paragraph(metrics.get("generated_on", ""), normal_style),
             Paragraph("<b>Period</b>", normal_style), Paragraph(date_range or "All time", normal_style)],
        ]
        info_table = Table(info_data, colWidths=[28 * mm, 52 * mm, 28 * mm, 52 * mm])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), light_bg),
            ('BACKGROUND', (2, 0), (2, -1), light_bg),
            ('TEXTCOLOR', (0, 0), (-1, -1), dark),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, line),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 10))
    else:
        # Site-wide Admin Report: clean, minimal meta header line (no mock doctor table)
        meta_text = f"<b>Generated On:</b> {metrics.get('generated_on', '')} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Report Period:</b> {date_range or 'All Time'}"
        elements.append(Paragraph(meta_text, subtitle_style))
        elements.append(Spacer(1, 10))

    if owner_type == "doctor":
        summary_data = [
            ["Metric", "Value"],
            ["Total Appointments", str(metrics["total"])],
            ["Patients Seen", str(metrics["patients_seen"])],
            ["Gross Appointment Fees (BDT)", f'{float(metrics["income_total"]):.2f}'],
            ["Your Payout (BDT)", f'{float(metrics["revenue"]):.2f}'],
            ["Refunds (BDT)", f'{float(metrics["refund_total"]):.2f}'],
            ["Cancelled Count", str(metrics["cancelled_count"])],
        ]
    else:
        net_income = float(metrics["site_charge"])
        summary_data = [
            ["Metric", "Value"],
            ["Total Appointments", str(metrics["total"])],
            ["Patients Seen", str(metrics["patients_seen"])],
            ["Gross Appointment Fees (BDT)", f'{float(metrics["income_total"]):.2f}'],
            ["Gross Site Commission (BDT)", f'{float(metrics["site_charge"]):.2f}'],
            ["Total Refunds Issued (BDT)", f'{float(metrics["refund_total"]):.2f}'],
            ["Net Site Revenue (Commission) (BDT)", f'{net_income:.2f}'],
            ["Cancelled Count", str(metrics["cancelled_count"])],
        ]
    summary_table = Table(summary_data, colWidths=[85 * mm, 65 * mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), teal),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, line),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdfa")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(Paragraph("Summary", heading_style))
    elements.append(summary_table)
    elements.append(Spacer(1, 8))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        status_counts = metrics.get("status_counts", {})
        if status_counts:
            fig, ax = plt.subplots(figsize=(5, 3))
            labels = [k for k, v in status_counts.items() if v > 0]
            sizes = [v for v in status_counts.values() if v > 0]
            colors_pie = ["#0d9488", "#e11d48", "#f97316", "#f59e0b", "#14b8a6", "#9333ea"]
            ax.pie(sizes, labels=labels, colors=colors_pie[:len(labels)], autopct="%1.0f%%", startangle=90)
            ax.set_title("Appointment Status Distribution")
            chart_buf = io.BytesIO()
            plt.tight_layout()
            plt.savefig(chart_buf, format="png", dpi=150, bbox_inches="tight")
            plt.close(fig)
            chart_buf.seek(0)
            elements.append(Paragraph("Visualizations", heading_style))
            elements.append(Image(chart_buf, width=75 * mm, height=45 * mm))
            elements.append(Spacer(1, 8))

        daily_series = metrics.get("daily_series", [])
        if daily_series:
            fig, ax = plt.subplots(figsize=(6, 3))
            dates = [item["date"] for item in daily_series]
            incomes = [float(item["income"] or 0) for item in daily_series]
            ax.bar(dates, incomes, color="#0f766e")
            ax.set_title("Daily Revenue (BDT)")
            ax.set_xlabel("Date")
            ax.set_ylabel("Revenue")
            ax.tick_params(axis="x", rotation=45)
            chart_buf2 = io.BytesIO()
            plt.tight_layout()
            plt.savefig(chart_buf2, format="png", dpi=150, bbox_inches="tight")
            plt.close(fig)
            chart_buf2.seek(0)
            elements.append(Image(chart_buf2, width=80 * mm, height=40 * mm))
            elements.append(Spacer(1, 8))
    except Exception:
        pass

    all_headers = {
        "date": "Date",
        "patient": "Patient",
        "doctor": "Doctor",
        "status": "Status",
        "payment": "Payment",
        "fee": "Fee (BDT)",
        "consultation": "Type",
    }

    if not columns:
        columns = ["date", "patient", "status", "fee", "payment"]

    detail_header = [Paragraph(f"<b>{all_headers.get(col, col)}</b>", normal_style) for col in columns]
    detail_data = [detail_header]

    col_widths = []
    width_map = {
        "date": 22 * mm,
        "patient": 34 * mm,
        "doctor": 28 * mm,
        "status": 22 * mm,
        "payment": 22 * mm,
        "fee": 18 * mm,
        "consultation": 24 * mm,
    }
    for col in columns:
        col_widths.append(width_map.get(col, 20 * mm))

    for apt in appointments.select_related("patient__user", "doctor__user").order_by("-appointment_date", "-start_time")[:200]:
        row = []
        for col in columns:
            if col == "date":
                row.append(Paragraph(apt.appointment_date.strftime("%Y-%m-%d"), normal_style))
            elif col == "patient":
                row.append(Paragraph(apt.patient.user.get_full_name() or apt.patient.user.username, normal_style))
            elif col == "doctor":
                row.append(Paragraph(apt.doctor.user.get_full_name() or apt.doctor.user.username, normal_style))
            elif col == "status":
                row.append(Paragraph(apt.get_status_display(), normal_style))
            elif col == "payment":
                row.append(Paragraph(apt.get_payment_status_display(), normal_style))
            elif col == "fee":
                row.append(Paragraph(f'{apt.fee_bdt:.2f}', normal_style))
            elif col == "consultation":
                row.append(Paragraph(apt.get_consultation_type_display(), normal_style))
            else:
                row.append(Paragraph("", normal_style))
        detail_data.append(row)

    detail_table = Table(detail_data, colWidths=col_widths, repeatRows=1)
    detail_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), teal),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, line),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdfa")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(Paragraph("Appointment Details", heading_style))
    elements.append(detail_table)

    elements.append(Spacer(1, 12))
    elements.append(Table([['']], colWidths=[150 * mm], rowHeights=[1], style=TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 1, line),
    ])))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(f"Generated by CareBridge AI Clinical Network on {metrics.get('generated_on', '')}", footer_style))
    elements.append(Paragraph("Confidential — For authorized medical use only", footer_style))

    doc.build(elements)
    return response


def export_overall_health_report_pdf(patient, metrics, appointments, prescriptions, vitals, filename="overall_health_report.pdf", ai_summary="", medical_history=None):
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    doc = SimpleDocTemplate(response, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm, leftMargin=18 * mm, rightMargin=18 * mm)
    styles = getSampleStyleSheet()

    teal = colors.HexColor("#0f766e")
    dark = colors.HexColor("#1c1917")
    slate = colors.HexColor("#57534e")
    light_bg = colors.HexColor("#f0fdfa")
    line = colors.HexColor("#e7e5e4")

    title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=18, textColor=teal, spaceAfter=2, leading=22)
    subtitle_style = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=10, textColor=slate, spaceAfter=10, leading=14)
    heading_style = ParagraphStyle("heading", parent=styles["Heading3"], fontSize=11, textColor=teal, spaceAfter=4, spaceBefore=10, leading=14)
    normal_style = ParagraphStyle("normal", parent=styles["Normal"], fontSize=9, leading=12, textColor=dark)
    footer_style = ParagraphStyle("footer", parent=styles["Normal"], fontSize=8, textColor=slate, alignment=1, leading=10)

    elements = []

    logo_path = os.path.join(settings.BASE_DIR, "carebridge", "static", "images", "logo.png")
    if os.path.exists(logo_path):
        elements.append(Image(logo_path, width=18 * mm, height=18 * mm))
        elements.append(Spacer(1, 4))

    patient_name = patient.user.get_full_name() or patient.user.username
    elements.append(Paragraph(f"Overall Health Report — {patient_name}", title_style))
    elements.append(Paragraph("CareBridge AI Patient Comprehensive Health Summary", subtitle_style))

    pat_id = f"#PAT-{patient.id}"
    gender = (patient.gender or "N/A").capitalize()
    district = patient.district or "Dhaka"
    phone = patient.phone_number or "N/A"
    dob = patient.date_of_birth.strftime("%d %b %Y") if patient.date_of_birth else "N/A"

    info_data = [
        [Paragraph("<b>Patient</b>", normal_style), Paragraph(patient_name, normal_style),
         Paragraph("<b>Patient ID</b>", normal_style), Paragraph(pat_id, normal_style)],
        [Paragraph("<b>Gender</b>", normal_style), Paragraph(gender, normal_style),
         Paragraph("<b>Date of Birth</b>", normal_style), Paragraph(dob, normal_style)],
        [Paragraph("<b>District</b>", normal_style), Paragraph(district, normal_style),
         Paragraph("<b>Contact</b>", normal_style), Paragraph(phone, normal_style)],
        [Paragraph("<b>Generated On</b>", normal_style), Paragraph(metrics.get("generated_on", ""), normal_style),
         Paragraph("<b>Adherence Score</b>", normal_style), Paragraph(f"{metrics.get('adherence_pct', 0)}%", normal_style)],
    ]
    info_table = Table(info_data, colWidths=[28 * mm, 52 * mm, 28 * mm, 52 * mm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), light_bg),
        ('BACKGROUND', (2, 0), (2, -1), light_bg),
        ('TEXTCOLOR', (0, 0), (-1, -1), dark),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, line),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 10))

    # Summary Metrics Table
    summary_data = [
        ["Metric", "Value"],
        ["Total Consultations Booked", str(metrics.get("total_appointments", 0))],
        ["Completed Consultations", str(metrics.get("completed_appointments", 0))],
        ["Prescriptions Issued", str(metrics.get("total_prescriptions", 0))],
        ["Active Prescriptions", str(metrics.get("active_prescriptions", 0))],
        ["Total Scheduled Doses", str(metrics.get("total_doses", 0))],
        ["Doses Taken (Adherence Rate)", f"{metrics.get('taken_doses', 0)} ({metrics.get('adherence_pct', 0)}%)"],
    ]
    summary_table = Table(summary_data, colWidths=[85 * mm, 65 * mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), teal),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, line),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdfa")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(Paragraph("Health Metrics Overview", heading_style))
    elements.append(summary_table)
    elements.append(Spacer(1, 10))

    # Recent Appointments Section
    elements.append(Paragraph("Recent Consultation History", heading_style))
    apt_header = [Paragraph("<b>Date</b>", normal_style), Paragraph("<b>Doctor</b>", normal_style), Paragraph("<b>Type</b>", normal_style), Paragraph("<b>Status</b>", normal_style)]
    apt_rows = [apt_header]
    for apt in appointments[:15]:
        doc_name = f"Dr. {apt.doctor.user.get_full_name() or apt.doctor.user.username}"
        apt_rows.append([
            Paragraph(apt.appointment_date.strftime("%Y-%m-%d"), normal_style),
            Paragraph(doc_name, normal_style),
            Paragraph(apt.get_consultation_type_display(), normal_style),
            Paragraph(apt.get_status_display(), normal_style),
        ])
    if len(apt_rows) > 1:
        apt_table = Table(apt_rows, colWidths=[30 * mm, 60 * mm, 35 * mm, 25 * mm])
        apt_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), teal),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, line),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdfa")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(apt_table)
    else:
        elements.append(Paragraph("No consultation records found.", normal_style))
    elements.append(Spacer(1, 10))

    # Prescriptions Section
    elements.append(Paragraph("Prescription Records", heading_style))
    rx_header = [Paragraph("<b>Date Issued</b>", normal_style), Paragraph("<b>Doctor</b>", normal_style), Paragraph("<b>Diagnosis</b>", normal_style), Paragraph("<b>Status</b>", normal_style)]
    rx_rows = [rx_header]
    for rx in prescriptions[:15]:
        doc_name = f"Dr. {rx.doctor.user.get_full_name() or rx.doctor.user.username}"
        rx_rows.append([
            Paragraph(rx.issued_at.strftime("%Y-%m-%d"), normal_style),
            Paragraph(doc_name, normal_style),
            Paragraph(rx.diagnosis or "N/A", normal_style),
            Paragraph(rx.get_status_display(), normal_style),
        ])
    if len(rx_rows) > 1:
        rx_table = Table(rx_rows, colWidths=[30 * mm, 60 * mm, 35 * mm, 25 * mm])
        rx_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), teal),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, line),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdfa")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(rx_table)
    else:
        elements.append(Paragraph("No prescriptions logged.", normal_style))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph(f"Generated by CareBridge AI Clinical Network on {metrics.get('generated_on', '')}", footer_style))
    doc.build(elements)
    return response


def export_dose_report_pdf(patient, metrics, doses, filename="dose_tracking_report.pdf"):
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    doc = SimpleDocTemplate(response, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm, leftMargin=18 * mm, rightMargin=18 * mm)
    styles = getSampleStyleSheet()

    teal = colors.HexColor("#0f766e")
    dark = colors.HexColor("#1c1917")
    slate = colors.HexColor("#57534e")
    light_bg = colors.HexColor("#f0fdfa")
    line = colors.HexColor("#e7e5e4")

    title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=18, textColor=teal, spaceAfter=2, leading=22)
    subtitle_style = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=10, textColor=slate, spaceAfter=10, leading=14)
    heading_style = ParagraphStyle("heading", parent=styles["Heading3"], fontSize=11, textColor=teal, spaceAfter=4, spaceBefore=10, leading=14)
    normal_style = ParagraphStyle("normal", parent=styles["Normal"], fontSize=9, leading=12, textColor=dark)
    footer_style = ParagraphStyle("footer", parent=styles["Normal"], fontSize=8, textColor=slate, alignment=1, leading=10)

    elements = []

    logo_path = os.path.join(settings.BASE_DIR, "carebridge", "static", "images", "logo.png")
    if os.path.exists(logo_path):
        elements.append(Image(logo_path, width=18 * mm, height=18 * mm))
        elements.append(Spacer(1, 4))

    patient_name = patient.user.get_full_name() or patient.user.username
    elements.append(Paragraph(f"Medication Dose Tracking Report — {patient_name}", title_style))
    elements.append(Paragraph("CareBridge AI Adherence Log", subtitle_style))

    pat_id = f"#PAT-{patient.id}"
    gender = (patient.gender or "N/A").capitalize()
    district = patient.district or "Dhaka"

    info_data = [
        [Paragraph("<b>Patient</b>", normal_style), Paragraph(patient_name, normal_style),
         Paragraph("<b>Patient ID</b>", normal_style), Paragraph(pat_id, normal_style)],
        [Paragraph("<b>Gender</b>", normal_style), Paragraph(gender, normal_style),
         Paragraph("<b>District</b>", normal_style), Paragraph(district, normal_style)],
        [Paragraph("<b>Generated On</b>", normal_style), Paragraph(metrics.get("generated_on", ""), normal_style),
         Paragraph("<b>Adherence Rate</b>", normal_style), Paragraph(f"<b>{metrics.get('rate', metrics.get('adherence_rate', 0))}%</b>", normal_style)],
    ]
    info_table = Table(info_data, colWidths=[28 * mm, 52 * mm, 28 * mm, 52 * mm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), light_bg),
        ('BACKGROUND', (2, 0), (2, -1), light_bg),
        ('TEXTCOLOR', (0, 0), (-1, -1), dark),
        ('GRID', (0, 0), (-1, -1), 0.5, line),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 10))

    # Metrics Overview Table
    metrics_data = [
        ["Total Scheduled Doses", "Taken Doses", "Skipped Doses", "Missed Doses", "Adherence Rate"],
        [str(metrics.get("total", 0)), str(metrics.get("taken", 0)), str(metrics.get("skipped", 0)), str(metrics.get("missed", 0)), f"{metrics.get('rate', 0)}%"],
    ]
    metrics_table = Table(metrics_data, colWidths=[32 * mm, 28 * mm, 28 * mm, 28 * mm, 34 * mm])
    metrics_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), teal),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, line),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(Paragraph("Adherence Overview", heading_style))
    elements.append(metrics_table)
    elements.append(Spacer(1, 10))

    # Dose Logs Table
    elements.append(Paragraph("Dose Log Details", heading_style))
    log_header = [
        Paragraph("<b>Date</b>", normal_style),
        Paragraph("<b>Time</b>", normal_style),
        Paragraph("<b>Medicine</b>", normal_style),
        Paragraph("<b>Status</b>", normal_style),
    ]
    log_rows = [log_header]
    for d in doses[:100]:
        med_name = str(d.prescription_item.medicine) if (d.prescription_item and d.prescription_item.medicine) else "Medication"
        time_str = d.reminder_time[:5] if isinstance(d.reminder_time, str) else (d.reminder_time.strftime("%H:%M") if d.reminder_time else "09:00")
        log_rows.append([
            Paragraph(d.scheduled_date.strftime("%Y-%m-%d"), normal_style),
            Paragraph(time_str, normal_style),
            Paragraph(med_name, normal_style),
            Paragraph(d.get_status_display(), normal_style),
        ])
    if len(log_rows) > 1:
        log_table = Table(log_rows, colWidths=[28 * mm, 22 * mm, 70 * mm, 30 * mm], repeatRows=1)
        log_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), teal),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, line),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdfa")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(log_table)
    else:
        elements.append(Paragraph("No dose records logged.", normal_style))

    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"Generated by CareBridge AI Clinical Network on {metrics.get('generated_on', '')}", footer_style))
    doc.build(elements)
    return response
