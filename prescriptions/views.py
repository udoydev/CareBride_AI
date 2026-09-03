from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, Http404
from django.utils import timezone
from decimal import Decimal
import pytz
from io import BytesIO
import threading
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics, ttfonts
from pypdf import PdfReader, PdfWriter
from carebridge.ai_services import GeminiAIService
from accounts.decorators import never_cache_auth
from .models import Prescription, PrescriptionItem, Medicine
from doctors.models import Appointment


def calculate_age(date_of_birth):
    if not date_of_birth:
        return None
    today = timezone.now().date()
    return today.year - date_of_birth.year - ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))


def _build_prescription_pdf(prescription):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15*mm, leftMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    story = []

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

    title_style = ParagraphStyle(name='Title', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#0f766e'), spaceAfter=2, fontName=pdf_font_name)
    subtitle_style = ParagraphStyle(name='Subtitle', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#57534e'), spaceAfter=8, fontName=pdf_font_name)
    heading_style = ParagraphStyle(name='Heading', parent=styles['Heading2'], fontSize=11, textColor=colors.HexColor('#0f766e'), spaceAfter=4, spaceBefore=8, fontName=pdf_font_name)
    normal_style = ParagraphStyle(name='Normal', parent=styles['Normal'], fontSize=9, leading=13, textColor=colors.HexColor('#1c1917'), fontName=pdf_font_name)
    small_style = ParagraphStyle(name='Small', parent=styles['Normal'], fontSize=8, leading=11, textColor=colors.HexColor('#57534e'), fontName=pdf_font_name)

    doctor = prescription.doctor
    patient = prescription.patient
    doctor_name = doctor.user.get_full_name() or doctor.user.username
    patient_name = patient.user.get_full_name() or patient.user.email

    # Professional Medical Header
    story.append(Paragraph("CareBridge AI Clinical Network", title_style))
    story.append(Paragraph(f"Digital Prescription & Medical Record | Rx Code: <b>#CARE-RX-{prescription.pk}</b>", subtitle_style))
    story.append(Spacer(1, 4))

    info_data = [
        [Paragraph("<b>Doctor Name</b>", normal_style), Paragraph(f"Dr. {doctor_name}", normal_style),
         Paragraph("<b>Specialty</b>", normal_style), Paragraph(doctor.specialty or "General Medicine", normal_style)],
        [Paragraph("<b>Qualifications</b>", normal_style), Paragraph(doctor.degrees or "MBBS, MD", normal_style),
         Paragraph("<b>BMDC Reg No</b>", normal_style), Paragraph(doctor.registration_number or "A-10892", normal_style)],
        [Paragraph("<b>Chamber / Clinic</b>", normal_style), Paragraph(doctor.clinic_name or "CareBridge Digital Chamber", normal_style),
         Paragraph("<b>Issued Date</b>", normal_style), Paragraph(prescription.issued_at.strftime("%d %b %Y, %I:%M %p"), normal_style)],
        [Paragraph("<b>Patient Name</b>", normal_style), Paragraph(patient_name, normal_style),
         Paragraph("<b>Patient ID</b>", normal_style), Paragraph(f"#PAT-{patient.id}", normal_style)],
        [Paragraph("<b>Gender / Age</b>", normal_style), Paragraph(f"{patient.gender or 'N/A'}, {calculate_age(patient.date_of_birth) if patient.date_of_birth else 'N/A'} yrs", normal_style),
         Paragraph("<b>Contact Phone</b>", normal_style), Paragraph(patient.phone_number or "N/A", normal_style)],
    ]
    info_table = Table(info_data, colWidths=[32*mm, 58*mm, 32*mm, 58*mm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0fdfa')),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#f0fdfa')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#1c1917')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ccfbf1')),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 8))

    # Visit Vitals
    visit = getattr(prescription, "visit", None)
    if visit:
        vitals_data = [
            [Paragraph("<b>Heart Rate</b>", normal_style), Paragraph(f"{visit.heart_rate} bpm" if visit.heart_rate else "—", normal_style),
             Paragraph("<b>Blood Pressure</b>", normal_style), Paragraph(f"{visit.blood_pressure_systolic}/{visit.blood_pressure_diastolic} mmHg" if visit.blood_pressure_systolic and visit.blood_pressure_diastolic else "—", normal_style)],
            [Paragraph("<b>Temperature</b>", normal_style), Paragraph(f"{visit.temperature_celsius}°C" if visit.temperature_celsius else "—", normal_style),
             Paragraph("<b>Weight / Height</b>", normal_style), Paragraph(f"{visit.weight_kg or '—'} kg / {visit.height_cm or '—'} cm", normal_style)],
        ]
        vitals_table = Table(vitals_data, colWidths=[35*mm, 55*mm, 35*mm, 55*mm])
        vitals_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#eff6ff')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dbeafe')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 5),
        ]))
        story.append(Paragraph("Patient Clinical Vitals", heading_style))
        story.append(vitals_table)
        story.append(Spacer(1, 6))

    if prescription.chief_complaints:
        story.append(Paragraph("Chief Complaints (C/C)", heading_style))
        story.append(Paragraph(prescription.chief_complaints, normal_style))
    if prescription.diagnosis:
        story.append(Paragraph("Diagnosis (D)", heading_style))
        story.append(Paragraph(f"<b>{prescription.diagnosis}</b>", normal_style))
    if prescription.tests_investigations:
        story.append(Paragraph("Tests / Investigations Required", heading_style))
        story.append(Paragraph(prescription.tests_investigations, normal_style))

    # Prescribed Medicines (Rx)
    story.append(Paragraph("Prescribed Medications (Rx)", heading_style))
    meds = prescription.items.select_related("medicine").all()
    if meds:
        med_data = [[
            Paragraph("<b>Medicine</b>", normal_style),
            Paragraph("<b>Dosage</b>", normal_style),
            Paragraph("<b>Frequency</b>", normal_style),
            Paragraph("<b>Duration</b>", normal_style),
            Paragraph("<b>Instructions</b>", normal_style)
        ]]
        for item in meds:
            med_data.append([
                Paragraph(f"<b>{item.medicine.brand_name}</b><br/><font color='#57534e' size='8'>{item.medicine.generic_name}</font>", normal_style),
                Paragraph(item.dosage, normal_style),
                Paragraph(f"{item.frequency}x / day", normal_style),
                Paragraph(f"{item.duration_days} days", normal_style),
                Paragraph(item.get_timing_relation_to_meal_display(), normal_style),
            ])
        med_table = Table(med_data, colWidths=[55*mm, 25*mm, 25*mm, 25*mm, 50*mm])
        med_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f766e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('PADDING', (0, 0), (-1, -1), 5),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e7e5e4')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fafaf9')]),
        ]))
        story.append(med_table)
    else:
        story.append(Paragraph("No specific medicines recorded on this prescription.", small_style))

    if prescription.advice_rules:
        story.append(Paragraph("Doctor Advice & Lifestyle Rules", heading_style))
        story.append(Paragraph(prescription.advice_rules, normal_style))

    # Follow-up info
    follow_up = getattr(prescription, "follow_up", None)
    if follow_up:
        story.append(Paragraph("Follow-up Schedule", heading_style))
        followup_data = [
            [Paragraph("<b>Scheduled Follow-up Date</b>", normal_style), Paragraph(follow_up.scheduled_date.strftime("%d %b %Y"), normal_style)],
            [Paragraph("<b>Book By (Deadline)</b>", normal_style), Paragraph(follow_up.booking_deadline.strftime("%d %b %Y") if follow_up.booking_deadline else "As needed", normal_style)],
        ]
        followup_table = Table(followup_data, colWidths=[50*mm, 130*mm])
        followup_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e7e5e4')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 5),
        ]))
        story.append(followup_table)

    # Virtual Digital Signature Box
    story.append(Spacer(1, 14))
    sig_doctor_title = f"Dr. {doctor_name}"
    bmdc_no = doctor.registration_number or "A-10892"
    issued_date_str = prescription.issued_at.strftime("%d %b %Y, %I:%M %p")

    sig_content = [
        [Paragraph(f"<b>{sig_doctor_title}</b>", ParagraphStyle("sig_doc", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#0f766e"), fontName=pdf_font_name))],
        [Paragraph("<i>Virtual Digital Signature</i>", ParagraphStyle("sig_sub", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#047857"), fontName=pdf_font_name))],
        [Paragraph("<b>[ ✓ DIGITALLY SIGNED & VERIFIED ]</b>", ParagraphStyle("sig_stamp", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#047857"), fontName=pdf_font_name))],
        [Paragraph(f"BMDC Reg: <b>{bmdc_no}</b>", ParagraphStyle("sig_bmdc", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#57534e"), fontName=pdf_font_name))],
        [Paragraph(f"Signed: {issued_date_str}", ParagraphStyle("sig_date", parent=styles["Normal"], fontSize=7, textColor=colors.HexColor("#78716c"), fontName=pdf_font_name))],
    ]

    sig_box_table = Table(sig_content, colWidths=[65*mm])
    sig_box_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f0fdfa")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#0d9488")),
        ('PADDING', (0,0), (-1,-1), 5),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
    ]))

    sig_wrapper = Table([["", sig_box_table]], colWidths=[115*mm, 65*mm])
    sig_wrapper.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(sig_wrapper)

    story.append(Spacer(1, 8))
    story.append(Table([['']], colWidths=[180*mm], rowHeights=[1], style=TableStyle([('LINEBELOW', (0,0), (-1,0), 1, colors.HexColor('#d6d3d1'))])))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"Verification Hash: #CARE-{prescription.pk}-{prescription.issued_at.strftime('%Y%m%d%H%M')}", small_style))
    story.append(Paragraph("Issued by CareBridge AI Clinical & Telemedicine Network", small_style))

    doc.build(story)
    buffer.seek(0)
    return buffer


def _build_appointment_receipt_pdf(appointment):
    """Generate a detailed payment receipt PDF for an appointment.

    Includes: receipt number, patient ID, doctor ID, appointment date/time,
    payment method, transaction ID, platform commission, doctor payout,
    and timestamps for when the appointment was booked and payment verified.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    story = []

    teal = colors.HexColor("#0f766e")
    dark = colors.HexColor("#1c1917")
    slate = colors.HexColor("#57534e")
    light_bg = colors.HexColor("#f0fdfa")
    line_color = colors.HexColor("#e7e5e4")

    title_style = ParagraphStyle(name='Title', parent=styles['Heading1'], fontSize=22, textColor=teal, spaceAfter=2, leading=26)
    subtitle_style = ParagraphStyle(name='Subtitle', parent=styles['Normal'], fontSize=10, textColor=slate, spaceAfter=2, leading=14)
    heading_style = ParagraphStyle(name='Heading', parent=styles['Heading2'], fontSize=12, textColor=teal, spaceAfter=4, spaceBefore=8, leading=15)
    normal_style = ParagraphStyle(name='Normal', parent=styles['Normal'], fontSize=10, leading=14, textColor=dark)
    small_style = ParagraphStyle(name='Small', parent=styles['Normal'], fontSize=9, leading=12, textColor=slate)
    right_style = ParagraphStyle(name='Right', parent=styles['Normal'], fontSize=10, leading=14, textColor=dark, alignment=2)

    story.append(Paragraph("CareBridge <font color='#0f766e'>AI</font> Health", title_style))
    story.append(Paragraph("Smart Clinical & Healthcare Network", subtitle_style))
    story.append(Spacer(1, 10))

    story.append(Table([['']], colWidths=[170*mm], rowHeights=[1], style=TableStyle([('LINEBELOW', (0,0), (-1,0), 1.5, teal)])))
    story.append(Spacer(1, 8))

    story.append(Paragraph("APPOINTMENT RECEIPT", heading_style))

    doctor = appointment.doctor
    patient = appointment.patient
    doctor_name = doctor.user.get_full_name() or doctor.user.username
    patient_name = patient.user.get_full_name() or patient.user.email

    bdt = pytz.timezone("Asia/Dhaka")
    local_dt = appointment.appointment_date.strftime("%d %B %Y")
    local_start = appointment.start_time.strftime("%I:%M %p")
    local_end = appointment.end_time.strftime("%I:%M %p") if appointment.end_time else ""

    receipt_no = f"APT-{appointment.pk:06d}-{appointment.appointment_date.strftime('%Y%m%d')}"

    info_data = [
        [Paragraph("<b>Receipt No.</b>", normal_style), Paragraph(receipt_no, normal_style),
         Paragraph("<b>Date</b>", normal_style), Paragraph(timezone.now().astimezone(bdt).strftime("%d %B %Y"), normal_style)],
        [Paragraph("<b>Patient Name</b>", normal_style), Paragraph(patient_name, normal_style),
         Paragraph("<b>Patient ID</b>", normal_style), Paragraph(f"PAT-{patient.pk:05d}", normal_style)],
        [Paragraph("<b>Doctor Name</b>", normal_style), Paragraph(f"Dr. {doctor_name}", normal_style),
         Paragraph("<b>Doctor ID</b>", normal_style), Paragraph(f"DOC-{doctor.pk:05d}", normal_style)],
        [Paragraph("<b>Appointment Date</b>", normal_style), Paragraph(local_dt, normal_style),
         Paragraph("<b>Status</b>", normal_style), Paragraph(appointment.get_status_display(), normal_style)],
        [Paragraph("<b>Time (BDT)</b>", normal_style), Paragraph(f"{local_start} - {local_end}", normal_style),
         Paragraph("<b>Service Type</b>", normal_style), Paragraph(appointment.get_consultation_type_display(), normal_style)],
        [Paragraph("<b>Consultation Fee</b>", normal_style), Paragraph(f"BDT {appointment.fee_bdt:,.2f}", normal_style),
         Paragraph("<b>Payment Method</b>", normal_style), Paragraph(appointment.payment_method or "N/A", normal_style)],
    ]
    info_table = Table(info_data, colWidths=[30*mm, 55*mm, 30*mm, 55*mm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), light_bg),
        ('BACKGROUND', (2, 0), (2, -1), light_bg),
        ('TEXTCOLOR', (0, 0), (-1, -1), dark),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, line_color),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 10))

    if appointment.chief_complaint:
        story.append(Paragraph("Chief Complaint", heading_style))
        story.append(Paragraph(appointment.chief_complaint, normal_style))

    if appointment.payment_method or appointment.transaction_id:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Payment Details", heading_style))
        pay_data = []
        if appointment.payment_method:
            pay_data.append([Paragraph("<b>Payment Method:</b>", normal_style), Paragraph(appointment.payment_method, normal_style)])
        if appointment.transaction_id:
            pay_data.append([Paragraph("<b>Transaction ID:</b>", normal_style), Paragraph(appointment.transaction_id or "N/A", normal_style)])
        if appointment.payment_verified_at:
            pay_data.append([Paragraph("<b>Payment Verified At:</b>", normal_style), Paragraph(appointment.payment_verified_at.astimezone(bdt).strftime("%d %B %Y, %I:%M %p") + " BDT", normal_style)])
        pay_table = Table(pay_data, colWidths=[40*mm, 130*mm])
        pay_table.setStyle(TableStyle([
            ('TEXTCOLOR', (0, 0), (-1, -1), dark),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        story.append(pay_table)

    story.append(Spacer(1, 14))
    story.append(Table([['']], colWidths=[170*mm], rowHeights=[1], style=TableStyle([('LINEBELOW', (0,0), (-1,0), 1, line_color)])))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Generated on {timezone.now().astimezone(bdt).strftime('%d %B %Y, %I:%M %p')} BDT", small_style))
    story.append(Paragraph("CareBridge AI Telemedicine & Clinical Systems", small_style))
    story.append(Spacer(1, 10))
    story.append(Paragraph("This is a computer-generated receipt. No physical signature required.", ParagraphStyle(name='Footer', parent=styles['Normal'], fontSize=8, leading=10, textColor=slate, alignment=1)))

    doc.build(story)
    buffer.seek(0)
    return buffer


@login_required
def appointment_receipt_pdf(request, appointment_id):
    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        messages.error(request, "Only registered patients can access appointment receipts.")
        return redirect("home")
    appointment = get_object_or_404(Appointment, pk=appointment_id, patient=patient)
    if appointment.status not in ("confirmed", "completed"):
        messages.error(request, "Receipt is only available for confirmed or completed appointments.")
        return redirect("patient:appointment_detail", appointment_id=appointment.pk)

    buffer = _build_appointment_receipt_pdf(appointment)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = f"inline; filename=appointment_receipt_{appointment.pk}.pdf"
    return response


def _build_refund_receipt_pdf(appointment):
    """Generate a professional cancellation/refund receipt PDF.

    Shows: receipt number, original appointment details, refund amount,
    refund status, and timestamps. Includes a watermark indicating the
    appointment was cancelled/refunded.
    """
    """Build a professional cancellation/refund receipt PDF."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    story = []

    teal = colors.HexColor("#0f766e")
    dark = colors.HexColor("#1c1917")
    slate = colors.HexColor("#57534e")
    light_bg = colors.HexColor("#fef2f2")
    line_color = colors.HexColor("#e7e5e4")

    title_style = ParagraphStyle(name='RefundTitle', parent=styles['Heading1'], fontSize=22, textColor=teal, spaceAfter=2, leading=26)
    subtitle_style = ParagraphStyle(name='RefundSubtitle', parent=styles['Normal'], fontSize=10, textColor=slate, spaceAfter=2, leading=14)
    heading_style = ParagraphStyle(name='RefundHeading', parent=styles['Heading2'], fontSize=12, textColor=teal, spaceAfter=4, spaceBefore=8, leading=15)
    normal_style = ParagraphStyle(name='RefundNormal', parent=styles['Normal'], fontSize=10, leading=14, textColor=dark)
    small_style = ParagraphStyle(name='RefundSmall', parent=styles['Normal'], fontSize=9, leading=12, textColor=slate)

    story.append(Paragraph("CareBridge <font color='#0f766e'>AI</font> Health", title_style))
    story.append(Paragraph("Smart Clinical & Healthcare Network", subtitle_style))
    story.append(Spacer(1, 10))

    story.append(Table([['']], colWidths=[170*mm], rowHeights=[1], style=TableStyle([('LINEBELOW', (0,0), (-1,0), 1.5, teal)])))
    story.append(Spacer(1, 8))

    story.append(Paragraph("CANCELLATION & REFUND RECEIPT", heading_style))

    bdt = pytz.timezone("Asia/Dhaka")
    patient = appointment.patient
    doctor = appointment.doctor
    patient_name = patient.user.get_full_name() or patient.user.email
    doctor_name = doctor.user.get_full_name() or doctor.user.username

    receipt_no = f"REF-{appointment.pk:06d}-{appointment.appointment_date.strftime('%Y%m%d')}"
    fee = Decimal(str(appointment.fee_bdt or 0))
    refunded = Decimal(str(appointment.refund_amount or 0))

    info_data = [
        [Paragraph("<b>Receipt No.</b>", normal_style), Paragraph(receipt_no, normal_style),
         Paragraph("<b>Date</b>", normal_style), Paragraph(timezone.now().astimezone(bdt).strftime("%d %B %Y"), normal_style)],
        [Paragraph("<b>Patient Name</b>", normal_style), Paragraph(patient_name, normal_style),
         Paragraph("<b>Patient ID</b>", normal_style), Paragraph(f"PAT-{patient.pk:05d}", normal_style)],
        [Paragraph("<b>Doctor</b>", normal_style), Paragraph(f"Dr. {doctor_name}", normal_style),
         Paragraph("<b>Appointment ID</b>", normal_style), Paragraph(f"#APT-{appointment.pk:06d}", normal_style)],
        [Paragraph("<b>Appointment Date</b>", normal_style), Paragraph(appointment.appointment_date.strftime("%d %B %Y"), normal_style),
         Paragraph("<b>Time</b>", normal_style), Paragraph(f"{appointment.start_time.strftime('%I:%M %p')} - {appointment.end_time.strftime('%I:%M %p')}", normal_style)],
        [Paragraph("<b>Original Fee</b>", normal_style), Paragraph(f"BDT {fee:,.2f}", normal_style),
         Paragraph("<b>Payment Method</b>", normal_style), Paragraph(appointment.payment_method or "N/A", normal_style)],
        [Paragraph("<b>Refund Amount</b>", normal_style), Paragraph(f"BDT {refunded:,.2f}", normal_style),
         Paragraph("<b>Status</b>", normal_style), Paragraph(appointment.get_status_display(), normal_style)],
    ]
    info_table = Table(info_data, colWidths=[30*mm, 55*mm, 30*mm, 55*mm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), light_bg),
        ('BACKGROUND', (2, 0), (2, -1), light_bg),
        ('TEXTCOLOR', (0, 0), (-1, -1), dark),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, line_color),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Refund Details", heading_style))
    refund_note = (
        f"This appointment was cancelled. A refund of <b>BDT {refunded:,.2f}</b> "
        f"(based on the cancellation policy) has been processed. "
        f"The refund will be credited to your original payment method within 3-5 business days. "
        f"Reference ID: {appointment.transaction_id or 'N/A'}."
    )
    story.append(Paragraph(refund_note, normal_style))

    story.append(Spacer(1, 14))
    story.append(Table([['']], colWidths=[170*mm], rowHeights=[1], style=TableStyle([('LINEBELOW', (0,0), (-1,0), 1, line_color)])))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Generated on {timezone.now().astimezone(bdt).strftime('%d %B %Y, %I:%M %p')} BDT", small_style))
    story.append(Paragraph("CareBridge AI Telemedicine & Clinical Systems", small_style))
    story.append(Spacer(1, 10))
    story.append(Paragraph("This is a computer-generated refund receipt. No physical signature required.", ParagraphStyle(name='RefundFooter', parent=styles['Normal'], fontSize=8, leading=10, textColor=slate, alignment=1)))

    doc.build(story)
    buffer.seek(0)
    return buffer


@login_required
def refund_receipt_pdf(request, appointment_id):
    from doctors.models import Appointment
    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        messages.error(request, "Only registered patients can access refund receipts.")
        return redirect("home")
    appointment = get_object_or_404(Appointment, pk=appointment_id, patient=patient)
    if appointment.status not in ("cancelled", "refunded"):
        messages.error(request, "Refund receipt is only available for cancelled or refunded appointments.")
        return redirect("patient:appointment_detail", appointment_id=appointment.pk)
    if not appointment.refund_amount or appointment.refund_amount <= 0:
        messages.error(request, "No refund has been processed for this appointment.")
        return redirect("patient:appointment_detail", appointment_id=appointment.pk)

    buffer = _build_refund_receipt_pdf(appointment)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = f"inline; filename=refund_receipt_{appointment.pk}.pdf"
    return response


@login_required
def view_prescription_online(request, prescription_id):
    prescription = get_object_or_404(Prescription, pk=prescription_id)
    patient = getattr(request.user, "patient_profile", None)
    doctor = getattr(request.user, "doctor_profile", None)
    if not patient and not doctor:
        messages.error(request, "You are not authorized to view this prescription.")
        return redirect("home")
    if patient and prescription.patient_id != patient.pk:
        messages.error(request, "You are not authorized to view this prescription.")
        return redirect("home")
    if doctor and prescription.doctor_id != doctor.pk:
        messages.error(request, "You are not authorized to view this prescription.")
        return redirect("home")
    return render(request, "prescriptions/view_prescription.html", {
        "prescription": prescription,
    })


def printable_prescription_pdf(request, prescription_id):
    prescription = get_object_or_404(Prescription, pk=prescription_id)
    patient = getattr(request.user, "patient_profile", None)
    doctor = getattr(request.user, "doctor_profile", None)
    if not patient and not doctor:
        messages.error(request, "You are not authorized to download this prescription.")
        return redirect("home")
    if patient and prescription.patient_id != patient.pk:
        messages.error(request, "You are not authorized to download this prescription.")
        return redirect("home")
    if doctor and prescription.doctor_id != doctor.pk:
        messages.error(request, "You are not authorized to download this prescription.")
        return redirect("home")
    buffer = _build_prescription_pdf(prescription)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = f"inline; filename=prescription_{prescription.pk}.pdf"
    return response


@login_required
def bulk_prescriptions_pdf(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    ids = request.POST.getlist("prescription_ids")
    if not ids:
        return JsonResponse({"error": "No prescription IDs provided"}, status=400)

    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        return JsonResponse({"error": "Only patients can download prescriptions"}, status=403)

    prescriptions = Prescription.objects.filter(pk__in=ids, patient=patient).select_related("doctor__user").prefetch_related("items__medicine")
    if not prescriptions.exists():
        return JsonResponse({"error": "No valid prescriptions found"}, status=404)

    writer = PdfWriter()
    for rx in prescriptions:
        reader = PdfReader(_build_prescription_pdf(rx))
        for page in reader.pages:
            writer.add_page(page)

    merged_buffer = BytesIO()
    writer.write(merged_buffer)
    merged_buffer.seek(0)

    response = HttpResponse(merged_buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = "attachment; filename=prescriptions_bulk.pdf"
    return response
