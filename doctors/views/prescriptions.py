import os
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import never_cache_auth
from accounts.models import Patient
from doctors.models import Appointment
from prescriptions.models import FollowUp, Medicine, Prescription, PrescriptionItem, ReminderSchedule


@never_cache_auth
@login_required
def create_prescription(request, patient_id):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Only verified doctor profiles can write prescriptions.")
        return redirect("doctors:dashboard")

    patient = get_object_or_404(Patient, pk=patient_id)
    today = timezone.localdate()
    now = timezone.localtime(timezone.now())
    tz = timezone.get_current_timezone()

    todays_appointments = Appointment.objects.filter(
        doctor=doctor,
        patient=patient,
        appointment_date=today,
        status__in=["pending", "confirmed"],
    ).order_by("start_time")

    matching_appointment = None
    for apt in todays_appointments:
        apt_start = timezone.make_aware(timezone.datetime.combine(apt.appointment_date, apt.start_time), tz)
        window_start = apt_start - timezone.timedelta(hours=4)
        window_end = apt_start + timezone.timedelta(hours=4)
        if window_start <= now <= window_end and not Prescription.objects.filter(appointment=apt).exists():
            matching_appointment = apt
            break

    active_followup = FollowUp.objects.filter(
        prescription__doctor=doctor,
        prescription__patient=patient,
        status="upcoming",
        scheduled_date=today,
    ).first()

    if not matching_appointment and not active_followup and not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, f"Prescriptions can only be created during an active appointment window (±4 hours) or scheduled follow-up date for {patient.user.get_full_name()}.")
        return redirect("doctors:patient_detail", patient_id=patient.pk)

    medicines = Medicine.objects.all().order_by("brand_name")

    if request.method == "POST":
        chief_complaints = request.POST.get("chief_complaints", "").strip()
        diagnosis = request.POST.get("diagnosis", "").strip()
        doctor_notes = (request.POST.get("doctor_notes") or request.POST.get("clinical_notes") or "").strip()
        next_visit = request.POST.get("follow_up_date") or request.POST.get("next_visit_date") or ""
        next_visit = next_visit.strip()

        # Combine tests investigations
        test_names = request.POST.getlist("test_name[]")
        tests_investigations = "\n".join([t.strip() for t in test_names if t.strip()])

        # Combine advice rules
        advice_rules_list = request.POST.getlist("advice_rule[]")
        advice_rules = (request.POST.get("advice_rules") or "\n".join([a.strip() for a in advice_rules_list if a.strip()]) or request.POST.get("advice") or "").strip()

        next_followup = None
        if next_visit:
            try:
                next_followup = datetime.strptime(next_visit, "%Y-%m-%d").date()
            except ValueError:
                pass

        activates_at_raw = request.POST.get("activates_at", "").strip()
        expires_at_raw = request.POST.get("expires_at", "").strip()

        activates_at = None
        expires_at = None
        tz = timezone.get_current_timezone()

        if activates_at_raw:
            try:
                naive_dt = datetime.strptime(activates_at_raw, "%Y-%m-%dT%H:%M")
                activates_at = timezone.make_aware(naive_dt, tz)
            except ValueError:
                pass

        if expires_at_raw:
            try:
                naive_dt = datetime.strptime(expires_at_raw, "%Y-%m-%dT%H:%M")
                expires_at = timezone.make_aware(naive_dt, tz)
            except ValueError:
                pass

        status = "scheduled" if (activates_at and activates_at > now) else "active"

        prescription = Prescription.objects.create(
            doctor=doctor,
            patient=patient,
            appointment=matching_appointment,
            chief_complaints=chief_complaints,
            diagnosis=diagnosis,
            tests_investigations=tests_investigations,
            advice_rules=advice_rules,
            doctor_notes=doctor_notes,
            next_followup_date=next_followup,
            status=status,
            activates_at=activates_at,
            expires_at=expires_at,
            is_locked=False,
        )

        # Update patient demographics if provided
        patient_age = request.POST.get("patient_age", "").strip()
        patient_gender = request.POST.get("patient_gender", "").strip()
        patient_email = request.POST.get("patient_email", "").strip()
        patient_phone = request.POST.get("patient_phone", "").strip()

        patient_updated = False
        if patient_gender and (not patient.gender or patient.gender.lower() != patient_gender.lower()):
            patient.gender = patient_gender.capitalize()
            patient_updated = True
        if patient_phone and patient.phone_number != patient_phone:
            patient.phone_number = patient_phone
            patient_updated = True
        if patient_age and patient_age.isdigit():
            age_int = int(patient_age)
            if age_int >= 0 and (patient.age is None or patient.age != age_int):
                today = timezone.localdate()
                if patient.date_of_birth:
                    try:
                        patient.date_of_birth = patient.date_of_birth.replace(year=today.year - age_int)
                    except ValueError:
                        patient.date_of_birth = datetime(today.year - age_int, patient.date_of_birth.month, 28).date()
                else:
                    patient.date_of_birth = datetime(today.year - age_int, 1, 1).date()
                patient_updated = True
        if patient_updated:
            patient.save()

        if patient_email and patient.user.email != patient_email:
            patient.user.email = patient_email
            patient.user.save(update_fields=["email"])

        if matching_appointment:
            matching_appointment.status = "completed"
            matching_appointment.save(update_fields=["status"])

        # Record patient visit vitals if provided
        h_rate = request.POST.get("heart_rate")
        bp_sys = request.POST.get("blood_pressure_systolic")
        bp_dia = request.POST.get("blood_pressure_diastolic")
        temp_c = request.POST.get("temperature_celsius")
        weight = request.POST.get("weight_kg")
        spo2 = request.POST.get("oxygen_saturation")
        visit_notes = request.POST.get("visit_notes", "").strip()

        # Height can be provided in ft/in or cm
        h_cm = request.POST.get("height_cm", "").strip()
        h_ft = request.POST.get("height_ft", "").strip()
        h_in = request.POST.get("height_in", "").strip()
        final_height_cm = None
        if h_ft or h_in:
            try:
                ft_val = float(h_ft) if h_ft else 0
                in_val = float(h_in) if h_in else 0
                if ft_val > 0 or in_val > 0:
                    final_height_cm = int(round((ft_val * 12 + in_val) * 2.54))
            except (ValueError, TypeError):
                pass
        if not final_height_cm and h_cm:
            try:
                final_height_cm = int(round(float(h_cm)))
            except (ValueError, TypeError):
                pass

        if any([h_rate, bp_sys, bp_dia, temp_c, weight, final_height_cm, spo2, visit_notes]):
            try:
                from patient.models import PatientVisit
                visit = None
                if matching_appointment:
                    visit = getattr(matching_appointment, "visit", None)
                if not visit:
                    visit = PatientVisit.objects.filter(prescription=prescription).first()
                if not visit:
                    visit = PatientVisit(patient=patient, doctor=doctor, appointment=matching_appointment, prescription=prescription)
                else:
                    visit.prescription = prescription
                    if not visit.doctor:
                        visit.doctor = doctor
                    if matching_appointment and not visit.appointment:
                        visit.appointment = matching_appointment

                if h_rate and h_rate.isdigit():
                    visit.heart_rate = int(h_rate)
                if bp_sys and bp_sys.isdigit():
                    visit.blood_pressure_systolic = int(bp_sys)
                if bp_dia and bp_dia.isdigit():
                    visit.blood_pressure_diastolic = int(bp_dia)
                if temp_c:
                    try:
                        visit.temperature_celsius = float(temp_c)
                    except ValueError:
                        pass
                if weight:
                    try:
                        visit.weight_kg = float(weight)
                    except ValueError:
                        pass
                if final_height_cm:
                    visit.height_cm = final_height_cm
                if spo2 and spo2.isdigit():
                    visit.oxygen_saturation = int(spo2)
                if visit_notes:
                    visit.visit_notes = visit_notes
                visit.save()
            except Exception as err:
                logger.warning(f"Could not record PatientVisit in create_prescription: {err}")

        med_names = request.POST.getlist("med_name[]") or request.POST.getlist("medicine_name[]")
        med_ids = request.POST.getlist("medicine_id[]")
        dosages = request.POST.getlist("med_dosage[]") or request.POST.getlist("dosage[]")
        freqs = request.POST.getlist("med_frequency[]") or request.POST.getlist("frequency[]")
        timings = request.POST.getlist("med_timing[]") or request.POST.getlist("timing[]")
        durations = request.POST.getlist("med_duration[]") or request.POST.getlist("duration_days[]")
        notes_list = request.POST.getlist("med_notes[]") or request.POST.getlist("instructions[]")

        items_count = max(len(med_names), len(med_ids))
        for idx in range(items_count):
            med_name = med_names[idx].strip() if idx < len(med_names) else ""
            med_id = med_ids[idx] if idx < len(med_ids) else None

            med_obj = None
            if med_id and str(med_id).isdigit():
                med_obj = Medicine.objects.filter(pk=int(med_id)).first()
            if not med_obj and med_name:
                med_obj = (
                    Medicine.objects.filter(brand_name__iexact=med_name).first() or
                    Medicine.objects.filter(generic_name__iexact=med_name).first() or
                    Medicine.objects.filter(brand_name__icontains=med_name).first()
                )
                if not med_obj:
                    med_obj = Medicine.objects.create(
                        brand_name=med_name,
                        generic_name=med_name,
                        form="Tablet",
                    )

            if med_obj:
                d_val = dosages[idx].strip() if (idx < len(dosages) and dosages[idx].strip()) else "1+0+1"

                raw_f = freqs[idx] if idx < len(freqs) else "1"
                try:
                    f_val = int(raw_f)
                except ValueError:
                    f_val = 1

                timing_val = timings[idx] if idx < len(timings) else "after_meal"
                if timing_val not in ["before_meal", "after_meal", "with_meal", "anytime"]:
                    timing_val = "after_meal"

                raw_dur = durations[idx] if idx < len(durations) else "7"
                try:
                    dur_val = int(raw_dur)
                except ValueError:
                    dur_val = 7

                inst_val = notes_list[idx].strip() if idx < len(notes_list) else ""

                p_item = PrescriptionItem.objects.create(
                    prescription=prescription,
                    medicine=med_obj,
                    dosage=d_val,
                    frequency=f_val,
                    timing_relation_to_meal=timing_val,
                    duration_days=dur_val,
                    special_instructions=inst_val,
                )

                from prescriptions.models import get_active_dose_slots
                dose_slots = get_active_dose_slots(d_val, frequency=f_val)
                today = timezone.localdate()
                for day_offset in range(dur_val):
                    sch_date = today + timezone.timedelta(days=day_offset)
                    for slot in dose_slots:
                        t_str = slot.get("time")
                        if t_str:
                            try:
                                t_obj = datetime.strptime(t_str, "%H:%M:%S").time()
                            except ValueError:
                                t_obj = None
                            ReminderSchedule.objects.create(
                                prescription_item=p_item,
                                scheduled_date=sch_date,
                                reminder_time=t_obj,
                                status="pending",
                            )

        if active_followup and active_followup.status != "completed":
            active_followup.status = "completed"
            active_followup.save(update_fields=["status"])

        if next_followup:
            followup, _ = FollowUp.objects.get_or_create(prescription=prescription, defaults={"scheduled_date": next_followup})
            followup.scheduled_date = next_followup
            followup.status = "upcoming"
            followup.save()

        messages.success(request, "Prescription saved and issued successfully.")
        return redirect("doctors:prescription_detail", prescription_id=prescription.pk)

    return render(
        request,
        "doctors/create_prescription.html",
        {
            "doctor": doctor,
            "patient": patient,
            "medicines": medicines,
            "matching_appointment": matching_appointment,
            "active_followup": active_followup,
            "now_str": now.strftime("%Y-%m-%dT%H:%M"),
        },
    )


