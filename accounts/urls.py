from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("redirect/", views.post_login_redirect, name="post_login_redirect"),
    path("verification-pending/", views.verification_pending_view, name="verification_pending"),
    path("admin-unverified/", views.admin_unverified_dashboard_view, name="admin_unverified_dashboard"),
    # AI Provider Management (Admin only)
    path("ai-providers/", views.ai_provider_list, name="ai_provider_list"),
    path("ai-providers/add/", views.ai_provider_add, name="ai_provider_add"),
    path("ai-providers/<int:provider_id>/edit/", views.ai_provider_edit, name="ai_provider_edit"),
    path("ai-providers/<int:provider_id>/delete/", views.ai_provider_delete, name="ai_provider_delete"),
    path("ai-providers/<int:provider_id>/toggle/", views.ai_provider_toggle, name="ai_provider_toggle"),
    # Password Reset URLs
    path("password-reset/", views.CustomPasswordResetView.as_view(), name="password_reset"),
    path("password-reset/done/", views.CustomPasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password-reset-confirm/<uidb64>/<token>/", views.CustomPasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password-reset-complete/", views.CustomPasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("payment/<int:appointment_id>/", views.payment_process_view, name="payment_process"),
    path("doctor/analytics/", views.doctor_analytics_view, name="doctor_analytics"),
    path("analytics/", views.admin_analytics_view, name="admin_analytics"),
    # Session Management
    path("session-ping/", views.session_ping_view, name="session_ping"),
    path("session-end/", views.session_end_view, name="session_end"),
    # Notification Management
    path("notifications/<int:notification_id>/delete/", views.delete_notification_view, name="delete_notification"),
    path("notifications/clear/", views.clear_notifications_view, name="clear_notifications"),
]
