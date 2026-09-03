import json
import os
from decimal import Decimal
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Min, Max, Sum, Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.conf import settings

from carebridge.ai_services import GeminiAIService
from doctors.models import Appointment, DoctorSchedule
from prescriptions.models import FollowUp, Prescription, ReminderSchedule
from prescriptions.views import _build_prescription_pdf

from accounts.models import AppNotification, Doctor, News, Patient
from accounts.decorators import never_cache_auth

from .models import ChatMessage, ChatSession
from .services import generate_patient_reply, summarize_prescription


def _get_patient(request):
    if not request.user.is_authenticated:
        return None
    return getattr(request.user, "patient_profile", None)


def _resolve_language(request, patient):
    lang = request.GET.get("lang") or request.POST.get("lang")
    if not lang:
        try:
            if request.body:
                lang = json.loads(request.body).get("lang")
        except (json.JSONDecodeError, AttributeError, Exception):
            pass
    lang = lang or request.session.get("site_lang") or (patient.preferred_language if patient else "en")
    return "bn" if lang == "bn" else "en"


def _get_active_ai_model():
    try:
        from carebridge.ai_services import GeminiAIService
        providers = GeminiAIService._get_db_providers()
        for p in providers:
            if p.is_available:
                return p.model_name or p.get_provider_display()
    except Exception:
        pass
    return "Gemini"


def _get_or_create_session(patient, session_id=None):
    if not patient:
        return None
    if session_id:
        try:
            return ChatSession.objects.filter(pk=session_id, patient=patient).first()
        except (ValueError, TypeError):
            pass
    session = ChatSession.objects.create(patient=patient, title="New Chat")
    first_msg = ChatMessage.objects.filter(patient=patient, session=session).order_by("created_at").first()
    if first_msg:
        session.title = first_msg.content[:50] or "New Chat"
        session.save(update_fields=["title", "updated_at"])
    return session


DOSE_TIMES = [
    "09:00:00",
    "14:00:00",
    "18:00:00",
    "22:00:00",
]


def _ensure_dose_schedules(patient):
    from prescriptions.models import Prescription, PrescriptionItem, ReminderSchedule, get_active_dose_slots
    today = timezone.localdate()
    now = timezone.localtime(timezone.now())

    active_rxs = Prescription.objects.filter(patient=patient, status__in=["active", "scheduled"]).order_by("-issued_at")
    if not active_rxs.exists():
        ReminderSchedule.objects.filter(
            prescription_item__prescription__patient=patient,
            scheduled_date=today,
            status="pending"
        ).delete()
        return

    latest_rx = active_rxs.first()
    use_rx = None

    if latest_rx.status == "active":
        use_rx = latest_rx
    elif latest_rx.status == "scheduled":
        if latest_rx.activates_at and now >= latest_rx.activates_at:
            latest_rx.status = "active"
            latest_rx.save(update_fields=["status"])
            use_rx = latest_rx
        else:
            active_rx = active_rxs.filter(status="active").first()
            if active_rx:
                use_rx = active_rx
            else:
                ReminderSchedule.objects.filter(
                    prescription_item__prescription__patient=patient,
                    scheduled_date=today,
                ).exclude(prescription_item__prescription=latest_rx).delete()
                return

    if not use_rx:
        return

    older_rxs = active_rxs.exclude(pk=use_rx.pk)
    if older_rxs.exists():
        older_rxs.update(status="completed")

    ReminderSchedule.objects.filter(
        prescription_item__prescription__patient=patient,
        scheduled_date=today,
    ).exclude(prescription_item__prescription=use_rx).delete()

    items = use_rx.items.all()
    for item in items:
        # Clean up legacy schedule entries without reminder_time
        ReminderSchedule.objects.filter(
            prescription_item=item,
            scheduled_date=today,
            reminder_time__isnull=True
        ).delete()

        issued_date = use_rx.issued_at.date()
        days_since = (today - issued_date).days
        if 0 <= days_since < item.duration_days:
            active_slots = get_active_dose_slots(item.dosage, item.frequency)

            custom_times = patient.custom_dose_times or []
            if custom_times:
                mapped_slots = []
                for idx, slot in enumerate(active_slots):
                    new_slot = dict(slot)
                    if idx < len(custom_times):
                        ct = custom_times[idx]
                        new_slot["time"] = ct + ":00" if len(ct) == 5 else ct
                    mapped_slots.append(new_slot)
                active_slots = mapped_slots

            allowed_times = [slot["time"] for slot in active_slots]

            # Clean up any schedules for today that don't match active dosage slots
            ReminderSchedule.objects.filter(
                prescription_item=item,
                scheduled_date=today
            ).exclude(reminder_time__in=allowed_times).delete()

            for slot in active_slots:
                ReminderSchedule.objects.get_or_create(
                    prescription_item=item,
                    scheduled_date=today,
                    reminder_time=slot["time"],
                    defaults={"status": "pending"},
                )


@login_required
def custom_dose_times(request):
    patient = request.user.patient_profile

    if request.method == "POST":
        times = request.POST.getlist("dose_times")
        cleaned = []
        for t in times:
            t = t.strip()
            if not t:
                continue
            if len(t) == 5:
                t = t + ":00"
            cleaned.append(t)
        # Validate times
        valid_times = []
        for t in cleaned:
            try:
                from datetime import datetime
                datetime.strptime(t, "%H:%M:%S")
                valid_times.append(t[:5])
            except ValueError:
                pass
        patient.custom_dose_times = valid_times
        patient.save(update_fields=["custom_dose_times"])
        messages.success(request, "Custom dose times saved successfully.")
        return redirect("patient:custom_dose_times")

    current_times = patient.custom_dose_times or []
    return render(request, "patient/custom_dose_times.html", {
        "current_times": current_times,
    })


@login_required
def dashboard(request):
    patient = request.user.patient_profile
    today = timezone.localdate()
    now = timezone.localtime(timezone.now())

    _ensure_dose_schedules(patient)

    # Auto-mark today's past appointments as missed once the prescription window closes
    from doctors.views import _auto_mark_missed_today
    _auto_mark_missed_today(patient=patient)

    # Prescription timing evaluator
    for rx in Prescription.objects.filter(patient=patient):
        updated = False
        if rx.activates_at and now >= rx.activates_at and rx.status == "scheduled":
            rx.status = "active"
            updated = True
        if rx.expires_at and now >= rx.expires_at and not rx.is_locked:
            rx.is_locked = True
            updated = True
        if updated:
            rx.save(update_fields=["status", "is_locked"])

    # Follow-up auto-completion evaluator
    all_followups = FollowUp.objects.filter(prescription__patient=patient)
    for fu in all_followups:
        doc = fu.prescription.doctor
        has_rx = Prescription.objects.filter(
            doctor=doc,
            patient=patient,
            issued_at__date__gte=fu.scheduled_date
        ).exists()

        if has_rx and fu.status != "completed":
            fu.status = "completed"
            fu.save()
        elif fu.scheduled_date < today and fu.status == "upcoming":
            fu.status = "missed"
            fu.save()

    now = timezone.localtime()
    current_hour = now.hour

    doses_today = ReminderSchedule.objects.filter(
        prescription_item__prescription__patient=patient,
        scheduled_date=today,
        status="pending",
    ).select_related("prescription_item__medicine")

    dose_reminder_message = None
    due_now = doses_today.filter(reminder_time__hour=current_hour).first()
    if due_now:
        dose_reminder_message = (
            f"Reminder sent to your mobile — "
            f"{due_now.prescription_item.medicine}, "
            f"{due_now.reminder_time.strftime('%I:%M %p')}"
        )

    next_follow_up = (
        FollowUp.objects.filter(prescription__patient=patient, status="upcoming")
        .order_by("scheduled_date")
        .first()
    )

    # Follow-ups requiring booking (allow booking even after deadline)
    followups_needing_booking = FollowUp.objects.filter(
        prescription__patient=patient,
        status="upcoming",
        is_booking_confirmed=False,
    ).select_related("prescription__doctor__user").order_by("scheduled_date")[:5]

    # Overdue/missed follow-up bookings - allow rebooking for missed follow-ups
    overdue_followups = FollowUp.objects.filter(
        prescription__patient=patient,
        status__in=["upcoming", "missed"],
        is_booking_confirmed=False,
        scheduled_date__lt=today,
    ).select_related("prescription__doctor__user").order_by("scheduled_date")[:5]

    # Send follow-up booking notifications (4 days before follow-up date)
    for fu in FollowUp.objects.filter(
        prescription__patient=patient,
        status="upcoming",
        notification_sent=False,
    ).select_related("prescription__doctor__user"):
        if fu.should_send_notification():
            AppNotification.objects.create(
                user=patient.user,
                title="📅 Follow-up Reminder — Book Your Appointment",
                message=f"Your follow-up with Dr. {fu.prescription.doctor.user.get_full_name() or fu.prescription.doctor.user.username} is scheduled for {fu.scheduled_date.strftime('%d %b %Y')}. Please book your appointment. You can book even after the suggested deadline if needed.",
                notification_type="booking",
                link_url=reverse("patient:follow_ups"),
            )
            fu.notification_sent = True
            fu.save(update_fields=["notification_sent"])

    upcoming_appointments = Appointment.objects.filter(
        patient=patient,
        appointment_date__gte=timezone.localdate(),
        status__in=["pending", "confirmed"],
    ).select_related("doctor__user").order_by("appointment_date", "start_time")[:5]

    # Current appointments (today) - shown separately
    current_appointments = Appointment.objects.filter(
        patient=patient,
        appointment_date=today,
        status__in=["pending", "confirmed"],
    ).select_related("doctor__user").order_by("start_time")

    # Check if patient has ANY appointment history (for empty state)
    has_any_booking = Appointment.objects.filter(patient=patient).exists()

    # Calendar data - past 90 days to next 365 days
    calendar_start = today - timezone.timedelta(days=90)
    calendar_end = today + timezone.timedelta(days=365)
    
    calendar_appointments = Appointment.objects.filter(
        patient=patient,
        appointment_date__gte=calendar_start,
        appointment_date__lte=calendar_end,
        status__in=["pending", "confirmed"],
    ).select_related("doctor__user").order_by("appointment_date", "start_time")
    
    calendar_followups = FollowUp.objects.filter(
        prescription__patient=patient,
        scheduled_date__gte=calendar_start,
        scheduled_date__lte=calendar_end,
        status__in=["upcoming", "missed"],
    ).select_related("prescription__doctor__user").order_by("scheduled_date")
    
    calendar_doses = ReminderSchedule.objects.filter(
        prescription_item__prescription__patient=patient,
        scheduled_date__gte=calendar_start,
        scheduled_date__lte=calendar_end,
        status="pending",
    ).select_related("prescription_item__medicine").order_by("scheduled_date", "reminder_time")[:100]

    refund_notifications = AppNotification.objects.filter(
        user=request.user,
        notification_type="booking",
    ).filter(
        Q(title__icontains="refund") | Q(title__icontains="cancel") | Q(title__icontains="Cancellation")
    ).order_by("-created_at")[:5]

    return render(request, "patient/dashboard.html", {
        "patient": patient,
        "doses_today": doses_today,
        "dose_reminder_message": dose_reminder_message,
        "next_follow_up": next_follow_up,
        "followups_needing_booking": followups_needing_booking,
        "overdue_followups": overdue_followups,
        "upcoming_appointments": upcoming_appointments,
        "current_appointments": current_appointments,
        "has_any_booking": has_any_booking,
        "refund_notifications": refund_notifications,
        "calendar_appointments": calendar_appointments,
        "calendar_followups": calendar_followups,
        "calendar_doses": calendar_doses,
        "news_list": News.objects.filter(is_active=True, target_audience__in=["all", "patients"]).order_by("-created_at")[:5],
    })


