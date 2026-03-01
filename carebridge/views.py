from django.conf import settings
from django.shortcuts import redirect, render
from django.views.static import serve as static_serve


def home(request):
  return render(request,'home.html')


def set_site_language(request, lang):
    next_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or "/home/"
    target_lang = "bn" if lang == "bn" else "en"
    request.session["site_lang"] = target_lang

    if request.user.is_authenticated and hasattr(request.user, "patient_profile"):
        patient = request.user.patient_profile
        patient.preferred_language = target_lang
        patient.save(update_fields=["preferred_language"])

    return redirect(next_url)


def media_serve(request, path, document_root=None):
    """Serve media files with cache-busting headers to prevent stale avatar caching."""
    response = static_serve(request, path, document_root=document_root)
    response["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response

