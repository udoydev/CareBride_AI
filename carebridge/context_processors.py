from django.conf import settings
from django.urls import reverse
from django.utils import translation


def ui_settings(request):
    site_lang = request.session.get("site_lang")

    if not site_lang and request.user.is_authenticated:
        if hasattr(request.user, "patient_profile") and request.user.patient_profile:
            site_lang = getattr(request.user.patient_profile, "preferred_language", None)
        elif hasattr(request.user, "doctor_profile") and request.user.doctor_profile:
            site_lang = getattr(request.user.doctor_profile, "preferred_language", None)

    if not site_lang:
        cookie_lang = request.COOKIES.get(getattr(settings, "LANGUAGE_COOKIE_NAME", "django_language"))
        site_lang = cookie_lang

    target_lang = "bn" if site_lang == "bn" else "en"
    translation.activate(target_lang)
    request.session["site_lang"] = target_lang

    dashboard_url = None
    if request.user.is_authenticated:
        if hasattr(request.user, "patient_profile") and request.user.patient_profile:
            dashboard_url = reverse("patient:dashboard")
        elif hasattr(request.user, "doctor_profile") and request.user.doctor_profile:
            dashboard_url = reverse("doctors:dashboard")

    is_patient = request.user.is_authenticated and hasattr(request.user, "patient_profile") and bool(request.user.patient_profile)

    from accounts.models import SiteSettings, News
    try:
        settings_obj = SiteSettings.get_solo()
        comm_rate = settings_obj.platform_commission_rate
        refund_pct = settings_obj.patient_refund_percentage
    except Exception:
        comm_rate = 15.00
        refund_pct = 35.00

    site_news_list = []
    try:
        active_news_qs = News.objects.filter(is_active=True)
        if request.user.is_authenticated:
            if hasattr(request.user, "patient_profile") and request.user.patient_profile:
                active_news_qs = active_news_qs.filter(target_audience__in=["all", "patients"])
            elif hasattr(request.user, "doctor_profile") and request.user.doctor_profile:
                active_news_qs = active_news_qs.filter(target_audience__in=["all", "doctors"])
            else:
                active_news_qs = active_news_qs.filter(target_audience="all")
        else:
            active_news_qs = active_news_qs.filter(target_audience="all")
        site_news_list = list(active_news_qs[:5])
    except Exception:
        site_news_list = []

    try:
        from carebridge.ai_services import GeminiAIService
        ai_available = GeminiAIService.is_ai_available()
    except Exception:
        ai_available = True

    return {
        "site_lang": target_lang,
        "dashboard_url": dashboard_url,
        "is_patient_portal": is_patient,
        "site_commission_rate": comm_rate,
        "site_refund_percentage": refund_pct,
        "site_news_list": site_news_list,
        "ai_available": ai_available,
    }