@login_required
def prescription_detail(request, prescription_id):
    patient = request.user.patient_profile
    prescription = get_object_or_404(Prescription, pk=prescription_id, patient=patient)
    summary_language = request.GET.get("lang") or request.session.get("site_lang") or patient.preferred_language or "en"
    if summary_language not in {"bn", "en"}:
        summary_language = "en"
    
    if request.GET.get("lang"):
        request.session["site_lang"] = summary_language

    cache_key = f"prescription-summary:{prescription.pk}:{summary_language}"
    summary_payload = request.session.get(cache_key)
    if request.GET.get("refresh") or not summary_payload or not isinstance(summary_payload, dict) or "overview" not in summary_payload:
        summary_payload = summarize_prescription(prescription, summary_language)
        request.session[cache_key] = summary_payload

    # Deep AI analysis for detailed prescription view
    deep_cache_key = f"prescription-deep:{prescription.pk}:{summary_language}"
    deep_analysis = request.session.get(deep_cache_key)
    if request.GET.get("refresh") or not deep_analysis or not isinstance(deep_analysis, dict) or "overview" not in deep_analysis:
        from prescriptions.services import analyze_prescription_deep
        deep_analysis = analyze_prescription_deep(prescription, summary_language)
        request.session[deep_cache_key] = deep_analysis

    patient_age = None
    if prescription.patient.date_of_birth:
        today = timezone.localdate()
        patient_age = today.year - prescription.patient.date_of_birth.year - ((today.month, today.day) < (prescription.patient.date_of_birth.month, prescription.patient.date_of_birth.day))

    return render(request, "patient/prescription_detail.html", {
        "prescription": prescription,
        "patient_age": patient_age,
        "summary_text": summary_payload.get("text", ""),
        "summary_overview": summary_payload.get("overview", ""),
        "summary_schedule": summary_payload.get("schedule", ""),
        "summary_precautions": summary_payload.get("precautions", ""),
        "summary_warnings": summary_payload.get("warnings", ""),
        "summary_source": summary_payload.get("source", "local"),
        "summary_language": summary_language,
        "deep_analysis": deep_analysis,
    })


@login_required
def doses_today(request):
    patient = request.user.patient_profile
    today = timezone.localdate()

    _ensure_dose_schedules(patient)

    schedules = ReminderSchedule.objects.filter(
        prescription_item__prescription__patient=patient,
        scheduled_date=today,
        status="pending",
    ).select_related("prescription_item__medicine")

    if request.method == "POST":
        schedule_id = request.POST.get("schedule_id")
        new_status = request.POST.get("status")
        schedule = get_object_or_404(
            ReminderSchedule, pk=schedule_id,
            prescription_item__prescription__patient=patient,
        )
        if new_status in ("taken", "skipped"):
            schedule.status = new_status
            schedule.save()
            messages.success(request, "✓ Dose status updated.")

        return redirect("patient:doses_today")

    total_doses = schedules.count()
    taken_doses = schedules.filter(status="taken").count()
    skipped_doses = schedules.filter(status="skipped").count()
    pending_doses = total_doses - taken_doses - skipped_doses
    completion_pct = int((taken_doses / total_doses) * 100) if total_doses else 0

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

    return render(request, "patient/doses_today.html", {
        "schedules": schedules,
        "total_doses": total_doses,
        "taken_doses": taken_doses,
        "skipped_doses": skipped_doses,
        "pending_doses": pending_doses,
        "completion_pct": completion_pct,
        "dose_history": dose_history,
    })


@login_required
def dose_track_report(request):
    patient = request.user.patient_profile
    from prescriptions.models import ReminderSchedule
    from datetime import datetime, timedelta
    from collections import defaultdict

    today = timezone.localdate()
    filter_date_str = request.GET.get('filter_date', '').strip()
    view_mode = request.GET.get('view', 'single')

    selected_date = today
    if filter_date_str:
        try:
            selected_date = datetime.strptime(filter_date_str, '%Y-%m-%d').date()
        except ValueError:
            selected_date = today

    end_date = today
    start_date = today - timedelta(days=30)

    schedules_all = ReminderSchedule.objects.filter(
        prescription_item__prescription__patient=patient,
        scheduled_date__range=(start_date, end_date)
    ).select_related('prescription_item__medicine').order_by('-scheduled_date', 'reminder_time')

    total_doses = schedules_all.count()
    taken_doses = schedules_all.filter(status='taken').count()
    skipped_doses = schedules_all.filter(status='skipped').count()
    pending_doses = schedules_all.filter(status='pending').count()
    adherence_rate = (taken_doses / total_doses * 100) if total_doses > 0 else 0

    available_dates = sorted(list(set(schedules_all.values_list('scheduled_date', flat=True))), reverse=True)

    if view_mode == 'all':
        schedules = schedules_all
    else:
        schedules = schedules_all.filter(scheduled_date=selected_date)
        if not schedules.exists() and available_dates:
            selected_date = available_dates[0]
            schedules = schedules_all.filter(scheduled_date=selected_date)

    by_date = defaultdict(list)
    for s in schedules:
        by_date[s.scheduled_date].append(s)

    if request.GET.get('export') == 'csv':
        import csv
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="dose_track_report_{selected_date}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Date', 'Medicine', 'Time', 'Status', 'Taken At'])
        for s in schedules_all:
            writer.writerow([
                s.scheduled_date,
                s.prescription_item.medicine.brand_name if s.prescription_item.medicine else 'Unknown',
                s.reminder_time,
                s.get_status_display(),
                s.taken_at.strftime('%Y-%m-%d %H:%M') if s.taken_at else ''
            ])
        return response

    return render(request, 'patient/dose_track_report.html', {
        'schedules': schedules,
        'by_date': dict(by_date),
        'available_dates': available_dates,
        'selected_date': selected_date,
        'view_mode': view_mode,
        'total_doses': total_doses,
        'taken_doses': taken_doses,
        'skipped_doses': skipped_doses,
        'pending_doses': pending_doses,
        'adherence_rate': round(adherence_rate, 1),
        'start_date': start_date,
        'end_date': end_date,
        'today': today,
    })


@login_required
def followups(request):
    patient = request.user.patient_profile
    today = timezone.localdate()

    all_followups = FollowUp.objects.filter(prescription__patient=patient).order_by("scheduled_date")

    # Auto-completion evaluator: if the doctor issued a prescription on or after follow-up date, mark completed
    for fu in all_followups:
        doc = fu.prescription.doctor
        has_rx = Prescription.objects.filter(
            doctor=doc,
            patient=patient,
            issued_at__date__gte=fu.scheduled_date
        ).exists()

        if has_rx and fu.status != "completed":
            fu.status = "completed"
            fu.save()
        elif fu.scheduled_date < today and fu.status == "upcoming":
            fu.status = "missed"
            fu.save()

    if request.method == "POST":
        followup_id = request.POST.get("followup_id")
        followup = get_object_or_404(FollowUp, pk=followup_id, prescription__patient=patient)
        
        action = request.POST.get("action")
        if action == "book":
            # Redirect to doctor booking page (carry follow-up id so it gets confirmed)
            return redirect(f"{reverse('patient:book_doctor', kwargs={'doctor_id': followup.prescription.doctor.pk})}?followup_id={followup.pk}")
        elif action == "change_date":
            # Allow patient to request date change
            new_date_str = request.POST.get("new_date", "").strip()
            if new_date_str:
                try:
                    new_date = timezone.datetime.strptime(new_date_str, "%Y-%m-%d").date()
                    if new_date >= today:
                        followup.scheduled_date = new_date
                        followup.booking_deadline = new_date + timezone.timedelta(days=4)
                        followup.save()
                        messages.success(request, f"✓ Follow-up date changed to {new_date.strftime('%d %b %Y')}. Please book before {followup.booking_deadline.strftime('%d %b %Y')}.")
                    else:
                        messages.error(request, "Follow-up date cannot be in the past.")
                except ValueError:
                    messages.error(request, "Invalid date format.")
            else:
                messages.error(request, "Please select a new date.")
        elif action == "complete":
            followup.status = "completed"
            followup.save()
            messages.success(request, "✓ Follow-up marked as completed.")
        
        return redirect("patient:follow_ups")

    upcoming = all_followups.filter(status="upcoming")
    completed = all_followups.filter(status="completed")
    missed = all_followups.filter(status="missed")
    booking_required = all_followups.filter(status="booking_required")

    return render(request, "patient/follow_ups.html", {
        "upcoming": upcoming,
        "completed": completed,
        "missed": missed,
        "booking_required": booking_required,
    })


