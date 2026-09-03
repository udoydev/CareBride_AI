"""
URL configuration for carebridge project.
"""
from django.contrib import admin
from django.conf import settings
from django.urls import path,include,re_path
from django.shortcuts import redirect
from django.conf.urls.static import static

from . import views, voice_views
from . views import home, media_serve

def index(request):
 return redirect("home")

from accounts import views as accounts_views
from accounts.forms import AdminEmailLoginForm

admin.site.login_form = AdminEmailLoginForm


urlpatterns = [
    path('admin/', admin.site.urls),
    path("", index),
    path("home/", home, name="home"),
    path("voice/", voice_views.voice_chatbot_view, name="voice_chatbot"),
    path("reports/admin/", views.admin_reports, name="admin_reports"),
    path("reports/admin/doctor/<int:doctor_id>/", views.admin_doctor_report, name="admin_doctor_report"),
    path("reports/admin/doctors/tracking/", views.admin_doctor_tracking, name="admin_doctor_tracking"),
    path("reports/admin/doctors/<int:doctor_id>/delete/", views.admin_delete_doctor, name="admin_delete_doctor"),
    path("api/voice/stt-demo/", voice_views.voice_stt_demo_api, name="voice_stt_demo"),
    path("api/voice/explainer/", voice_views.voice_explainer_api, name="voice_explainer"),
    path("api/voice/tts/", voice_views.voice_tts_stream_api, name="voice_tts_stream"),
    path("language/<str:lang>/", views.set_site_language, name="set_language"),
    path("reset/<uidb64>/<token>/", accounts_views.CustomPasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path('', include('accounts.urls')),
    path('', include('patient.urls')),
    path('', include('doctors.urls')),
    path('prescriptions/', include('prescriptions.urls')),



    # always last
     path("__reload__/", include("django_browser_reload.urls")),
]

if settings.DEBUG:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', media_serve, {'document_root': settings.MEDIA_ROOT}),
    ]

handler404 = 'carebridge.views.custom_404'