@never_cache_auth
@login_required
def edit_prescription(request, prescription_id):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("doctors:dashboard")

    prescription = get_object_or_404(Prescription, pk=prescription_id, doctor=doctor)

    if prescription.is_locked and not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "This prescription is locked (expired or finalized) and cannot be edited.")
        return redirect("doctors:prescription_detail", prescription_id=prescription.pk)

    medicines = Medicine.objects.all().order_by("brand_name")
    existing_items = prescription.items.select_related("medicine").prefetch_related("reminder_schedules")

    if request.method == "POST":
        chief_complaints = request.POST.get("chief_complaints", "").strip()
        diagnosis = request.POST.get("diagnosis", "").strip()
        doctor_notes = (request.POST.get("doctor_notes") or request.POST.get("clinical_notes") or "").strip()
        next_visit = request.POST.get("follow_up_date") or request.POST.get("next_visit_date") or ""
        next_visit = next_visit.strip()

        test_names = request.POST.getlist("test_name[]")
        tests_investigations = "\n".join([t.strip() for t in test_names if t.strip()])

        advice_rules_list = request.POST.getlist("advice_rule[]")
        advice_rules = (request.POST.get("advice_rules") or "\n".join([a.strip() for a in advice_rules_list if a.strip()]) or request.POST.get("advice") or "").strip()

        next_followup = None
        if next_visit:
            try:
                next_followup = datetime.strptime(next_visit, "%Y-%m-%d").date()
            except ValueError:
                pass

        activates_at_raw = request.POST.get("activates_at", "").strip()
        expires_at_raw = request.POST.get("expires_at", "").strip()

        tz = timezone.get_current_timezone()

        if activates_at_raw:
            try:
                prescription.activates_at = timezone.make_aware(datetime.strptime(activates_at_raw, "%Y-%m-%dT%H:%M"), tz)
            except ValueError:
                pass
        if expires_at_raw:
            try:
                prescription.expires_at = timezone.make_aware(datetime.strptime(expires_at_raw, "%Y-%m-%dT%H:%M"), tz)
            except ValueError:
                pass

        prescription.chief_complaints = chief_complaints
        prescription.diagnosis = diagnosis
        prescription.tests_investigations = tests_investigations
        prescription.advice_rules = advice_rules
        prescription.doctor_notes = doctor_notes
        prescription.next_followup_date = next_followup
        prescription.save()

        # Update patient demographics if provided
        patient = prescription.patient
        patient_age = request.POST.get("patient_age", "").strip()
        patient_gender = request.POST.get("patient_gender", "").strip()
        patient_email = request.POST.get("patient_email", "").strip()
        patient_phone = request.POST.get("patient_phone", "").strip()

        patient_updated = False
        if patient_gender and (not patient.gender or patient.gender.lower() != patient_gender.lower()):
            patient.gender = patient_gender.capitalize()
            patient_updated = True
        if patient_phone and patient.phone_number != patient_phone:
            patient.phone_number = patient_phone
            patient_updated = True
        if patient_age and patient_age.isdigit():
            age_int = int(patient_age)
            if age_int >= 0 and (patient.age is None or patient.age != age_int):
                today = timezone.localdate()
                if patient.date_of_birth:
                    try:
                        patient.date_of_birth = patient.date_of_birth.replace(year=today.year - age_int)
                    except ValueError:
                        patient.date_of_birth = datetime(today.year - age_int, patient.date_of_birth.month, 28).date()
                else:
                    patient.date_of_birth = datetime(today.year - age_int, 1, 1).date()
                patient_updated = True
        if patient_updated:
            patient.save()

        if patient_email and patient.user.email != patient_email:
            patient.user.email = patient_email
            patient.user.save(update_fields=["email"])

        prescription.items.all().delete()

        med_names = request.POST.getlist("med_name[]") or request.POST.getlist("medicine_name[]")
        med_ids = request.POST.getlist("medicine_id[]")
        dosages = request.POST.getlist("med_dosage[]") or request.POST.getlist("dosage[]")
        freqs = request.POST.getlist("med_frequency[]") or request.POST.getlist("frequency[]")
        timings = request.POST.getlist("med_timing[]") or request.POST.getlist("timing[]")
        durations = request.POST.getlist("med_duration[]") or request.POST.getlist("duration_days[]")
        notes_list = request.POST.getlist("med_notes[]") or request.POST.getlist("instructions[]")

        items_count = max(len(med_names), len(med_ids))
        for idx in range(items_count):
            med_name = med_names[idx].strip() if idx < len(med_names) else ""
            med_id = med_ids[idx] if idx < len(med_ids) else None

            med_obj = None
            if med_id and str(med_id).isdigit():
                med_obj = Medicine.objects.filter(pk=int(med_id)).first()
            if not med_obj and med_name:
                med_obj = (
                    Medicine.objects.filter(brand_name__iexact=med_name).first() or
                    Medicine.objects.filter(generic_name__iexact=med_name).first() or
                    Medicine.objects.filter(brand_name__icontains=med_name).first()
                )
                if not med_obj:
                    med_obj = Medicine.objects.create(
                        brand_name=med_name,
                        generic_name=med_name,
                        form="Tablet",
                    )

            if med_obj:
                d_val = dosages[idx].strip() if (idx < len(dosages) and dosages[idx].strip()) else "1+0+1"

                raw_f = freqs[idx] if idx < len(freqs) else "1"
                try:
                    f_val = int(raw_f)
                except ValueError:
                    f_val = 1

                timing_val = timings[idx] if idx < len(timings) else "after_meal"
                if timing_val not in ["before_meal", "after_meal", "with_meal", "anytime"]:
                    timing_val = "after_meal"

                raw_dur = durations[idx] if idx < len(durations) else "7"
                try:
                    dur_val = int(raw_dur)
                except ValueError:
                    dur_val = 7

                inst_val = notes_list[idx].strip() if idx < len(notes_list) else ""

                p_item = PrescriptionItem.objects.create(
                    prescription=prescription,
                    medicine=med_obj,
                    dosage=d_val,
                    frequency=f_val,
                    timing_relation_to_meal=timing_val,
                    duration_days=dur_val,
                    special_instructions=inst_val,
                )

                from prescriptions.models import get_active_dose_slots
                dose_slots = get_active_dose_slots(d_val, frequency=f_val)
                today = timezone.localdate()
                for day_offset in range(dur_val):
                    sch_date = today + timezone.timedelta(days=day_offset)
                    for slot in dose_slots:
                        t_str = slot.get("time")
                        if t_str:
                            try:
                                t_obj = datetime.strptime(t_str, "%H:%M:%S").time()
                            except ValueError:
                                t_obj = None
                            ReminderSchedule.objects.create(
                                prescription_item=p_item,
                                scheduled_date=sch_date,
                                reminder_time=t_obj,
                                status="pending",
                            )

        # Record/update patient visit vitals if provided
        h_rate = request.POST.get("heart_rate")
        bp_sys = request.POST.get("blood_pressure_systolic")
        bp_dia = request.POST.get("blood_pressure_diastolic")
        temp_c = request.POST.get("temperature_celsius")
        weight = request.POST.get("weight_kg")
        # Height can be provided in ft/in or cm
        h_cm = request.POST.get("height_cm", "").strip()
        h_ft = request.POST.get("height_ft", "").strip()
        h_in = request.POST.get("height_in", "").strip()
        final_height_cm = None
        if h_ft or h_in:
            try:
                ft_val = float(h_ft) if h_ft else 0
                in_val = float(h_in) if h_in else 0
                if ft_val > 0 or in_val > 0:
                    final_height_cm = int(round((ft_val * 12 + in_val) * 2.54))
            except (ValueError, TypeError):
                pass
        if not final_height_cm and h_cm:
            try:
                final_height_cm = int(round(float(h_cm)))
            except (ValueError, TypeError):
                pass

        spo2 = request.POST.get("oxygen_saturation")
        visit_notes = request.POST.get("visit_notes", "").strip()

        if any([h_rate, bp_sys, bp_dia, temp_c, weight, final_height_cm, spo2, visit_notes]):
            try:
                from patient.models import PatientVisit
                visit = getattr(prescription, "visit", None)
                if not visit and prescription.appointment:
                    visit = getattr(prescription.appointment, "visit", None)
                if not visit:
                    visit = PatientVisit.objects.filter(prescription=prescription).first()
                if not visit:
                    visit = PatientVisit(
                        patient=prescription.patient,
                        doctor=doctor,
                        appointment=prescription.appointment,
                        prescription=prescription,
                    )
                else:
                    visit.prescription = prescription
                    if not visit.doctor:
                        visit.doctor = doctor

                if h_rate and h_rate.isdigit():
                    visit.heart_rate = int(h_rate)
                if bp_sys and bp_sys.isdigit():
                    visit.blood_pressure_systolic = int(bp_sys)
                if bp_dia and bp_dia.isdigit():
                    visit.blood_pressure_diastolic = int(bp_dia)
                if temp_c:
                    try:
                        visit.temperature_celsius = float(temp_c)
                    except ValueError:
                        pass
                if weight:
                    try:
                        visit.weight_kg = float(weight)
                    except ValueError:
                        pass
                if final_height_cm:
                    visit.height_cm = final_height_cm
                if spo2 and spo2.isdigit():
                    visit.oxygen_saturation = int(spo2)
                if visit_notes:
                    visit.visit_notes = visit_notes
                visit.save()
            except Exception:
                pass

        if next_followup:
            followup, _ = FollowUp.objects.get_or_create(prescription=prescription, defaults={"scheduled_date": next_followup})
            followup.scheduled_date = next_followup
            followup.status = "upcoming"
            followup.save()

        messages.success(request, "Prescription updated successfully.")
        return redirect("doctors:prescription_detail", prescription_id=prescription.pk)

    visit = getattr(prescription, "visit", None)
    return render(
        request,
        "doctors/edit_prescription.html",
        {
            "doctor": doctor,
            "patient": prescription.patient,
            "prescription": prescription,
            "medicines": medicines,
            "existing_items": existing_items,
            "visit": visit,
        },
    )