@login_required
def notifications(request):
    from accounts.models import AppNotification
    notifications_qs = AppNotification.objects.filter(user=request.user)
    items = list(notifications_qs[:30])
    notifications_qs.filter(is_read=False).update(is_read=True)
    return render(request, "patient/notifications.html", {"items": items})


def _build_adherence_data(patient, weeks=4):
    from datetime import timedelta
    from collections import defaultdict

    today = timezone.localdate()
    current_week_start = today - timedelta(days=today.weekday())
    week_starts = sorted(
        current_week_start - timedelta(weeks=i)
        for i in range(weeks - 1, -1, -1)
    )
    week_labels = [w.strftime("%b %d") for w in week_starts]
    week_start_set = set(week_starts)

    schedules = ReminderSchedule.objects.filter(
        prescription_item__prescription__patient=patient,
        scheduled_date__gte=week_starts[0],
    ).select_related("prescription_item__medicine")

    medicine_stats = defaultdict(lambda: defaultdict(lambda: {"total": 0, "taken": 0}))
    for s in schedules:
        med_name = str(s.prescription_item.medicine)
        week_start = s.scheduled_date - timedelta(days=s.scheduled_date.weekday())
        if week_start in week_start_set:
            medicine_stats[med_name][week_start]["total"] += 1
            if s.status == "taken":
                medicine_stats[med_name][week_start]["taken"] += 1

    medicines = []
    for med_name in medicine_stats:
        data = []
        for w in week_starts:
            stats = medicine_stats[med_name].get(w, {"total": 0, "taken": 0})
            pct = round(stats["taken"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0
            data.append(pct)
        medicines.append({"name": med_name, "data": data})

    return {
        "labels": week_labels,
        "medicines": medicines,
    }


@login_required
def health_record(request):
    from patient.models import PatientHealthReport

    patient = request.user.patient_profile
    language = request.GET.get("lang") or request.session.get("site_lang") or patient.preferred_language or "en"
    today = timezone.localdate()

    # 1. Handle Self-Report Upload
    if request.method == "POST" and "upload_report" in request.POST:
        title = (request.POST.get("title") or "").strip()
        report_type = request.POST.get("report_type", "lab_test")
        date_performed = request.POST.get("date_performed") or timezone.localdate()
        doc_clinic = (request.POST.get("doctor_or_clinic_name") or "").strip()
        result_desc = (request.POST.get("result_description") or "").strip()
        doc_file = request.FILES.get("document_file")

        if title and doc_file:
            PatientHealthReport.objects.create(
                patient=patient,
                title=title,
                report_type=report_type,
                date_performed=date_performed,
                doctor_or_clinic_name=doc_clinic,
                result_description=result_desc,
                document_file=doc_file,
            )
            messages.success(request, f"✓ Health report '{title}' uploaded successfully to your health journey.")
            return redirect("patient:health_record")
        else:
            messages.error(request, "Please provide a document title and file upload.")

    # 2. Fetch Prescriptions & Uploaded Health Reports
    prescriptions = (
        Prescription.objects.filter(patient=patient)
        .select_related("doctor__user")
        .prefetch_related("items__medicine", "follow_up")
        .order_by("-issued_at")
    )
    reports = PatientHealthReport.objects.filter(patient=patient).order_by("-date_performed")

    # 3. Build Unified Chronological Health Journey Timeline
    timeline_items = []
    for rx in prescriptions:
        timeline_items.append({
            "type": "prescription",
            "date": rx.issued_at.date(),
            "title": f"Prescription by Dr. {rx.doctor.user.get_full_name() or rx.doctor.user.username}",
            "subtitle": rx.doctor.specialty or "General Specialist",
            "details": f"Diagnosis: {rx.diagnosis or 'N/A'}\nComplaints: {rx.chief_complaints or 'N/A'}\nTests: {rx.tests_investigations or 'N/A'}\nAdvice: {rx.advice_rules or 'N/A'}",
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

    # 4. Interactive AI Health Journey Assistant Q&A
    ai_answer = ""
    ai_query = (request.POST.get("ai_query") or "").strip() if (request.method == "POST" and "ai_query" in request.POST) else ""
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

    # 5. Holistic AI Summary of Health History
    history_text_summary = f"Total Medical Records: {len(timeline_items)} ({len(prescriptions)} Doctor Prescriptions, {len(reports)} Self-Uploaded Lab Tests/External Reports)."

    adherence_chart = _build_adherence_data(patient)

    prescriptions_paginator = Paginator(prescriptions, 10)
    reports_paginator = Paginator(reports, 10)
    rx_page = request.GET.get("rx_page")
    rpt_page = request.GET.get("rpt_page")
    prescriptions_page = prescriptions_paginator.get_page(rx_page)
    reports_page = reports_paginator.get_page(rpt_page)

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

    return render(request, "patient/health_record.html", {
        "prescriptions": prescriptions_page,
        "reports": reports_page,
        "timeline_items": timeline_items,
        "ai_answer": ai_answer,
        "ai_query": ai_query,
        "history_text_summary": history_text_summary,
        "ai_available": GeminiAIService.is_ai_available(),
        "adherence_chart": adherence_chart,
        "prescriptions_page": prescriptions_page,
        "reports_page": reports_page,
        "dose_history": dose_history,
    })


@login_required
def doctor_list(request):
    from accounts.models import Doctor

    query = request.GET.get("q", "")
    category = request.GET.get("category", "")

    doctors = Doctor.objects.select_related("user").filter(is_verified=True).order_by("-id")
    if query:
        doctors = doctors.filter(Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query) | Q(specialty__icontains=query))
    if category and category != "All":
        doctors = doctors.filter(specialty=category)

    categories = ["All"] + list(
        Doctor.objects.exclude(specialty="").values_list("specialty", flat=True).distinct()
    )

    paginator = Paginator(doctors, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "patient/doctor_list.html", {
        "doctors": page_obj,
        "categories": categories,
        "suggested": doctors[:2],
        "page_obj": page_obj,
    })


@login_required
def doctor_detail(request, doctor_id):
    from accounts.models import Doctor
    from urllib.parse import quote_plus

    doctor = get_object_or_404(Doctor, pk=doctor_id)
    map_query = doctor.location_text.strip()
    map_url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(map_query)}" if map_query else ""
    map_embed_url = f"https://www.google.com/maps?q={quote_plus(map_query)}&output=embed" if map_query else ""
    return render(request, "patient/doctor_detail.html", {
        "doctor": doctor,
        "map_url": map_url,
        "map_embed_url": map_embed_url,
    })


@login_required
def book_doctor(request, doctor_id):
    from doctors.models import DoctorSchedule, Appointment
    from accounts.models import Doctor, AppNotification

    doctor = get_object_or_404(Doctor, pk=doctor_id)
    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        messages.error(request, "Only patients can book appointments.")
        return redirect("patient:doctor_list")

    # If this booking originates from a follow-up, mark it confirmed once booked.
    followup_id = request.GET.get("followup_id") or request.POST.get("followup_id")
    followup = None
    if followup_id:
        followup = FollowUp.objects.filter(pk=followup_id, prescription__patient=patient).first()

    schedules = DoctorSchedule.objects.filter(doctor=doctor, is_active=True).order_by("day_of_week", "start_time")

    if request.method == "POST":
        appointment_date = request.POST.get("appointment_date")
        start_time = request.POST.get("start_time")
        consultation_type = request.POST.get("consultation_type", "in_person")
        if consultation_type not in ["in_person", "video_online"]:
            consultation_type = "in_person"
        chief_complaint = request.POST.get("chief_complaint", "").strip()

        if not appointment_date or not start_time:
            messages.error(request, "Please select date and time.")
            return redirect("patient:book_doctor", doctor_id=doctor.pk)

        # Find matching schedule to calculate end_time
        from datetime import datetime, timedelta
        apt_date = datetime.strptime(appointment_date, "%Y-%m-%d").date()
        day_name = apt_date.strftime("%A").lower()
        schedule = DoctorSchedule.objects.filter(doctor=doctor, day_of_week=day_name, is_active=True).first()
        if not schedule:
            messages.error(request, "Doctor is not available on this day.")
            return redirect("patient:book_doctor", doctor_id=doctor.pk)

        start_dt = datetime.strptime(start_time, "%H:%M").time()
        end_dt = (datetime.combine(apt_date, start_dt) + timedelta(minutes=schedule.slot_duration_minutes)).time()

        # Double-booking check
        existing = Appointment.objects.filter(
            doctor=doctor,
            appointment_date=apt_date,
            status__in=["pending", "confirmed"],
        ).filter(start_time__lt=end_dt, end_time__gt=start_dt)
        if existing.exists():
            messages.error(request, "This time slot is already booked. Please choose another.")
            return redirect("patient:book_doctor", doctor_id=doctor.pk)

        appointment = Appointment.objects.create(
            patient=patient,
            doctor=doctor,
            appointment_date=apt_date,
            start_time=start_dt,
            end_time=end_dt,
            consultation_type=consultation_type,
            chief_complaint=chief_complaint,
            status="pending",
            fee_bdt=500.00,
            platform_fee_bdt=15.00,
            net_doctor_payout_bdt=485.00,
        )

        # Notification for doctor
        AppNotification.objects.create(
            user=doctor.user,
            title="🗓️ New Appointment Booking",
            message=f"Patient {request.user.get_full_name() or request.user.email} has booked an appointment on {apt_date} at {start_dt.strftime('%H:%M')}.",
            notification_type="booking",
            link_url=reverse("doctors:patient_detail", kwargs={"patient_id": patient.pk}),
        )

        # Notification for patient
        AppNotification.objects.create(
            user=request.user,
            title="✓ Appointment Booking Request Sent",
            message=f"Your booking request with Dr. {doctor.user.get_full_name() or doctor.user.username} on {apt_date} at {start_dt.strftime('%H:%M')} has been sent.",
            notification_type="booking",
            link_url=reverse("patient:notifications"),
        )

        messages.success(request, f"Appointment booked successfully for {apt_date} at {start_dt.strftime('%H:%M')}. Please complete payment.")

        # Confirm the originating follow-up so it moves out of the booking list
        if followup and not followup.is_booking_confirmed:
            followup.is_booking_confirmed = True
            followup.save(update_fields=["is_booking_confirmed"])

        return redirect("accounts:payment_process", appointment_id=appointment.pk)

    # Generate available slots for next 14 days
    from datetime import timedelta
    from collections import OrderedDict
    today = timezone.localdate()
    now = timezone.localtime()
    min_booking_time = (now + timedelta(hours=2)).time()
    available_slots = []
    for i in range(14):
        date = today + timedelta(days=i)
        day_name = date.strftime("%A").lower()
        day_schedules = DoctorSchedule.objects.filter(doctor=doctor, day_of_week=day_name, is_active=True)
        for sch in day_schedules:
            blocked = min_booking_time if date == today else None
            slots = _generate_slots(sch.start_time, sch.end_time, sch.slot_duration_minutes, doctor, date, blocked_before_time=blocked)
            available_slots.extend(slots)

    grouped_slots = OrderedDict()
    for slot in available_slots:
        key = slot["date"]
        grouped_slots.setdefault(key, []).append(slot)
    grouped_slots = list(grouped_slots.items())

    return render(request, "patient/book_appointment.html", {
        "doctor": doctor,
        "schedules": schedules,
        "available_slots": available_slots,
        "grouped_slots": grouped_slots,
        "today": timezone.localdate(),
    })


def _generate_slots(start_time, end_time, slot_duration, doctor, date, blocked_before_time=None, exclude_appointment_id=None):
    """Generate available appointment time slots for a given doctor on a given date.

    Args:
        start_time: Clinic opening time for the day
        end_time: Clinic closing time for the day
        slot_duration: Minutes per appointment slot (e.g., 30 or 45)
        doctor: The doctor whose schedule and appointments to check
        date: The specific date for slot generation
        blocked_before_time: Optional cutoff — slots before this time are blocked
        exclude_appointment_id: ID to exclude (for edit mode, so current apt doesn't block itself)

    Returns:
        List of slot dicts with date, start/end times (AM/PM format), and availability flag.
    """
    from datetime import datetime, timedelta
    slots = []
    # Iterate through each slot from start_time to end_time
    current = datetime.combine(date, start_time)
    end = datetime.combine(date, end_time)
    while current + timedelta(minutes=slot_duration) <= end:
        slot_end = current + timedelta(minutes=slot_duration)
        # Check if any appointment is already booked for this slot (pending/confirmed only)
        is_booked = Appointment.objects.filter(
            doctor=doctor,
            appointment_date=date,
            status__in=["pending", "confirmed"],
            start_time=current.time(),
        )
        if exclude_appointment_id:
            is_booked = is_booked.exclude(pk=exclude_appointment_id)
        is_booked = is_booked.exists()
        available = not is_booked
        if available and blocked_before_time and current.time() < blocked_before_time:
            available = False
        slots.append({
            "date": date.strftime("%Y-%m-%d"),
            "start": current.strftime("%I:%M %p"),
            "end": slot_end.strftime("%I:%M %p"),
            "available": available,
        })
        current = slot_end
    return slots


@login_required
def appointments(request):
    """Display the patient's appointment history with filtering.

    Filters: status (pending/confirmed/completed/missed/cancelled), date, month, year.
    Computes a 4h prescription window countdown for each pending/confirmed appointment,
    showing the time remaining for the doctor to issue a prescription before the
    appointment window expires.
    """
    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        messages.error(request, "Only patients can view appointments.")
        return redirect("home")

    status_filter = request.GET.get("status", "")
    filter_type = request.GET.get("filter_type", "")
    filter_value = request.GET.get("filter_value", "")
    filter_month = request.GET.get("filter_month", "")
    filter_year = request.GET.get("filter_year", "")

    apts_qs = Appointment.objects.filter(patient=patient).select_related("doctor__user").order_by("-appointment_date", "-start_time")
    if status_filter:
        apts_qs = apts_qs.filter(status=status_filter)

    if filter_type == "date" and filter_value:
        apts_qs = apts_qs.filter(appointment_date=filter_value)
    elif filter_type == "month" and filter_month and filter_year:
        apts_qs = apts_qs.filter(appointment_date__startswith=f"{filter_year}-{filter_month}")
    elif filter_type == "year" and filter_year:
        apts_qs = apts_qs.filter(appointment_date__startswith=filter_year)

    today = timezone.localdate()
    for apt in apts_qs.filter(appointment_date__lt=today, status__in=["pending", "confirmed"]):
        has_prescription = Prescription.objects.filter(
            patient=patient,
            doctor=apt.doctor,
            issued_at__date__gte=apt.appointment_date,
        ).exists()
        if not has_prescription:
            apt.status = "missed"
            apt.save(update_fields=["status"])

    now = timezone.localtime(timezone.now())
    from accounts.models import SiteSettings
    booking_rule = SiteSettings.get_solo().booking_edit_rule
    enable_4h_rule = booking_rule == "enabled"
    tz = timezone.get_current_timezone()
    apts = []
    for apt in apts_qs:
        apt_datetime = timezone.make_aware(
            timezone.datetime.combine(apt.appointment_date, apt.start_time), tz
        )
        apt_end = timezone.make_aware(
            timezone.datetime.combine(apt.appointment_date, apt.end_time or apt.start_time), tz
        )
        window_end = apt_datetime + timezone.timedelta(hours=4)
        hours_until = (apt_datetime - now).total_seconds() / 3600
        apt.can_cancel = apt.status in ("pending", "confirmed") and hours_until >= 24
        if enable_4h_rule:
            apt.can_edit = apt.status == "pending" and hours_until >= 4 and apt.edit_count < 3
        else:
            apt.can_edit = apt.status == "pending" and apt.edit_count < 3
        apt.window_expired = apt.status in ("completed", "missed", "cancelled", "refunded") or (now > window_end and apt.status in ("pending", "confirmed"))
        apts.append(apt)

    paginator = Paginator(apts, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Get distinct years and months for filter dropdowns
    all_appointments = Appointment.objects.filter(patient=patient)
    date_aggregates = all_appointments.aggregate(
        min_date=Min("appointment_date"),
        max_date=Max("appointment_date"),
    )
    years = []
    months = []
    if date_aggregates["min_date"] and date_aggregates["max_date"]:
        min_year = date_aggregates["min_date"].year
        max_year = date_aggregates["max_date"].year
        years = list(range(min_year, max_year + 1))
        months = [
            ("01", "January"), ("02", "February"), ("03", "March"), ("04", "April"),
            ("05", "May"), ("06", "June"), ("07", "July"), ("08", "August"),
            ("09", "September"), ("10", "October"), ("11", "November"), ("12", "December"),
        ]

    selected_month = ""
    selected_year = ""
    if filter_type == "month" and filter_month and filter_year:
        selected_month = filter_month
        selected_year = filter_year
    elif filter_type == "year" and filter_year:
        selected_year = filter_year

    return render(request, "patient/appointments.html", {
        "patient": patient,
        "appointments": page_obj,
        "status_filter": status_filter,
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


@login_required
def appointment_detail_patient(request, appointment_id):
    patient = getattr(request.user, "patient_profile", None)
    appointment = get_object_or_404(Appointment, pk=appointment_id, patient=patient)
    tz = timezone.get_current_timezone()
    appointment_datetime = timezone.make_aware(
        timezone.datetime.combine(appointment.appointment_date, appointment.start_time), tz
    )
    appointment_end = timezone.make_aware(
        timezone.datetime.combine(appointment.appointment_date, appointment.end_time or appointment.start_time), tz
    )
    window_end = appointment_datetime + timezone.timedelta(hours=4)
    now_local = timezone.localtime(timezone.now())
    hours_until = (appointment_datetime - now_local).total_seconds() / 3600
    appointment.can_cancel = appointment.status in ("pending", "confirmed") and hours_until >= 24
    from accounts.models import SiteSettings
    enable_4h_rule = SiteSettings.get_solo().booking_edit_rule == "enabled"
    if enable_4h_rule:
        appointment.can_edit = appointment.status == "pending" and hours_until >= 4 and appointment.edit_count < 3
    else:
        appointment.can_edit = appointment.status == "pending" and appointment.edit_count < 3
    appointment.window_expired = appointment.status in ("completed", "missed", "cancelled", "refunded") or (timezone.localtime(timezone.now()) > window_end and appointment.status in ("pending", "confirmed"))
    appointment.window_end = window_end
    return render(request, "patient/appointment_detail.html", {"appointment": appointment})



from prescriptions.views import _build_prescription_pdf

@login_required
def download_prescription(request, prescription_id):
    patient = getattr(request.user, "patient_profile", None)
    prescription = get_object_or_404(Prescription, pk=prescription_id, patient=patient)
    buffer = _build_prescription_pdf(prescription)
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = f"inline; filename=prescription_{prescription.pk}.pdf"
    return response


@login_required
def patient_analytics_view(request):
    patient = request.user.patient_profile
    today = timezone.localdate()

    appointments = Appointment.objects.filter(patient=patient)
    total_appointments = appointments.count()
    completed_appointments = appointments.filter(status="completed").count()
    pending_payments = appointments.filter(payment_status="pending").count()
    total_spent = appointments.filter(payment_status="paid").aggregate(total=Sum("fee_bdt"))["total"] or Decimal("0.00")

    upcoming_appointments = appointments.filter(
        appointment_date__gte=today, status__in=["pending", "confirmed"]
    ).count()
    prescriptions_count = Prescription.objects.filter(patient=patient).count()
    follow_ups_count = FollowUp.objects.filter(prescription__patient=patient, status="upcoming").count()

    recent_appointments_qs = appointments.select_related("doctor__user").order_by("-appointment_date", "-start_time")[:50]
    recent_prescriptions_qs = Prescription.objects.filter(patient=patient).select_related("doctor__user").order_by("-issued_at")[:50]

    recent_appointments_paginator = Paginator(recent_appointments_qs, 10)
    recent_prescriptions_paginator = Paginator(recent_prescriptions_qs, 10)

    apt_page = request.GET.get("apt_page")
    rx_page = request.GET.get("rx_page")

    recent_appointments = recent_appointments_paginator.get_page(apt_page)
    recent_prescriptions = recent_prescriptions_paginator.get_page(rx_page)

    return render(request, "patient/analytics.html", {
        "total_appointments": total_appointments,
        "completed_appointments": completed_appointments,
        "total_spent": total_spent,
        "pending_payments": pending_payments,
        "upcoming_appointments": upcoming_appointments,
        "prescriptions_count": prescriptions_count,
        "follow_ups_count": follow_ups_count,
        "recent_appointments": recent_appointments,
        "recent_prescriptions": recent_prescriptions,
    })


@login_required
def patient_payment_history(request):
    patient = request.user.patient_profile
    appointments = Appointment.objects.filter(patient=patient).select_related("doctor__user").order_by("-appointment_date", "-start_time")

    import io
    from decimal import Decimal
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.pdfbase import pdfmetrics, ttfonts

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
    light_bg = colors.HexColor("#f0fdfa")

    title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=18, textColor=teal, spaceAfter=2, leading=22, fontName=pdf_font_name)
    subtitle_style = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=9, textColor=slate, spaceAfter=10, leading=12, fontName=pdf_font_name)
    header_style = ParagraphStyle("header", parent=styles["Normal"], fontSize=8, textColor=colors.white, fontName=pdf_font_name)
    cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, textColor=dark, leading=11, fontName=pdf_font_name)

    elements = []
    elements.append(Paragraph("Patient Payment & Billing History", title_style))
    elements.append(Paragraph(f"Patient: <b>{patient.user.get_full_name() or patient.user.email}</b> (#PAT-{patient.id}) | Date: <b>{timezone.localdate().strftime('%d %b %Y')}</b>", subtitle_style))

    table_data = [
        [
            Paragraph("<b>Date</b>", header_style),
            Paragraph("<b>Doctor</b>", header_style),
            Paragraph("<b>Consultation Fee</b>", header_style),
            Paragraph("<b>Refund Issued</b>", header_style),
            Paragraph("<b>Payment Status</b>", header_style),
            Paragraph("<b>Type</b>", header_style),
        ]
    ]

    total_fee = Decimal("0.00")
    total_refund = Decimal("0.00")

    for apt in appointments:
        fee = Decimal(str(apt.fee_bdt or 0))
        ref = Decimal(str(apt.refund_amount or 0))
        total_fee += fee
        total_refund += ref

        doc_name = apt.doctor.user.get_full_name() or apt.doctor.user.username
        
        table_data.append([
            Paragraph(apt.appointment_date.strftime("%d %b %Y"), cell_style),
            Paragraph(f"Dr. {doc_name}", cell_style),
            Paragraph(f"BDT {fee:,.2f}", cell_style),
            Paragraph(f"BDT {ref:,.2f}", cell_style),
            Paragraph(apt.get_payment_status_display(), cell_style),
            Paragraph(apt.get_consultation_type_display(), cell_style),
        ])

    table_data.append([
        Paragraph("<b>TOTALS</b>", cell_style),
        Paragraph("", cell_style),
        Paragraph(f"<b>BDT {total_fee:,.2f}</b>", cell_style),
        Paragraph(f"<b>BDT {total_refund:,.2f}</b>", cell_style),
        Paragraph("", cell_style),
        Paragraph("", cell_style),
    ])

    col_widths = [25 * mm, 50 * mm, 30 * mm, 30 * mm, 25 * mm, 20 * mm]
    t = Table(table_data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), teal),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.HexColor("#e7e5e4")),
        ('BACKGROUND', (0, -1), (-1, -1), light_bg),
        ('LINEABOVE', (0, -1), (-1, -1), 1, teal),
    ]))
    elements.append(t)

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'inline; filename="patient_payment_history.pdf"'
    return response


