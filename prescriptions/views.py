from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, Http404
from django.utils import timezone
import pytz
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter
from carebridge.ai_services import GeminiAIService
from accounts.decorators import never_cache_auth
from .models import AIPrescriptionScan, Prescription, PrescriptionItem, Medicine
from doctors.models import Appointment


@login_required
def scan_prescription_view(request):
    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        messages.error(request, "Only patients can scan prescriptions.")
        return redirect("home")

    recent_scans = AIPrescriptionScan.objects.filter(patient=patient).order_by("-created_at")[:10]

    if request.method == "POST":
        image = request.FILES.get("prescription_image")
        if not image:
            messages.error(request, "Please upload a prescription image.")
            return redirect("prescriptions:scan_prescription")

        scan = AIPrescriptionScan.objects.create(
            patient=patient,
            image=image,
            status="pending",
        )
        messages.success(request, "Prescription uploaded. AI is processing it...")
        return redirect("prescriptions:scan_prescription")

    return render(request, "prescriptions/scan_prescription.html", {
        "recent_scans": recent_scans,
    })


def _build_prescription_pdf(prescription):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle(name='Title', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#0f766e'), spaceAfter=6)
    subtitle_style = ParagraphStyle(name='Subtitle', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#57534e'), spaceAfter=12)
    heading_style = ParagraphStyle(name='Heading', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#0f766e'), spaceAfter=4, spaceBefore=8)
    normal_style = ParagraphStyle(name='Normal', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.HexColor('#1c1917'))
    small_style = ParagraphStyle(name='Small', parent=styles['Normal'], fontSize=9, leading=12, textColor=colors.HexColor('#57534e'))

    story.append(Paragraph("CareBridgeAI Health", title_style))
    story.append(Paragraph("Smart Clinical & Healthcare Portal", subtitle_style))
    story.append(Spacer(1, 6))

    doctor = prescription.doctor
    patient = prescription.patient
    doctor_name = doctor.user.get_full_name() or doctor.user.username
    patient_name = patient.user.get_full_name() or patient.user.email

    info_data = [
        [Paragraph("<b>Doctor</b>", normal_style), Paragraph(doctor_name, normal_style),
         Paragraph("<b>Specialty</b>", normal_style), Paragraph(doctor.specialty or "General Specialist", normal_style)],
        [Paragraph("<b>Patient</b>", normal_style), Paragraph(patient_name, normal_style),
         Paragraph("<b>Issued</b>", normal_style), Paragraph(prescription.issued_at.strftime("%d %b %Y, %I:%M %p"), normal_style)],
        [Paragraph("<b>Clinic</b>", normal_style), Paragraph(doctor.clinic_name or "CareBridge Digital Chamber", normal_style),
         Paragraph("<b>Rx Code</b>", normal_style), Paragraph(f"#CARE-RX-{prescription.pk}", normal_style)],
    ]
    info_table = Table(info_data, colWidths=[30*mm, 55*mm, 30*mm, 55*mm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0fdfa')),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#f0fdfa')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#1c1917')),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e7e5e4')),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 10))

    if prescription.chief_complaints:
        story.append(Paragraph("Chief Complaints (C/C)", heading_style))
        story.append(Paragraph(prescription.chief_complaints, normal_style))
    if prescription.diagnosis:
        story.append(Paragraph("Diagnosis (D)", heading_style))
        story.append(Paragraph(f"<b>{prescription.diagnosis}</b>", normal_style))
    if prescription.tests_investigations:
        story.append(Paragraph("Tests / Investigations", heading_style))
        story.append(Paragraph(prescription.tests_investigations, normal_style))

    story.append(Paragraph("Prescribed Medicines (Rx)", heading_style))
    meds = prescription.items.select_related("medicine").all()
    if meds:
        med_data = [[Paragraph("<b>Medicine</b>", normal_style), Paragraph("<b>Dosage</b>", normal_style),
                     Paragraph("<b>Frequency</b>", normal_style), Paragraph("<b>Duration</b>", normal_style),
                     Paragraph("<b>Timing</b>", normal_style)]]
        for item in meds:
            med_data.append([
                Paragraph(f"{item.medicine.brand_name} <br/><font color='#57534e' size='9'>{item.medicine.generic_name}</font>", normal_style),
                Paragraph(item.dosage, normal_style),
                Paragraph(f"{item.frequency}x / day", normal_style),
                Paragraph(f"{item.duration_days} days", normal_style),
                Paragraph(item.get_timing_relation_to_meal_display(), normal_style),
            ])
        med_table = Table(med_data, colWidths=[55*mm, 25*mm, 25*mm, 25*mm, 40*mm])
        med_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f766e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#fafaf9')),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#1c1917')),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e7e5e4')),
        ]))
        story.append(med_table)
    else:
        story.append(Paragraph("No specific medicines recorded on this prescription.", small_style))

    if prescription.advice_rules:
        story.append(Paragraph("Advice & Lifestyle Rules", heading_style))
        story.append(Paragraph(prescription.advice_rules, normal_style))
    if prescription.doctor_notes:
        story.append(Paragraph("Doctor Notes", heading_style))
        story.append(Paragraph(prescription.doctor_notes, small_style))

    story.append(Spacer(1, 14))
    story.append(Table([['']], colWidths=[170*mm], rowHeights=[1], style=TableStyle([('LINEBELOW', (0,0), (-1,0), 1, colors.HexColor('#d6d3d1'))])))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"Verification Hash: {prescription.pk}-{prescription.issued_at.strftime('%Y%m%d')}", small_style))
    story.append(Paragraph("Issued by CareBridge AI Clinical Network", small_style))

    doc.build(story)
    buffer.seek(0)
    return buffer


