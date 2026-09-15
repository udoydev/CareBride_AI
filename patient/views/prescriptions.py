from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import never_cache_auth
from prescriptions.models import FollowUp, Prescription, ReminderSchedule
from prescriptions.views import _build_prescription_pdf


def _ensure_dose_schedules(patient):
    from prescriptions.models import Prescription, ReminderSchedule, get_active_dose_slots
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


@never_cache_auth
@login_required
def prescription_detail(request, prescription_id):
    patient = getattr(request.user, "patient_profile", None)
    prescription = get_object_or_404(Prescription, pk=prescription_id, patient=patient)

    items = prescription.items.select_related("medicine").prefetch_related("reminder_schedules")
    follow_up = getattr(prescription, "follow_up", None)

    from patient.services import summarize_prescription
    ai_summary = summarize_prescription(prescription, language=patient.preferred_language if patient else "bn")

    return render(
        request,
        "patient/prescription_detail.html",
        {
            "prescription": prescription,
            "items": items,
            "follow_up": follow_up,
            "ai_summary": ai_summary,
        },
    )


@never_cache_auth
@login_required
def download_prescription(request, prescription_id):
    patient = getattr(request.user, "patient_profile", None)
    prescription = get_object_or_404(Prescription, pk=prescription_id, patient=patient)

    pdf_buffer = _build_prescription_pdf(prescription)

    response = HttpResponse(pdf_buffer.getvalue(), content_type="application/pdf")
    filename = f"Prescription_{prescription.pk}_{prescription.doctor.user.first_name}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@never_cache_auth
@login_required
def doses_today(request):
    patient = getattr(request.user, "patient_profile", None)

    _ensure_dose_schedules(patient)
    today = timezone.localdate()

    if request.method == "POST":
        schedule_id = request.POST.get("schedule_id")
        action = request.POST.get("action")

        sched = get_object_or_404(ReminderSchedule, pk=schedule_id, prescription_item__prescription__patient=patient)
        if action in ["taken", "skipped", "missed"]:
            sched.status = action
            sched.save()
            messages.success(request, f"Dose marked as {action}.")
        return redirect("patient:doses_today")

    schedules = ReminderSchedule.objects.filter(
        prescription_item__prescription__patient=patient,
        scheduled_date=today,
    ).select_related("prescription_item__medicine", "prescription_item__prescription__doctor__user").order_by("reminder_time")

    return render(request, "patient/doses_today.html", {
        "schedules": schedules,
        "today": today,
    })


@never_cache_auth
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
        "patient": patient,
        "current_times": current_times,
    })


@never_cache_auth
@login_required
def followups(request):
    patient = getattr(request.user, "patient_profile", None)

    followups_qs = FollowUp.objects.filter(
        prescription__patient=patient
    ).select_related("prescription__doctor__user").order_by("-scheduled_date")

    paginator = Paginator(followups_qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "patient/followups.html", {
        "followups": page_obj,
        "page_obj": page_obj,
    })