@never_cache_auth
@login_required
def prescription_detail(request, prescription_id):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor and not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access restricted to doctors.")
        return redirect("doctors:dashboard")

    if request.user.is_staff or request.user.is_superuser:
        prescription = get_object_or_404(Prescription, pk=prescription_id)
    else:
        prescription = get_object_or_404(Prescription, pk=prescription_id, doctor=doctor)

    items = prescription.items.select_related("medicine").prefetch_related("reminder_schedules")
    follow_up = getattr(prescription, "follow_up", None)

    return render(
        request,
        "prescriptions/view_prescription.html",
        {
            "prescription": prescription,
            "items": items,
            "follow_up": follow_up,
        },
    )


@never_cache_auth
@login_required
def download_prescription(request, prescription_id):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor and not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access restricted.")
        return redirect("home")

    if request.user.is_staff or request.user.is_superuser:
        prescription = get_object_or_404(Prescription, pk=prescription_id)
    else:
        prescription = get_object_or_404(Prescription, pk=prescription_id, doctor=doctor)

    from prescriptions.views import generate_prescription_pdf
    pdf_buffer = generate_prescription_pdf(prescription)

    response = HttpResponse(pdf_buffer.getvalue(), content_type="application/pdf")
    filename = f"Prescription_{prescription.pk}_{prescription.patient.user.first_name}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@never_cache_auth
