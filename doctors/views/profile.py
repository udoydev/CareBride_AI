from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import never_cache_auth
from accounts.forms import ProfileForm
from doctors.models import DoctorSchedule


@never_cache_auth
@login_required
def profile_edit(request):
    """
    Doctor profile editing view.
    Handles personal info, medical credentials, clinic details, fees, avatar, and digital signature.
    """
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Only doctors can edit doctor profile.")
        return redirect("doctors:dashboard")

    categories = [
        "General Physician", "Cardiologist", "Dermatologist", "Pediatrician",
        "Orthopedic", "Gastroenterologist", "Neurologist", "ENT Specialist",
        "Gynecologist", "Psychiatrist", "Ophthalmologist", "Urologist"
    ]

    from decimal import Decimal
    from django.utils import timezone

    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()
        phone_number = request.POST.get("phone_number", "").strip()
        specialty = request.POST.get("specialty", "General Physician").strip()
        clinic_name = request.POST.get("clinic_name", "").strip()
        location_text = request.POST.get("location_text", "").strip()
        bio = request.POST.get("bio", "").strip()
        experience_years = request.POST.get("experience_years", "").strip()
        consultation_fee = request.POST.get("consultation_fee", "").strip()
        designation = request.POST.get("designation", "").strip()
        degrees = request.POST.get("degrees", "").strip()
        bmdc_registration_year = request.POST.get("bmdc_registration_year", "").strip()

        errors = []
        if not experience_years:
            errors.append("Experience years is required.")
        if not consultation_fee:
            errors.append("Consultation fee is required.")

        if full_name:
            names = full_name.split(" ", 1)
            request.user.first_name = names[0]
            request.user.last_name = names[1] if len(names) > 1 else ""
            request.user.save()

        if phone_number:
            doctor.phone_number = phone_number
        if specialty:
            doctor.specialty = specialty
        doctor.clinic_name = clinic_name
        doctor.location_text = location_text
        doctor.bio = bio
        doctor.designation = designation
        doctor.degrees = degrees

        try:
            doctor.experience_years = int(experience_years) if experience_years else 0
        except (ValueError, TypeError):
            errors.append("Experience years must be a valid number.")

        try:
            doctor.consultation_fee = Decimal(consultation_fee) if consultation_fee else Decimal("0")
        except (ValueError, TypeError):
            errors.append("Consultation fee must be a valid amount.")

        try:
            doctor.bmdc_registration_year = int(bmdc_registration_year) if bmdc_registration_year else None
        except (ValueError, TypeError):
            errors.append("BMDC Registration Year must be a valid number.")

        if request.FILES.get("avatar"):
            old_avatar = doctor.avatar
            doctor.avatar = request.FILES.get("avatar")
            doctor.avatar_updated_at = timezone.now()
            if old_avatar and old_avatar.name != doctor.avatar.name:
                try:
                    old_avatar.delete(save=False)
                except Exception:
                    pass

        if request.FILES.get("signature"):
            old_sig = doctor.signature
            doctor.signature = request.FILES.get("signature")
            if old_sig and old_sig.name != doctor.signature.name:
                try:
                    old_sig.delete(save=False)
                except Exception:
                    pass

        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect("doctors:profile_edit")

        doctor.save()
        messages.success(request, "Doctor profile updated successfully.")
        return redirect("doctors:profile_edit")

    doctor_payload = {
        "name": request.user.get_full_name() or request.user.email,
        "specialty": doctor.specialty or "General Physician",
        "bio": doctor.bio or "",
        "clinic_name": doctor.clinic_name or "",
        "location_text": doctor.location_text or "",
        "experience_years": doctor.experience_years or 0,
        "consultation_fee": doctor.consultation_fee or 0,
        "avatar": doctor.avatar.url if doctor.avatar else None,
        "signature": doctor.signature.url if doctor.signature else None,
        "avatar_updated_at": doctor.avatar_updated_at,
        "designation": doctor.designation or "",
        "degrees": doctor.degrees or "",
        "bmdc_registration_year": doctor.bmdc_registration_year,
    }
    return render(request, "doctors/profile_edit.html", {"doctor": doctor_payload, "categories": categories})


@never_cache_auth
@login_required
def schedule_management(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("home")

    schedules = DoctorSchedule.objects.filter(doctor=doctor).order_by("day_of_week", "start_time")

    if request.method == "POST":
        day_of_week = request.POST.get("day_of_week")
        start_time = request.POST.get("start_time")
        end_time = request.POST.get("end_time")
        slot_duration = request.POST.get("slot_duration_minutes", 20)
        max_patients = request.POST.get("max_patients", 10)

        if day_of_week and start_time and end_time:
            try:
                slot_duration = int(slot_duration)
            except (ValueError, TypeError):
                slot_duration = 20

            try:
                max_patients = int(max_patients)
            except (ValueError, TypeError):
                max_patients = 10

            existing_schedules = DoctorSchedule.objects.filter(doctor=doctor, day_of_week=day_of_week)
            if existing_schedules.exists():
                schedule = existing_schedules.first()
                schedule.start_time = start_time
                schedule.end_time = end_time
                schedule.slot_duration_minutes = slot_duration
                schedule.max_patients = max_patients
                schedule.is_active = True
                schedule.save()
                # Clean up any previously created duplicate schedules for the same day
                if existing_schedules.count() > 1:
                    existing_schedules.exclude(pk=schedule.pk).delete()
                messages.success(request, f"Schedule for {schedule.get_day_of_week_display()} updated successfully.")
            else:
                schedule = DoctorSchedule.objects.create(
                    doctor=doctor,
                    day_of_week=day_of_week,
                    start_time=start_time,
                    end_time=end_time,
                    slot_duration_minutes=slot_duration,
                    max_patients=max_patients,
                    is_active=True,
                )
                messages.success(request, f"Schedule for {schedule.get_day_of_week_display()} created successfully.")
            return redirect("doctors:schedule_management")

    return render(request, "doctors/schedule_management.html", {
        "schedules": schedules,
        "days": DoctorSchedule.DAY_CHOICES,
    })


@never_cache_auth
@login_required
def delete_schedule(request, schedule_id):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("home")

    schedule = get_object_or_404(DoctorSchedule, pk=schedule_id, doctor=doctor)
    schedule.delete()
    messages.success(request, "Schedule slot removed.")
    return redirect("doctors:schedule_management")