def _build_appointment_receipt_pdf(appointment):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle(name='Title', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#0f766e'), spaceAfter=6)
    subtitle_style = ParagraphStyle(name='Subtitle', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#57534e'), spaceAfter=12)
    heading_style = ParagraphStyle(name='Heading', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#0f766e'), spaceAfter=4, spaceBefore=8)
    normal_style = ParagraphStyle(name='Normal', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.HexColor('#1c1917'))
    small_style = ParagraphStyle(name='Small', parent=styles['Normal'], fontSize=9, leading=12, textColor=colors.HexColor('#57534e'))

    story.append(Paragraph("CareBridgeAI Health", title_style))
    story.append(Paragraph("Appointment Receipt", subtitle_style))
    story.append(Spacer(1, 6))

    doctor = appointment.doctor
    patient = appointment.patient
    doctor_name = doctor.user.get_full_name() or doctor.user.username
    patient_name = patient.user.get_full_name() or patient.user.email

    bdt = pytz.timezone("Asia/Dhaka")
    local_dt = appointment.appointment_date.strftime("%d %b %Y")
    local_start = appointment.start_time.strftime("%I:%M %p")
    local_end = appointment.end_time.strftime("%I:%M %p") if appointment.end_time else ""

    info_data = [
        [Paragraph("<b>Patient</b>", normal_style), Paragraph(patient_name, normal_style),
         Paragraph("<b>Contact</b>", normal_style), Paragraph(patient.user.email or "N/A", normal_style)],
        [Paragraph("<b>Doctor</b>", normal_style), Paragraph(doctor_name, normal_style),
         Paragraph("<b>Specialty</b>", normal_style), Paragraph(doctor.specialty or "General Specialist", normal_style)],
        [Paragraph("<b>Appointment ID</b>", normal_style), Paragraph(f"#{appointment.pk}", normal_style),
         Paragraph("<b>Status</b>", normal_style), Paragraph(appointment.get_status_display(), normal_style)],
        [Paragraph("<b>Date</b>", normal_style), Paragraph(local_dt, normal_style),
         Paragraph("<b>Time (BDT)</b>", normal_style), Paragraph(f"{local_start} - {local_end}", normal_style)],
        [Paragraph("<b>Service Type</b>", normal_style), Paragraph(appointment.get_consultation_type_display(), normal_style),
         Paragraph("<b>Fee</b>", normal_style), Paragraph(f"BDT {appointment.fee_bdt:,.2f}", normal_style)],
    ]
    info_table = Table(info_data, colWidths=[30*mm, 55*mm, 30*mm, 55*mm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0fdfa')),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#f0fdfa')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#1c1917')),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e7e5e4')),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 10))

    if appointment.chief_complaint:
        story.append(Paragraph("Chief Complaint", heading_style))
        story.append(Paragraph(appointment.chief_complaint, normal_style))

    story.append(Spacer(1, 14))
    story.append(Table([['']], colWidths=[170*mm], rowHeights=[1], style=TableStyle([('LINEBELOW', (0,0), (-1,0), 1, colors.HexColor('#d6d3d1'))])))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"Generated on {timezone.now().astimezone(bdt).strftime('%d %b %Y, %I:%M %p')} BDT", small_style))
    story.append(Paragraph("CareBridge AI Telemedicine & Clinical Systems", small_style))

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


@login_required
def printable_prescription_pdf(request, prescription_id):
    patient = getattr(request.user, "patient_profile", None)
    prescription = get_object_or_404(Prescription, pk=prescription_id, patient=patient)
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
