from django.urls import reverse


def ui_settings(request):
    site_lang = request.session.get("site_lang")

    if not site_lang and request.user.is_authenticated and hasattr(request.user, "patient_profile"):
        site_lang = getattr(request.user.patient_profile, "preferred_language", "en") or "en"

    if not site_lang:
        site_lang = "en"

    dashboard_url = None
    if request.user.is_authenticated:
        if hasattr(request.user, "patient_profile"):
            dashboard_url = reverse("patient:dashboard")
        elif hasattr(request.user, "doctor_profile"):
            dashboard_url = reverse("doctors:dashboard")

    is_patient = request.user.is_authenticated and hasattr(request.user, "patient_profile")

    return {
        "site_lang": site_lang,
        "dashboard_url": dashboard_url,
        "is_patient_portal": is_patient,
    }