def chatbot(request):
    patient = _get_patient(request)
    prescription_id = request.GET.get("prescription_id") or request.POST.get("prescription_id")
    session_id = request.GET.get("session_id") or request.POST.get("session_id")
    
    if patient:
        session = _get_or_create_session(patient, session_id)
        qs = ChatMessage.objects.filter(patient=patient, session=session).order_by("created_at")[:50]
        formatted = [{"role": msg.role, "text": msg.content, "session": session.pk if session else None} for msg in qs]
        sessions = ChatSession.objects.filter(patient=patient).order_by("-updated_at")[:20]
    else:
        session = None
        request.session["guest_chat_messages"] = []
        request.session.modified = True
        formatted = []
        sessions = []

    if request.method == "POST" and patient:
        message = (request.POST.get("message") or "").strip()
        if message:
            language = _resolve_language(request, patient)
            ChatMessage.objects.create(patient=patient, session=session, role="user", content=message, language=language)
            history = list(ChatMessage.objects.filter(patient=patient, session=session).order_by("created_at"))
            reply = generate_patient_reply(
                question=message,
                language=language,
                patient=patient,
                history=history,
                prescription_id=prescription_id,
            )
            ChatMessage.objects.create(
                patient=patient,
                session=session,
                role="assistant",
                content=reply,
                language=language,
                ai_model_used=_get_active_ai_model(),
            )
            if session:
                session.title = session.messages.order_by("created_at").first().content[:50] if session.messages.exists() else "New Chat"
                session.save(update_fields=["title", "updated_at"])
            return redirect(f"{reverse('patient:chatbot')}?session_id={session.pk if session else ''}&prescription_id={prescription_id or ''}")

    guest_qa = []
    if not patient:
        from patient.services import GUEST_QA
        for key, qa in list(GUEST_QA.items())[:10]:
            guest_qa.append({
                "question_en": qa["en"].split("\n")[0].replace("**", "").strip(),
                "question_bn": qa["bn"].split("\n")[0].replace("**", "").strip(),
                "answer_en": qa["en"],
                "answer_bn": qa["bn"],
            })

    return render(request, "patient/chatbot.html", {
        "chat_messages": formatted,
        "sessions": sessions,
        "patient": patient,
        "prescription_id": prescription_id,
        "session_id": session_id,
        "active_session": session,
        "ai_available": GeminiAIService.is_ai_available() if patient else False,
        "active_model": _get_active_ai_model() if patient else None,
        "guest_qa": guest_qa,
    })