@login_required
def update_followup_status(request, followup_id):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("doctors:dashboard")

    followup = get_object_or_404(FollowUp, pk=followup_id, prescription__doctor=doctor)
    new_status = request.POST.get("status")
    if new_status in ["upcoming", "completed", "missed"]:
        followup.status = new_status
        followup.save()
        messages.success(request, f"Follow-up status updated to {new_status}.")

    return redirect("doctors:prescription_detail", prescription_id=followup.prescription.pk)


from django.urls import reverse
from django.db.models import Q


@never_cache_auth
@login_required
def history(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("home")

    filter_type = request.GET.get("type", "all").strip()
    query = request.GET.get("q", "").strip()

    prescriptions_qs = (
        Prescription.objects.filter(doctor=doctor)
        .select_related("patient__user")
        .prefetch_related("items__medicine")
        .order_by("-issued_at")
    )
    if query:
        prescriptions_qs = prescriptions_qs.filter(
            Q(patient__user__first_name__icontains=query)
            | Q(patient__user__last_name__icontains=query)
            | Q(patient__user__email__icontains=query)
            | Q(diagnosis__icontains=query)
            | Q(chief_complaints__icontains=query)
        )

    appointments_qs = (
        Appointment.objects.filter(doctor=doctor)
        .select_related("patient__user")
        .order_by("-appointment_date", "-start_time")
    )
    if query:
        appointments_qs = appointments_qs.filter(
            Q(patient__user__first_name__icontains=query)
            | Q(patient__user__last_name__icontains=query)
            | Q(patient__user__email__icontains=query)
            | Q(chief_complaint__icontains=query)
        )

    activity_items = []
    if filter_type in ["all", "prescriptions"]:
        for p in prescriptions_qs[:150]:
            patient_name = p.patient.user.get_full_name() or p.patient.user.email if p.patient and p.patient.user else "Patient"
            activity_items.append({
                "type": "prescription",
                "id": p.id,
                "date": p.issued_at,
                "patient": p.patient,
                "patient_name": patient_name,
                "title": f"Prescription #{p.id}",
                "detail": p.diagnosis or p.chief_complaints or "Prescription issued",
                "items_count": p.items.count() if hasattr(p, "items") else 0,
                "url": reverse("doctors:prescription_detail", args=[p.id]),
                "download_url": reverse("doctors:download_prescription", args=[p.id]),
                "patient_url": reverse("doctors:patient_detail", args=[p.patient.id]) if p.patient else None,
            })

    if filter_type in ["all", "appointments"]:
        for apt in appointments_qs[:150]:
            patient_name = apt.patient.user.get_full_name() or apt.patient.user.email if apt.patient and apt.patient.user else "Patient"
            is_cancelled_or_missed = apt.status in ["cancelled", "missed"]
            activity_items.append({
                "type": "appointment",
                "id": apt.id,
                "date": apt.created_at or timezone.now(),
                "appointment_date": apt.appointment_date,
                "start_time": apt.start_time,
                "status": apt.status,
                "status_display": apt.get_status_display(),
                "patient": apt.patient,
                "patient_name": patient_name,
                "title": f"Appointment #{apt.id} ({apt.get_consultation_type_display()})",
                "detail": f"Status: {apt.get_status_display()}" + (f" — {apt.chief_complaint}" if apt.chief_complaint else ""),
                "url": reverse("doctors:appointment_detail", args=[apt.id]) if not is_cancelled_or_missed else None,
                "patient_url": reverse("doctors:patient_detail", args=[apt.patient.id]) if (not is_cancelled_or_missed and apt.patient) else None,
                "is_cancelled_or_missed": is_cancelled_or_missed,
            })

    activity_items.sort(key=lambda x: x["date"] or timezone.now(), reverse=True)

    paginator = Paginator(activity_items, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    total_prescriptions = Prescription.objects.filter(doctor=doctor).count()
    total_appointments = Appointment.objects.filter(doctor=doctor).count()
    total_completed = Appointment.objects.filter(doctor=doctor, status="completed").count()

    return render(
        request,
        "doctors/history.html",
        {
            "activity": page_obj,
            "page_obj": page_obj,
            "prescriptions": page_obj,
            "query": query,
            "filter_type": filter_type,
            "total_prescriptions": total_prescriptions,
            "total_appointments": total_appointments,
            "total_completed": total_completed,
        },
    )
