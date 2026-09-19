from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import never_cache_auth
from doctors.models import Appointment
from patient.models import HealthMetric, PatientHealthReport
from prescriptions.models import FollowUp, Prescription, ReminderSchedule


@never_cache_auth
@login_required
def health_record(request):
    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        messages.error(request, "Only patients can access health records.")
        return redirect("home")

    language = request.session.get("site_lang") or getattr(patient, "preferred_language", None) or "en"
    today = timezone.localdate()

    ai_answer = ""
    ai_query = ""

    if request.method == "POST":
        action = request.POST.get("action")
        upload_report = request.POST.get("upload_report")

        if action == "add_vitals":
            bp_sys = request.POST.get("systolic_bp")
            bp_dia = request.POST.get("diastolic_bp")
            glucose = request.POST.get("blood_glucose")
            hr = request.POST.get("heart_rate")
            weight = request.POST.get("weight")

            HealthMetric.objects.create(
                patient=patient,
                blood_pressure_sys=int(bp_sys) if bp_sys and bp_sys.isdigit() else None,
                blood_pressure_dia=int(bp_dia) if bp_dia and bp_dia.isdigit() else None,
                blood_sugar_fasting=float(glucose) if glucose else None,
                pulse_rate=int(hr) if hr and hr.isdigit() else None,
                weight_kg=float(weight) if weight else None,
            )
            messages.success(request, "Vitals recorded successfully.")
            return redirect("patient:health_record")

        elif action == "upload_report" or upload_report == "1":
            r_title = (request.POST.get("title") or request.POST.get("report_title") or "").strip()
            r_type = (request.POST.get("report_type") or "lab_test").strip()
            r_date = request.POST.get("date_performed")
            r_file = request.FILES.get("document_file") or request.FILES.get("report_file")
            r_notes = (request.POST.get("result_description") or request.POST.get("report_notes") or "").strip()
            r_clinic = (request.POST.get("doctor_or_clinic_name") or "").strip()

            if r_title and r_file:
                PatientHealthReport.objects.create(
                    patient=patient,
                    title=r_title,
                    report_type=r_type,
                    date_performed=r_date if r_date else today,
                    document_file=r_file,
                    result_description=r_notes,
                    doctor_or_clinic_name=r_clinic,
                )
                messages.success(request, "Health report uploaded successfully.")
            else:
                messages.error(request, "Report title and file are required.")
            return redirect("patient:health_record")

        elif "ai_query" in request.POST:
            ai_query = (request.POST.get("ai_query") or "").strip()
            if ai_query:
                from patient.services import generate_patient_reply
                ai_answer = generate_patient_reply(
                    question=ai_query,
                    language=language,
                    patient=patient,
                    history=None,
                    image_file=None,
                    prescription_id=None,
                )

    # 1. Fetch Prescriptions & Uploaded Health Reports
    prescriptions = (
        Prescription.objects.filter(patient=patient)
        .select_related("doctor__user")
        .prefetch_related("items__medicine", "follow_up")
        .order_by("-issued_at")
    )
    reports = PatientHealthReport.objects.filter(patient=patient).order_by("-date_performed")

    # 2. Build Unified Chronological Health Journey Timeline
    timeline_items = []
    for rx in prescriptions:
        timeline_items.append({
            "type": "prescription",
            "date": rx.issued_at.date(),
            "title": f"Prescription by Dr. {rx.doctor.user.get_full_name() or rx.doctor.user.username}",
            "subtitle": rx.doctor.specialty or "General Specialist",
            "details": "",
            "obj": rx,
            "download_url": f"/patient/prescriptions/{rx.pk}/download/",
        })

    for r in reports:
        timeline_items.append({
            "type": "health_report",
            "date": r.date_performed,
            "title": r.title,
            "subtitle": f"{r.get_report_type_display()} &bull; {r.doctor_or_clinic_name or 'Self Uploaded'}",
            "details": r.result_description or "No result notes specified.",
            "obj": r,
            "file_url": r.document_file.url if r.document_file else "",
        })

    timeline_items.sort(key=lambda x: x["date"], reverse=True)

    # 3. Last 30 days dose history chart data
    dose_history = []
    for i in range(29, -1, -1):
        d = today - timezone.timedelta(days=i)
        day_schedules = ReminderSchedule.objects.filter(
            prescription_item__prescription__patient=patient,
            scheduled_date=d,
        )
        day_total = day_schedules.count()
        day_taken = day_schedules.filter(status="taken").count()
        day_skipped = day_schedules.filter(status="skipped").count()
        day_pending = day_total - day_taken - day_skipped
        pct = int((day_taken / day_total) * 100) if day_total else 0
        dose_history.append({
            "date": d.strftime("%Y-%m-%d"),
            "label": d.strftime("%b %d"),
            "total": day_total,
            "taken": day_taken,
            "skipped": day_skipped,
            "pending": day_pending,
            "pct": pct,
        })

    vitals_history = HealthMetric.objects.filter(patient=patient).order_by("-logged_at")[:15]
    latest_vitals = vitals_history.first()

    prescriptions_paginator = Paginator(prescriptions, 10)
    reports_paginator = Paginator(reports, 10)
    rx_page = request.GET.get("rx_page")
    rpt_page = request.GET.get("rpt_page")
    prescriptions_page = prescriptions_paginator.get_page(rx_page)
    reports_page = reports_paginator.get_page(rpt_page)

    from carebridge.ai_services import GeminiAIService

    latest_rx = prescriptions.first() if prescriptions else None
    latest_rpt = reports.first() if reports else None
    is_bn = language == "bn"

    if not latest_rx and not latest_rpt:
        if is_bn:
            history_text_summary = "বর্তমানে কোনো সক্রিয় প্রেসক্রিপশন বা মেডিকেল রেকর্ড যুক্ত নেই। আপনার স্বাস্থ্য প্রোফাইল আপডেট রাখতে নতুন অ্যাপয়েন্টমেন্ট বুক করুন বা ল্যাব রিপোর্ট আপলোড করুন।"
        else:
            history_text_summary = "No active medical conditions or prescriptions recorded yet. Your medical profile is clear. You can book an appointment or upload lab reports to track your complete health journey."
    else:
        parts = []
        if latest_rx:
            doc_name = latest_rx.doctor.user.get_full_name() or latest_rx.doctor.user.username
            specialty = latest_rx.doctor.specialty or ("মেডিসিন বিশেষজ্ঞ" if is_bn else "General Specialist")

            if latest_rx.diagnosis:
                if is_bn:
                    parts.append(f"বর্তমান স্বাস্থ্য অবস্থা: ডা. {doc_name} ({specialty})-এর অধীনে '{latest_rx.diagnosis}'-এর চিকিৎসাধীন।")
                else:
                    parts.append(f"Current Clinical Status: Under the care of Dr. {doc_name} ({specialty}) for {latest_rx.diagnosis}.")
            elif latest_rx.chief_complaints:
                if is_bn:
                    parts.append(f"বর্তমান স্বাস্থ্য অবস্থা: ডা. {doc_name} ({specialty})-এর সাথে '{latest_rx.chief_complaints}'-এর জন্য পরামর্শ গ্রহণ করেছেন।")
                else:
                    parts.append(f"Current Clinical Status: Under consultation with Dr. {doc_name} ({specialty}) for {latest_rx.chief_complaints}.")
            else:
                if is_bn:
                    parts.append(f"বর্তমান স্বাস্থ্য অবস্থা: ডা. {doc_name} ({specialty})-এর পরামর্শ গ্রহণ করেছেন।")
                else:
                    parts.append(f"Current Clinical Status: Under consultation with Dr. {doc_name} ({specialty}).")

            rx_items = list(latest_rx.items.select_related("medicine").all())
            if rx_items:
                med_list = ", ".join([f"{item.medicine.brand_name or item.medicine.generic_name} ({item.dosage})" for item in rx_items[:3]])
                if is_bn:
                    parts.append(f"চলমান প্রধান ওষুধ: {med_list}।")
                else:
                    parts.append(f"Active Prescribed Regimen: {med_list}.")

            fu = getattr(latest_rx, "follow_up", None)
            if fu and fu.status == "upcoming":
                if is_bn:
                    parts.append(f"পরবর্তী ফলো-আপ সাক্ষাত: {fu.scheduled_date} তারিখে নির্ধারিত।")
                else:
                    parts.append(f"Next Scheduled Follow-up: {fu.scheduled_date}.")

        if latest_rpt:
            if is_bn:
                parts.append(f"সর্বশেষ ল্যাব রিপোর্ট: {latest_rpt.title} ({latest_rpt.date_performed})।")
            else:
                parts.append(f"Latest Diagnostic Report: {latest_rpt.title} ({latest_rpt.date_performed}).")

        if is_bn:
            parts.append("প্রেসক্রিপশন অনুযায়ী সঠিক সময়ে নিয়মিত ওষুধ সেবন এবং সুস্থ জীবনধারা বজায় রাখুন।")
        else:
            parts.append("Maintain regular adherence to your prescribed regimen and monitor your overall recovery.")

        history_text_summary = " ".join(parts)

    overview_diagnosis = latest_rx.diagnosis if latest_rx else None
    overview_doctor = latest_rx.doctor if latest_rx else None
    overview_next_followup = (
        latest_rx.follow_up.scheduled_date
        if (latest_rx and hasattr(latest_rx, "follow_up") and latest_rx.follow_up and latest_rx.follow_up.status == "upcoming")
        else None
    )

    return render(request, "patient/health_record.html", {
        "patient": patient,
        "prescriptions": prescriptions_page,
        "reports": reports_page,
        "reports_list": reports,
        "timeline_items": timeline_items,
        "ai_answer": ai_answer,
        "ai_query": ai_query,
        "history_text_summary": history_text_summary,
        "overview_diagnosis": overview_diagnosis,
        "overview_doctor": overview_doctor,
        "overview_next_followup": overview_next_followup,
        "ai_available": GeminiAIService.is_ai_available(),
        "prescriptions_page": prescriptions_page,
        "reports_page": reports_page,
        "vitals_history": vitals_history,
        "latest_vitals": latest_vitals,
        "dose_history": dose_history,
    })