@require_GET
def chat_api_history(request):
    patient = _get_patient(request)
    if not patient:
        return JsonResponse({"messages": []})
    
    session_id = request.GET.get("session_id")
    
    if session_id:
        try:
            qs = ChatMessage.objects.filter(patient=patient, session_id=session_id).order_by("created_at")[:100]
        except (ValueError, TypeError):
            qs = ChatMessage.objects.filter(patient=patient).order_by("created_at")[:100]
    else:
        qs = ChatMessage.objects.filter(patient=patient).order_by("created_at")[:100]
    
    return JsonResponse({
        "messages": [
            {
                "id": msg.pk,
                "role": msg.role,
                "content": msg.content,
                "language": msg.language,
                "session": msg.session_id,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in qs
        ],
    })


@require_POST
def chat_api_send(request):
    patient = _get_patient(request)
    if not patient:
        return JsonResponse({"error": "Login required"}, status=401)

    user_message = ""
    language = _resolve_language(request, patient)
    prescription_id = None
    session_id = None
    uploaded_file = request.FILES.get("file") or request.FILES.get("image") or request.FILES.get("prescription_image")

    if "application/json" in (request.content_type or "") and request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
            user_message = (payload.get("message") or "").strip()
            language = payload.get("lang") or language
            prescription_id = payload.get("prescription_id")
            session_id = payload.get("session_id")
        except (json.JSONDecodeError, AttributeError):
            pass
    else:
        user_message = (request.POST.get("message") or "").strip()
        language = request.POST.get("lang") or language
        prescription_id = request.POST.get("prescription_id")
        session_id = request.POST.get("session_id")

    if not user_message and not uploaded_file:
        return JsonResponse({"error": "Message or uploaded document is required."}, status=400)

    user_content = user_message
    if uploaded_file:
        user_content += f" 📎 [Attached File: {uploaded_file.name}]"

    if patient:
        session = _get_or_create_session(patient, session_id)
        ChatMessage.objects.create(
            patient=patient,
            session=session,
            role="user",
            content=user_content,
            language=language,
        )

        history = list(ChatMessage.objects.filter(patient=patient, session=session).order_by("created_at"))
        reply = generate_patient_reply(
            question=user_message,
            language=language,
            patient=patient,
            history=history,
            image_file=uploaded_file,
            prescription_id=prescription_id,
        )

        assistant_msg = ChatMessage.objects.create(
            patient=patient,
            session=session,
            role="assistant",
            content=reply,
            language=language,
            ai_model_used=_get_active_ai_model(),
        )

        if session:
            session.title = session.messages.order_by("created_at").first().content[:50] if session.messages.exists() else "New Chat"
            session.save(update_fields=["title", "updated_at"])

        return JsonResponse({
            "reply": reply,
            "message_id": assistant_msg.pk,
            "session_id": session.pk if session else None,
            "language": language,
        })
    else:
        request.session["guest_chat_messages"] = []
        request.session.modified = True
        session_messages = []
        session_messages.append({"role": "user", "content": user_content, "language": language})
        
        reply = generate_patient_reply(
            question=user_message,
            language=language,
            patient=None,
            history=session_messages,
            image_file=uploaded_file,
            prescription_id=prescription_id,
        )
        session_messages.append({"role": "assistant", "content": reply, "language": language})
        
        request.session["guest_chat_messages"] = session_messages[-5:]
        request.session.modified = True

        return JsonResponse({
            "reply": reply,
            "message_id": len(session_messages),
            "session_id": None,
            "language": language,
        })



@require_POST
def chat_api_clear(request):
    patient = _get_patient(request)
    if not patient:
        return JsonResponse({"error": "Login required"}, status=401)
    
    session_id = request.POST.get("session_id")
    if session_id:
        try:
            ChatMessage.objects.filter(patient=patient, session_id=session_id).delete()
            ChatSession.objects.filter(pk=session_id, patient=patient).delete()
        except (ValueError, TypeError):
            pass
    else:
        ChatMessage.objects.filter(patient=patient).delete()
        ChatSession.objects.filter(patient=patient).delete()
    
    return JsonResponse({"ok": True})


@require_POST
def chat_api_new_session(request):
    patient = _get_patient(request)
    if not patient:
        return JsonResponse({"error": "Login required"}, status=401)
    session = ChatSession.objects.create(patient=patient, title="New Chat")
    return JsonResponse({
        "session_id": session.pk,
        "title": session.title,
        "created_at": session.created_at.isoformat(),
    })


@require_GET
def chat_api_sessions(request):
    patient = _get_patient(request)
    if not patient:
        return JsonResponse({"sessions": []})
    sessions = ChatSession.objects.filter(patient=patient).order_by("-updated_at")[:50]
    data = []
    for s in sessions:
        last_msg = s.messages.order_by("-created_at").first()
        data.append({
            "id": s.pk,
            "title": s.title,
            "updated_at": s.updated_at.isoformat(),
            "last_message": last_msg.content[:60] if last_msg else "",
            "message_count": s.messages.count(),
        })
    return JsonResponse({"sessions": data})


def chat_ui(request):
    """Gemini-like chat interface with file upload and doctor suggestions."""
    patient = _get_patient(request)
    language = _resolve_language(request, patient)
    prescription_id = request.GET.get("prescription_id") or request.POST.get("prescription_id")
    session_id = request.GET.get("session_id") or request.POST.get("session_id")

    if request.method == "POST":
        message = (request.POST.get("message") or "").strip()
        uploaded_file = request.FILES.get("file") or request.FILES.get("image") or request.FILES.get("prescription_image")

        if not message and not uploaded_file:
            return JsonResponse({"error": "Message or file required."}, status=400)

        user_content = message
        file_url = None
        if uploaded_file:
            user_content = message or f"Analyze this document: {uploaded_file.name}"
            file_url = uploaded_file.name

        if not patient:
            return JsonResponse({"error": "Login required for AI chat."}, status=401)

        session = _get_or_create_session(patient, session_id)
        ChatMessage.objects.create(
            patient=patient,
            session=session,
            role="user",
            content=user_content,
            language=language,
        )
        history = list(ChatMessage.objects.filter(patient=patient, session=session).order_by("created_at"))
        reply = generate_patient_reply(
            question=message,
            language=language,
            patient=patient,
            history=history,
            image_file=uploaded_file,
            prescription_id=prescription_id,
        )
        assistant_msg = ChatMessage.objects.create(
            patient=patient,
            session=session,
            role="assistant",
            content=reply,
            language=language,
            ai_model_used=_get_active_ai_model(),
        )
        if session:
            session.title = session.messages.order_by("created_at").first().content[:50] if session.messages.exists() else "New Chat"
            session.save(update_fields=["title", "updated_at"])
        return JsonResponse({
            "reply": reply,
            "message_id": assistant_msg.pk,
            "session_id": session.pk if session else None,
            "language": language,
            "file_url": file_url,
        })

    # GET request — render chat UI
    active_session = None
    if patient:
        if session_id:
            try:
                active_session = ChatSession.objects.filter(pk=session_id, patient=patient).first()
            except (ValueError, TypeError):
                pass
        if not active_session:
            active_session = ChatSession.objects.filter(patient=patient).order_by("-updated_at").first()
        if active_session:
            messages = ChatMessage.objects.filter(patient=patient, session=active_session).order_by("created_at")[:100]
            formatted = [{"role": msg.role, "text": msg.content, "id": msg.pk, "language": msg.language, "created_at": msg.created_at} for msg in messages]
        else:
            formatted = []
        sessions = ChatSession.objects.filter(patient=patient).order_by("-updated_at")[:50]
    else:
        session_messages = request.session.get("guest_chat_messages", [])
        formatted = [{"role": msg["role"], "text": msg["content"], "language": msg.get("language", "en")} for msg in session_messages]
        sessions = []
        active_session = None

    suggested_doctors = []
    if patient:
        from accounts.models import Doctor
        suggested_doctors = list(Doctor.objects.filter(is_verified=True).select_related("user")[:8])

    return render(request, "patient/chat_ui.html", {
        "chat_messages": formatted,
        "patient": patient,
        "language": language,
        "sessions": sessions,
        "active_session": active_session,
        "suggested_doctors": suggested_doctors,
        "prescription_id": prescription_id,
        "ai_available": GeminiAIService.is_ai_available(),
        "active_model": _get_active_ai_model(),
    })


@login_required
def request_cancellation(request, appointment_id):
    patient = request.user.patient_profile
    appointment = get_object_or_404(Appointment, pk=appointment_id, patient=patient)

    if appointment.status not in ("pending", "confirmed"):
        messages.error(request, "This appointment cannot be cancelled.")
        return redirect("patient:appointments")

    tz = timezone.get_current_timezone()
    appointment_datetime = timezone.make_aware(
        timezone.datetime.combine(appointment.appointment_date, appointment.start_time), tz
    )
    now_local = timezone.localtime(timezone.now())
    hours_until = (appointment_datetime - now_local).total_seconds() / 3600

    if hours_until < 24:
        messages.error(request, "Appointments can only be cancelled at least 24 hours before the scheduled time.")
        return redirect("patient:appointments")

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()

        if hours_until >= 24:
            appointment.status = "cancelled"
            appointment.cancellation_reason = reason

            if appointment.payment_status == "paid":
                from accounts.models import SiteSettings
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

                patient.balance = (patient.balance or Decimal("0")) + appointment.refund_amount
                patient.save(update_fields=["balance"])

                AppNotification.objects.create(
                    user=request.user,
                    title="Refund Credited to Wallet",
                    message=f"A refund of {appointment.refund_amount} BDT ({display_pct}%) has been credited to your CareBridge wallet balance for the appointment on {appointment.appointment_date}.",
                    notification_type="booking",
                    link_url=reverse("patient:appointments"),
                )

                AppNotification.objects.create(
                    user=appointment.doctor.user,
                    title="Appointment Cancelled by Patient",
                    message=f"Patient {patient.user.get_full_name()} cancelled appointment on {appointment.appointment_date}. Refund: {appointment.refund_amount} BDT ({display_pct}%) processed.",
                    notification_type="booking",
                    link_url=reverse("doctors:appointment_list"),
                )
                AppNotification.objects.create(
                    user=request.user,
                    title="Cancellation Confirmed",
                    message=f"Your appointment on {appointment.appointment_date} has been cancelled. Refund: {appointment.refund_amount} BDT ({display_pct}%) has been processed.",
                    notification_type="booking",
                    link_url=reverse("patient:appointments"),
                )
                messages.success(request, f"Appointment cancelled. {appointment.refund_amount} BDT refunded ({display_pct}%).")
            else:
                appointment.refund_status = "none"
                appointment.refund_amount = Decimal("0.00")
                appointment.save()
                messages.success(request, "Appointment cancelled successfully.")

        return redirect("patient:appointments")

    return render(request, "patient/request_cancellation.html", {"appointment": appointment})


@login_required
def edit_appointment(request, appointment_id):
    """Allow a patient to edit their own appointment within constraints.

    Constraints:
      - Appointment must be in 'pending' status (not yet confirmed)
      - Maximum 3 edits per appointment (tracked via edit_count)
      - If booking_edit_rule is 'enabled', edits must be within 4h of
        the appointment start time (prevents last-minute changes)
    """
    patient = request.user.patient_profile
    appointment = get_object_or_404(Appointment, pk=appointment_id, patient=patient)

    if appointment.status != "pending":
        messages.error(request, "Only pending appointments can be edited. Confirmed appointments cannot be changed.")
        return redirect("patient:appointments")

    if appointment.edit_count >= 3:
        messages.error(request, "You have reached the maximum of 3 edits for this booking.")
        return redirect("patient:appointments")

    from accounts.models import SiteSettings
    enable_4h_rule = SiteSettings.get_solo().booking_edit_rule == "enabled"
    if enable_4h_rule:
        tz = timezone.get_current_timezone()
        appointment_datetime = timezone.make_aware(
            timezone.datetime.combine(appointment.appointment_date, appointment.start_time), tz
        )
        now_local = timezone.localtime(timezone.now())
        hours_until = (appointment_datetime - now_local).total_seconds() / 3600
        if hours_until < 4:
            messages.error(request, "Appointments can only be edited at least 4 hours before the scheduled time.")
            return redirect("patient:appointments")

    if request.method == "POST":
        new_date = request.POST.get("appointment_date", "").strip()
        new_start_time = request.POST.get("start_time", "").strip()
        new_consultation_type = request.POST.get("consultation_type", appointment.consultation_type)

        if not new_date or not new_start_time:
            messages.error(request, "Please select both date and time.")
            return redirect("patient:edit_appointment", appointment_id=appointment.pk)

        if new_consultation_type not in ["in_person", "video_online"]:
            new_consultation_type = "in_person"

        from datetime import datetime, timedelta
        apt_date = datetime.strptime(new_date, "%Y-%m-%d").date()
        day_name = apt_date.strftime("%A").lower()
        schedule = DoctorSchedule.objects.filter(doctor=appointment.doctor, day_of_week=day_name, is_active=True).first()
        if not schedule:
            messages.error(request, "Doctor is not available on this day.")
            return redirect("patient:edit_appointment", appointment_id=appointment.pk)

        start_dt = datetime.strptime(new_start_time, "%H:%M").time()
        end_dt = (datetime.combine(apt_date, start_dt) + timedelta(minutes=schedule.slot_duration_minutes)).time()

        existing = Appointment.objects.filter(
            doctor=appointment.doctor,
            appointment_date=apt_date,
            status__in=["pending", "confirmed"],
        ).filter(start_time__lt=end_dt, end_time__gt=start_dt).exclude(pk=appointment.pk)
        if existing.exists():
            messages.error(request, "This time slot is already booked. Please choose another.")
            return redirect("patient:edit_appointment", appointment_id=appointment.pk)

        old_date = appointment.appointment_date
        old_time = appointment.start_time.strftime("%H:%M")
        appointment.appointment_date = apt_date
        appointment.start_time = start_dt
        appointment.end_time = end_dt
        appointment.consultation_type = new_consultation_type
        appointment.edit_count += 1
        appointment.save(update_fields=["appointment_date", "start_time", "end_time", "consultation_type", "edit_count"])

        AppNotification.objects.create(
            user=appointment.doctor.user,
            title="Appointment Rescheduled by Patient",
            message=f"Patient {patient.user.get_full_name()} changed appointment from {old_date} {old_time} to {apt_date} {start_dt.strftime('%H:%M')}. Edit count: {appointment.edit_count}/3.",
            notification_type="booking",
            link_url=reverse("doctors:appointment_list"),
        )
        AppNotification.objects.create(
            user=request.user,
            title="Appointment Updated",
            message=f"Your appointment with Dr. {appointment.doctor.user.get_full_name()} has been updated to {apt_date} {start_dt.strftime('%H:%M')}.",
            notification_type="booking",
            link_url=reverse("patient:appointments"),
        )

        messages.success(request, f"Appointment updated successfully. Edit count: {appointment.edit_count}/3.")
        return redirect("patient:appointments")

    schedules = DoctorSchedule.objects.filter(doctor=appointment.doctor, is_active=True).order_by("day_of_week", "start_time")
    available_slots = []
    from datetime import timedelta
    today = timezone.localdate()
    for i in range(14):
        date = today + timedelta(days=i)
        day_name = date.strftime("%A").lower()
        day_schedules = DoctorSchedule.objects.filter(doctor=appointment.doctor, day_of_week=day_name, is_active=True)
        for sch in day_schedules:
            slots = _generate_slots(sch.start_time, sch.end_time, sch.slot_duration_minutes, appointment.doctor, date, exclude_appointment_id=appointment.pk)
            available_slots.extend(slots)

    return render(request, "patient/edit_appointment.html", {
        "appointment": appointment,
        "doctor": appointment.doctor,
        "schedules": schedules,
        "available_slots": available_slots,
        "edit_count": appointment.edit_count,
    })


@login_required
def reports(request):
    from datetime import datetime
    from doctors.models import Appointment
    from carebridge.reports_utils import (
        compute_appointment_report,
        export_report_xlsx,
        export_report_pdf,
    )

    patient = request.user.patient_profile
    export_format = request.GET.get("export")
    status_filter = request.GET.get("status", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()
    doctor_filter = request.GET.get("doctor", "").strip()
    consultation_filter = request.GET.get("consultation_type", "").strip()
    payment_filter = request.GET.get("payment_status", "").strip()

    base_qs = Appointment.objects.filter(patient=patient).select_related("patient__user", "doctor__user")
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
        base_qs = base_qs.filter(doctor__pk=doctor_filter)
    if consultation_filter:
        base_qs = base_qs.filter(consultation_type=consultation_filter)
    if payment_filter:
        base_qs = base_qs.filter(payment_status=payment_filter)

    if export_format == "pdf":
        metrics = compute_appointment_report(base_qs)
        return export_report_pdf(
            base_qs,
            metrics,
            f"CareBridge Patient Report — {request.user.get_full_name() or request.user.email}",
            "patient_report.pdf",
            owner_type="patient",
        )

    metrics = compute_appointment_report(base_qs)
    all_doctors = Doctor.objects.filter(is_verified=True).order_by("user__first_name")
    return render(request, "patient/reports.html", {
        "metrics": metrics,
        "status_filter": status_filter,
        "start_date": start_date,
        "end_date": end_date,
        "status_choices": Appointment.STATUS_CHOICES,
        "patient_name": request.user.get_full_name() or request.user.email,
        "balance": patient.balance,
        "all_doctors": all_doctors,
        "doctor_filter": doctor_filter,
        "consultation_filter": consultation_filter,
        "payment_filter": payment_filter,
        "consultation_choices": Appointment.TYPE_CHOICES,
        "payment_choices": Appointment.PAYMENT_STATUS_CHOICES,
    })


@login_required
def overall_report(request):
    from datetime import datetime
    import io

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        HAS_MATPLOTLIB = True
    except ImportError:
        HAS_MATPLOTLIB = False

    from doctors.models import Appointment
    from patient.models import MedicalHistory, PatientVisit, PatientHealthReport
    from prescriptions.models import Prescription
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.pdfbase import pdfmetrics, ttfonts

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

    patient = _get_patient(request)
    if not patient:
        messages.error(request, "Please log in as a patient.")
        return redirect("home")

    export_format = request.GET.get("export")
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()

    appointments = Appointment.objects.filter(patient=patient).select_related("doctor__user").order_by("-appointment_date")
    visits = patient.visits.select_related("doctor__user").order_by("-visited_at")
    prescriptions = Prescription.objects.filter(patient=patient).select_related("doctor__user").prefetch_related("items__medicine").order_by("-issued_at")
    medical_history = getattr(patient, "medical_history", None)
    health_reports = patient.health_reports.all().order_by("-date_performed")

    summary_language = request.GET.get("lang") or request.session.get("site_lang") or "en"

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

    recent_visits = visits[:5]
    if recent_visits:
        history_parts.append("Recent Visits:")
        for v in recent_visits:
            vitals = []
            if v.heart_rate: vitals.append(f"HR {v.heart_rate} bpm")
            if v.blood_pressure_systolic and v.blood_pressure_diastolic: vitals.append(f"BP {v.blood_pressure_systolic}/{v.blood_pressure_diastolic} mmHg")
            if v.temperature_celsius: vitals.append(f"Temp {v.temperature_celsius}°C")
            if v.weight_kg: vitals.append(f"Weight {v.weight_kg} kg")
            if v.height_cm: vitals.append(f"Height {v.height_cm} cm")
            if v.oxygen_saturation: vitals.append(f"SpO2 {v.oxygen_saturation}%")
            vitals_str = ", ".join(vitals) if vitals else "No vitals recorded"
            history_parts.append(f"- {v.visited_at.strftime('%Y-%m-%d')}: {vitals_str} with Dr. {v.doctor.user.get_full_name() or v.doctor.user.username}")

    recent_prescriptions = prescriptions[:5]
    if recent_prescriptions:
        history_parts.append("Recent Prescriptions:")
        for rx in recent_prescriptions:
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
    if recent_visits:
        latest = recent_visits.first()
        if latest.heart_rate: metrics_parts.append(f"Heart rate: {latest.heart_rate} bpm")
        if latest.blood_pressure_systolic and latest.blood_pressure_diastolic: metrics_parts.append(f"BP: {latest.blood_pressure_systolic}/{latest.blood_pressure_diastolic} mmHg")
        if latest.temperature_celsius: metrics_parts.append(f"Temperature: {latest.temperature_celsius}°C")
        if latest.weight_kg: metrics_parts.append(f"Weight: {latest.weight_kg} kg")
        if latest.height_cm: metrics_parts.append(f"Height: {latest.height_cm} cm")
        if latest.oxygen_saturation: metrics_parts.append(f"SpO2: {latest.oxygen_saturation}%")
    metrics_summary = "; ".join(metrics_parts) if metrics_parts else "No recent vitals on file."

    ai_summary = GeminiAIService.generate_clinical_summary(
        patient_name=patient.user.get_full_name() or patient.user.email,
        history_text=history_text,
        metrics_summary=metrics_summary,
        language=summary_language,
    )

    if start_date:
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d").date()
            appointments = appointments.filter(appointment_date__gte=sd)
            visits = visits.filter(visited_at__date__gte=sd)
            prescriptions = prescriptions.filter(issued_at__date__gte=sd)
            health_reports = health_reports.filter(date_performed__gte=sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, "%Y-%m-%d").date()
            appointments = appointments.filter(appointment_date__lte=ed)
            visits = visits.filter(visited_at__date__lte=ed)
            prescriptions = prescriptions.filter(issued_at__date__lte=ed)
            health_reports = health_reports.filter(date_performed__lte=ed)
        except ValueError:
            pass

    if export_format == "pdf":
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm, leftMargin=18 * mm, rightMargin=18 * mm)
        styles = getSampleStyleSheet()
        teal = colors.HexColor("#0f766e")
        dark = colors.HexColor("#1c1917")
        slate = colors.HexColor("#57534e")
        light_bg = colors.HexColor("#f0fdfa")
        line = colors.HexColor("#e7e5e4")
        title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=18, textColor=teal, spaceAfter=6, leading=22, fontName=pdf_font_name)
        heading_style = ParagraphStyle("heading", parent=styles["Heading3"], fontSize=12, textColor=teal, spaceAfter=6, spaceBefore=10, leading=16, fontName=pdf_font_name)
        normal_style = ParagraphStyle("normal", parent=styles["Normal"], fontSize=9, leading=13, textColor=dark, fontName=pdf_font_name)
        small_style = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=11, textColor=slate, fontName=pdf_font_name)
        elements = []

        logo_path = os.path.join(settings.BASE_DIR, "carebridge", "static", "images", "logo.png")
        if os.path.exists(logo_path):
            elements.append(Image(logo_path, width=16 * mm, height=16 * mm))
            elements.append(Spacer(1, 4))

        elements.append(Paragraph("Overall Medical Summary Report", title_style))
        elements.append(Paragraph(f"Patient: {patient.user.get_full_name() or patient.user.email} | Generated: {timezone.localtime(timezone.now()).strftime('%d %b %Y, %I:%M %p')}", small_style))
        elements.append(Spacer(1, 8))

        demo_data = [
            [Paragraph("<b>Name</b>", normal_style), Paragraph(patient.user.get_full_name() or patient.user.email, normal_style),
             Paragraph("<b>Gender</b>", normal_style), Paragraph(patient.gender or "N/A", normal_style)],
            [Paragraph("<b>Age</b>", normal_style), Paragraph(str(calculate_age(patient.date_of_birth)) if patient.date_of_birth else "N/A", normal_style),
             Paragraph("<b>District</b>", normal_style), Paragraph(patient.district or "N/A", normal_style)],
            [Paragraph("<b>Phone</b>", normal_style), Paragraph(patient.phone_number or "N/A", normal_style),
             Paragraph("<b>Member Since</b>", normal_style), Paragraph(patient.user.date_joined.strftime("%Y-%m-%d"), normal_style)],
        ]
        demo_table = Table(demo_data, colWidths=[28 * mm, 52 * mm, 28 * mm, 52 * mm])
        demo_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), light_bg), ('BACKGROUND', (2, 0), (2, -1), light_bg),
            ('TEXTCOLOR', (0, 0), (-1, -1), dark), ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, line),
        ]))
        elements.append(Paragraph("Patient Demographics", heading_style))
        elements.append(demo_table)
        elements.append(Spacer(1, 10))

        if medical_history and (medical_history.chronic_conditions or medical_history.allergies or medical_history.past_surgeries or medical_history.family_medical_history):
            hist_data = [[Paragraph("<b>Patient Medical History</b>", normal_style), ""]]
            if medical_history.chronic_conditions:
                hist_data.append([Paragraph("<b>Chronic Conditions</b>", normal_style), Paragraph(medical_history.chronic_conditions, normal_style)])
            if medical_history.allergies:
                hist_data.append([Paragraph("<b>Allergies</b>", normal_style), Paragraph(medical_history.allergies, normal_style)])
            if medical_history.past_surgeries:
                hist_data.append([Paragraph("<b>Past Surgeries</b>", normal_style), Paragraph(medical_history.past_surgeries, normal_style)])
            if medical_history.family_medical_history:
                hist_data.append([Paragraph("<b>Family History</b>", normal_style), Paragraph(medical_history.family_medical_history, normal_style)])
            hist_table = Table(hist_data, colWidths=[40 * mm, 60 * mm])
            hist_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#b45309")), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('GRID', (0, 0), (-1, -1), 0.5, line), ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#fffbeb")]),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8), ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]))
            elements.append(Paragraph("Medical History", heading_style))
            elements.append(hist_table)
            elements.append(Spacer(1, 8))

        if visits.exists():
            vitals_data = [[Paragraph("<b>Date</b>", normal_style), Paragraph("<b>HR</b>", normal_style), Paragraph("<b>BP</b>", normal_style), Paragraph("<b>Temp</b>", normal_style), Paragraph("<b>Weight</b>", normal_style), Paragraph("<b>Height</b>", normal_style), Paragraph("<b>SpO2</b>", normal_style), Paragraph("<b>Doctor</b>", normal_style)]]
            for v in visits[:20]:
                vitals_data.append([
                    Paragraph(v.visited_at.strftime("%Y-%m-%d"), normal_style),
                    Paragraph(str(v.heart_rate) if v.heart_rate else "—", normal_style),
                    Paragraph(f"{v.blood_pressure_systolic}/{v.blood_pressure_diastolic}" if v.blood_pressure_systolic else "—", normal_style),
                    Paragraph(str(v.temperature_celsius) if v.temperature_celsius else "—", normal_style),
                    Paragraph(str(v.weight_kg) if v.weight_kg else "—", normal_style),
                    Paragraph(str(v.height_cm) if v.height_cm else "—", normal_style),
                    Paragraph(str(v.oxygen_saturation) if v.oxygen_saturation else "—", normal_style),
                    Paragraph(v.doctor.user.get_full_name() or v.doctor.user.username, normal_style),
                ])
            vitals_table = Table(vitals_data, colWidths=[22*mm, 16*mm, 22*mm, 18*mm, 18*mm, 16*mm, 16*mm, 28*mm])
            vitals_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1e40af")), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, line), ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#eff6ff")]),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6), ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            elements.append(Paragraph("Visit Vitals History", heading_style))
            elements.append(vitals_table)
            elements.append(Spacer(1, 8))

        if prescriptions.exists():
            rx_data = [[Paragraph("<b>Date</b>", normal_style), Paragraph("<b>Doctor</b>", normal_style), Paragraph("<b>Diagnosis</b>", normal_style), Paragraph("<b>Medicines</b>", normal_style)]]
            for rx in prescriptions[:15]:
                meds = ", ".join([item.medicine.brand_name for item in rx.items.all()[:3]])
                if rx.items.count() > 3:
                    meds += "..."
                rx_data.append([
                    Paragraph(rx.issued_at.strftime("%Y-%m-%d"), normal_style),
                    Paragraph(rx.doctor.user.get_full_name() or rx.doctor.user.username, normal_style),
                    Paragraph(rx.diagnosis or rx.chief_complaints or "—", normal_style),
                    Paragraph(meds or "—", normal_style),
                ])
            rx_table = Table(rx_data, colWidths=[22*mm, 32*mm, 40*mm, 56*mm])
            rx_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), teal), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, line), ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdfa")]),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6), ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            elements.append(Paragraph("Prescriptions History", heading_style))
            elements.append(rx_table)
            elements.append(Spacer(1, 8))

        if appointments.exists() and HAS_MATPLOTLIB:
            status_counts = {
                "completed": appointments.filter(status="completed").count(),
                "missed": appointments.filter(status="missed").count(),
                "cancelled": appointments.filter(status="cancelled").count(),
                "pending": appointments.filter(status="pending").count(),
                "confirmed": appointments.filter(status="confirmed").count(),
            }
            fig, ax = plt.subplots(figsize=(6, 3))
            labels = [k for k, v in status_counts.items() if v > 0]
            sizes = [v for v in status_counts.values() if v > 0]
            colors_pie = ["#0d9488", "#e11d48", "#f97316", "#f59e0b", "#14b8a6"]
            ax.pie(sizes, labels=labels, colors=colors_pie[:len(labels)], autopct="%1.0f%%", startangle=90)
            ax.set_title("Appointment Status Distribution")
            chart_buf = io.BytesIO()
            plt.tight_layout()
            plt.savefig(chart_buf, format="png", dpi=150, bbox_inches="tight")
            plt.close(fig)
            chart_buf.seek(0)

            elements.append(Paragraph("Appointment Analytics", heading_style))
            elements.append(Image(chart_buf, width=80 * mm, height=40 * mm))
            elements.append(Spacer(1, 8))
        elif appointments.exists():
            elements.append(Paragraph("Appointment Analytics", heading_style))
            elements.append(Paragraph("Charts require matplotlib. Install it to view visualizations.", small_style))
            elements.append(Spacer(1, 8))

        elements.append(Spacer(1, 12))
        elements.append(Table([['']], colWidths=[150 * mm], rowHeights=[1], style=TableStyle([('LINEBELOW', (0, 0), (-1, 0), 1, line)])))
        elements.append(Spacer(1, 4))

        if ai_summary:
            elements.append(Paragraph("AI Overall Health Assessment", heading_style))
            ai_text = ai_summary.replace("\n", "<br/>")
            ai_table_data = [[Paragraph(ai_text, normal_style)]]
            ai_table = Table(ai_table_data, colWidths=[150 * mm])
            ai_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f0fdfa")),
                ('BOX', (0, 0), (-1, -1), 0.5, line),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            elements.append(ai_table)
            elements.append(Spacer(1, 8))

        elements.append(Paragraph(f"Generated by CareBridge AI Clinical Network on {timezone.localtime(timezone.now()).strftime('%d %b %Y, %I:%M %p')}", small_style))
        elements.append(Paragraph("Confidential — For authorized medical use only", small_style))

        doc.build(elements)
        buffer.seek(0)
        return HttpResponse(buffer.read(), content_type="application/pdf")

    context = {
        "appointments": appointments[:50],
        "visits": visits[:20],
        "prescriptions": prescriptions[:20],
        "medical_history": medical_history,
        "health_reports": health_reports[:10],
        "patient": patient,
        "patient_age": calculate_age(patient.date_of_birth),
        "start_date": start_date,
        "end_date": end_date,
        "appointment_status_counts": {
            "completed": appointments.filter(status="completed").count(),
            "missed": appointments.filter(status="missed").count(),
            "cancelled": appointments.filter(status="cancelled").count(),
            "pending": appointments.filter(status="pending").count(),
            "confirmed": appointments.filter(status="confirmed").count(),
        },
        "ai_summary": ai_summary,
        "summary_language": summary_language,
    }
    return render(request, "patient/overall_report.html", context)


def calculate_age(date_of_birth):
    if not date_of_birth:
        return None
    today = timezone.localdate()
    return today.year - date_of_birth.year - ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))