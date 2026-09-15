from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from accounts.decorators import never_cache_auth
from accounts.forms import ProfileForm


@login_required
@never_cache_auth
def profile_view(request):
    patient = getattr(request.user, "patient_profile", None)
    doctor = getattr(request.user, "doctor_profile", None)

    from accounts.models import BD_DISTRICT_CHOICES
    from datetime import datetime

    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()
        preferred_language = request.POST.get("preferred_language", "").strip()
        avatar_file = request.FILES.get("avatar")
        email = request.POST.get("email", "").strip()

        if full_name:
            names = full_name.split(" ", 1)
            request.user.first_name = names[0]
            request.user.last_name = names[1] if len(names) > 1 else ""
        if email:
            request.user.email = email
        request.user.save()

        if patient:
            if preferred_language in ("bn", "en"):
                patient.preferred_language = preferred_language
                request.session["site_lang"] = preferred_language

            district = request.POST.get("district", "").strip()
            gender = request.POST.get("gender", "").strip()
            dob_str = request.POST.get("date_of_birth", "").strip()

            if district:
                patient.district = district
            if gender in ("Male", "Female", "Other"):
                patient.gender = gender
            if dob_str:
                try:
                    patient.date_of_birth = datetime.strptime(dob_str, "%Y-%m-%d").date()
                except ValueError:
                    pass

            if avatar_file:
                patient.avatar = avatar_file
                patient.avatar_updated_at = timezone.now()
            patient.save()
            patient.refresh_from_db()
        elif doctor:
            if preferred_language in ("bn", "en"):
                request.session["site_lang"] = preferred_language
            if avatar_file:
                old_avatar = doctor.avatar
                doctor.avatar = avatar_file
                doctor.avatar_updated_at = timezone.now()
                if old_avatar and old_avatar.name != doctor.avatar.name:
                    try:
                        old_avatar.delete(save=False)
                    except Exception:
                        pass
            doctor.save()
            doctor.refresh_from_db()

        messages.success(request, "Profile updated successfully.")
        return redirect("accounts:profile")
    else:
        if patient:
            patient.refresh_from_db()
        if doctor:
            doctor.refresh_from_db()
        form = ProfileForm(
            initial={
                "full_name": request.user.get_full_name(),
                "preferred_language": patient.preferred_language if patient else request.session.get("site_lang", "bn"),
            }
        )

    return render(
        request,
        "accounts/profile.html",
        {
            "form": form,
            "patient": patient,
            "doctor": doctor,
            "districts": BD_DISTRICT_CHOICES,
        },
    )
