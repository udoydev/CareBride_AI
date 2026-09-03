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


def export_report_pdf(appointments, metrics, title, filename, columns=None, doctor=None, start_date=None, end_date=None, owner_type="generic"):
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

    logo_path = os.path.join(settings.BASE_DIR, "carebridge", "static", "images", "logo.png")
    if os.path.exists(logo_path):
        elements.append(Image(logo_path, width=18 * mm, height=18 * mm))
        elements.append(Spacer(1, 4))

    elements.append(Paragraph(title, title_style))
    elements.append(Paragraph("Smart Clinical & Healthcare Portal", subtitle_style))

    if owner_type == "doctor" and doctor:
        doctor_name = doctor.user.get_full_name() or doctor.user.username
        designation = getattr(doctor, "designation", "") or doctor.specialty or "General Specialist"
        degrees = getattr(doctor, "degrees", "") or "MBBS, MD"
        reg_number = getattr(doctor, "registration_number", "") or "A-10892"
        clinic = getattr(doctor, "clinic_name", "") or "CareBridge Digital Chamber"
        location = getattr(doctor, "location_text", "") or "Dhaka, Bangladesh"
        phone = getattr(doctor, "phone_number", "") or "+880 1700-000000"
        specialty = doctor.specialty or "General Medicine"
        bio = getattr(doctor, "bio", "") or "Consultant Physician & Specialist"
    elif owner_type == "patient":
        doctor_name = "CareBridge Doctor"
        designation = "General Specialist"
        degrees = "MBBS, MD"
        reg_number = "A-10892"
        clinic = "CareBridge Digital Chamber"
        location = "Dhaka, Bangladesh"
        phone = "+880 1700-000000"
        specialty = "General Medicine"
        bio = "Consultant Physician & Specialist"
    else:
        doctor_name = "CareBridge Doctor"
        designation = "General Specialist"
        degrees = "MBBS, MD"
        reg_number = "A-10892"
        clinic = "CareBridge Digital Chamber"
        location = "Dhaka, Bangladesh"
        phone = "+880 1700-000000"
        specialty = "General Medicine"
        bio = "Consultant Physician & Specialist"

    date_range = ""
    if start_date and end_date:
        date_range = f"{start_date} to {end_date}"
    elif start_date:
        date_range = f"From {start_date}"
    elif end_date:
        date_range = f"Until {end_date}"

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
        summary_data = [
            ["Metric", "Value"],
            ["Total Appointments", str(metrics["total"])],
            ["Patients Seen", str(metrics["patients_seen"])],
            ["Gross Appointment Fees (BDT)", f'{float(metrics["income_total"]):.2f}'],
            ["Site Commission (BDT)", f'{float(metrics["site_charge"]):.2f}'],
            ["Total Refunds (BDT)", f'{float(metrics["refund_total"]):.2f}'],
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