@never_cache_auth
@login_required
def reports(request):
    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        messages.error(request, "Only patients can view reports.")
        return redirect("home")

    export_format = request.GET.get("export")
    status_filter = request.GET.get("status", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()

    base_qs = Appointment.objects.filter(patient=patient).select_related("doctor__user", "doctor")
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

    from carebridge.reports_utils import compute_appointment_report, export_report_pdf
    if export_format == "pdf":
        metrics = compute_appointment_report(base_qs)
        metrics["generated_on"] = timezone.localtime(timezone.now()).strftime("%d %b %Y, %I:%M %p")
        return export_report_pdf(
            base_qs,
            metrics,
            f"CareBridge Patient Appointment Report — {request.user.get_full_name()}",
            "patient_appointment_report.pdf",
            patient=patient,
            start_date=start_date,
            end_date=end_date,
            owner_type="patient",
        )

    metrics = compute_appointment_report(base_qs)
    return render(request, "patient/reports.html", {
        "metrics": metrics,
        "status_filter": status_filter,
        "start_date": start_date,
        "end_date": end_date,
        "status_choices": Appointment.STATUS_CHOICES,
    })


@never_cache_auth
@login_required
def overall_report(request):
    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        messages.error(request, "Only patients can view overall health report.")
        return redirect("home")

    export_format = request.GET.get("export")
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()

    appointments = Appointment.objects.filter(patient=patient).select_related("doctor__user").order_by("-appointment_date")
    prescriptions = Prescription.objects.filter(patient=patient).select_related("doctor__user").prefetch_related("items__medicine").order_by("-issued_at")
    medical_history = getattr(patient, "medical_history", None)
    health_reports = getattr(patient, "health_reports", None)
    if health_reports is not None:
        health_reports = health_reports.all().order_by("-date_performed")
    else:
        health_reports = PatientHealthReport.objects.filter(patient=patient).order_by("-date_performed")
    vitals_qs = HealthMetric.objects.filter(patient=patient).order_by("-logged_at")
    latest_vitals = vitals_qs.first()

    summary_language = request.GET.get("lang") or "en"
    if summary_language not in {"bn", "en"}:
        summary_language = "en"
    if request.GET.get("lang"):
        request.session["site_lang"] = summary_language
        if hasattr(patient, "preferred_language"):
            patient.preferred_language = summary_language
            patient.save(update_fields=["preferred_language"])

    history_parts = []
    if medical_history and (medical_history.chronic_conditions or medical_history.allergies or medical_history.past_surgeries or medical_history.family_medical_history):
        history_parts.append("Medical History:")
        if medical_history.chronic_conditions:
            history_parts.append(f"- Chronic Conditions: {medical_history.chronic_conditions}")
        if medical_history.allergies:
            history_parts.append(f"- Allergies: {medical_history.allergies}")
        if medical_history.past_surgeries:
            history_parts.append(f"- Past Surgeries: {medical_history.past_surgeries}")
        if medical_history.family_medical_history:
            history_parts.append(f"- Family History: {medical_history.family_medical_history}")

    recent_appointments = appointments[:5]
    if recent_appointments:
        history_parts.append("Recent Appointments:")
        for apt in recent_appointments:
            history_parts.append(f"- {apt.appointment_date}: Dr. {apt.doctor.user.get_full_name() or apt.doctor.user.username} ({apt.get_status_display()})")

    recent_rxs = prescriptions[:5]
    if recent_rxs:
        history_parts.append("Recent Prescriptions:")
        for rx in recent_rxs:
            meds = ", ".join([item.medicine.brand_name for item in rx.items.all()[:3]])
            if rx.items.count() > 3:
                meds += "..."
            history_parts.append(f"- {rx.issued_at.strftime('%Y-%m-%d')}: {rx.diagnosis or rx.chief_complaints or 'General'} — Medicines: {meds or 'None'}")

    recent_reports = health_reports[:5]
    if recent_reports:
        history_parts.append("Recent Health Reports:")
        for r in recent_reports:
            history_parts.append(f"- {r.date_performed}: {r.title} ({r.get_report_type_display()})")

    history_text = "\n".join(history_parts) if history_parts else "No detailed medical history available yet."

    metrics_parts = []
    if latest_vitals:
        if latest_vitals.heart_rate:
            metrics_parts.append(f"Heart rate: {latest_vitals.heart_rate} bpm")
        if latest_vitals.blood_pressure_sys and latest_vitals.blood_pressure_dia:
            metrics_parts.append(f"BP: {latest_vitals.blood_pressure_sys}/{latest_vitals.blood_pressure_dia} mmHg")
        if latest_vitals.temperature_celsius:
            metrics_parts.append(f"Temperature: {latest_vitals.temperature_celsius}°C")
        if latest_vitals.weight_kg:
            metrics_parts.append(f"Weight: {latest_vitals.weight_kg} kg")
        if latest_vitals.height_cm:
            metrics_parts.append(f"Height: {latest_vitals.height_cm} cm")
        if latest_vitals.oxygen_saturation:
            metrics_parts.append(f"SpO2: {latest_vitals.oxygen_saturation}%")
    metrics_summary = "; ".join(metrics_parts) if metrics_parts else "No recent vitals on file."

    from carebridge.ai_services import GeminiAIService

    ai_summary = GeminiAIService.generate_clinical_summary(
        patient_name=patient.user.get_full_name() or patient.user.email,
        history_text=history_text,
        metrics_summary=metrics_summary,
        language=summary_language,
    )

    def calculate_age(dob):
        from datetime import date
        if not dob:
            return None
        today = date.today()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    patient_age = calculate_age(patient.date_of_birth)

    if start_date:
        try:
            d_start = datetime.strptime(start_date, "%Y-%m-%d").date()
            appointments = appointments.filter(appointment_date__gte=d_start)
            prescriptions = prescriptions.filter(issued_at__date__gte=d_start)
            vitals_qs = vitals_qs.filter(logged_at__date__gte=d_start)
            health_reports = health_reports.filter(date_performed__gte=d_start)
        except ValueError:
            pass

    if end_date:
        try:
            d_end = datetime.strptime(end_date, "%Y-%m-%d").date()
            appointments = appointments.filter(appointment_date__lte=d_end)
            prescriptions = prescriptions.filter(issued_at__date__lte=d_end)
            vitals_qs = vitals_qs.filter(logged_at__date__lte=d_end)
            health_reports = health_reports.filter(date_performed__lte=d_end)
        except ValueError:
            pass

    if export_format == "pdf":
        from carebridge.reports_utils import export_overall_health_report_pdf
        metrics = {
            "total_appointments": appointments.count(),
            "completed_appointments": appointments.filter(status="completed").count(),
            "cancelled_appointments": appointments.filter(status="cancelled").count(),
            "missed_appointments": appointments.filter(status="missed").count(),
            "total_prescriptions": prescriptions.count(),
            "active_prescriptions": prescriptions.filter(status="active").count(),
        }
        return export_overall_health_report_pdf(
            patient=patient,
            metrics=metrics,
            appointments=appointments.order_by("-appointment_date")[:50],
            prescriptions=prescriptions.order_by("-issued_at")[:50],
            vitals=vitals_qs.order_by("-logged_at")[:20],
            ai_summary=ai_summary,
            medical_history=medical_history,
            filename="overall_health_report.pdf",
        )

    return render(request, "patient/overall_report.html", {
        "patient": patient,
        "patient_age": patient_age,
        "metrics": {
            "total_appointments": appointments.count(),
            "completed_appointments": appointments.filter(status="completed").count(),
            "cancelled_appointments": appointments.filter(status="cancelled").count(),
            "missed_appointments": appointments.filter(status="missed").count(),
            "total_prescriptions": prescriptions.count(),
            "active_prescriptions": prescriptions.filter(status="active").count(),
            "latest_vitals": latest_vitals,
            "generated_on": timezone.localtime(timezone.now()).strftime("%d %b %Y, %I:%M %p"),
        },
        "start_date": start_date,
        "end_date": end_date,
        "recent_appointments": appointments.order_by("-appointment_date")[:10],
        "recent_prescriptions": prescriptions.order_by("-issued_at")[:10],
        "vitals_list": vitals_qs.order_by("-logged_at")[:10],
        "medical_history": medical_history,
        "ai_summary": ai_summary,
        "summary_language": summary_language,
    })


@never_cache_auth
@login_required
def dose_track_report(request):
    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        messages.error(request, "Only patients can view dose tracking reports.")
        return redirect("home")

    export_format = request.GET.get("export")
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()

    doses_qs = ReminderSchedule.objects.filter(
        prescription_item__prescription__patient=patient
    ).select_related("prescription_item__medicine", "prescription_item__prescription__doctor__user")

    if start_date:
        try:
            doses_qs = doses_qs.filter(scheduled_date__gte=datetime.strptime(start_date, "%Y-%m-%d").date())
        except ValueError:
            pass
    if end_date:
        try:
            doses_qs = doses_qs.filter(scheduled_date__lte=datetime.strptime(end_date, "%Y-%m-%d").date())
        except ValueError:
            pass

    total = doses_qs.count()
    taken = doses_qs.filter(status="taken").count()
    skipped = doses_qs.filter(status="skipped").count()
    missed = doses_qs.filter(status="missed").count()
    pending = doses_qs.filter(status="pending").count()
    rate = round((taken / total * 100), 1) if total > 0 else 0

    metrics = {
        "total": total,
        "taken": taken,
        "skipped": skipped,
        "missed": missed,
        "pending": pending,
        "rate": rate,
        "generated_on": timezone.localtime(timezone.now()).strftime("%d %b %Y, %I:%M %p"),
    }

    if export_format == "pdf":
        from carebridge.reports_utils import export_dose_report_pdf
        return export_dose_report_pdf(
            patient=patient,
            metrics=metrics,
            doses=doses_qs.order_by("-scheduled_date", "-reminder_time")[:100],
            filename="dose_tracking_report.pdf",
        )

    return render(request, "patient/dose_track_report.html", {
        "metrics": metrics,
        "doses": doses_qs.order_by("-scheduled_date", "-reminder_time")[:50],
        "start_date": start_date,
        "end_date": end_date,
    })
