from .admin_views import (
    admin_unverified_dashboard_view,
    ai_provider_add,
    ai_provider_delete,
    ai_provider_edit,
    ai_provider_list,
    ai_provider_toggle,
)
from .analytics import (
    admin_analytics_view,
    doctor_analytics_view,
)
from .auth import (
    CustomPasswordResetCompleteView,
    CustomPasswordResetConfirmView,
    CustomPasswordResetDoneView,
    CustomPasswordResetView,
    login_view,
    logout_view,
    post_login_redirect,
    register_view,
    verification_pending_view,
)
from .notifications import (
    clear_notifications_view,
    delete_notification_view,
    session_end_view,
    session_ping_view,
)
from .payments import payment_process_view
from .profile import profile_view

__all__ = [
    "register_view",
    "login_view",
    "logout_view",
    "CustomPasswordResetView",
    "CustomPasswordResetDoneView",
    "CustomPasswordResetConfirmView",
    "CustomPasswordResetCompleteView",
    "verification_pending_view",
    "post_login_redirect",
    "profile_view",
    "admin_unverified_dashboard_view",
    "ai_provider_list",
    "ai_provider_add",
    "ai_provider_edit",
    "ai_provider_delete",
    "ai_provider_toggle",
    "payment_process_view",
    "doctor_analytics_view",
    "admin_analytics_view",
    "session_ping_view",
    "session_end_view",
    "delete_notification_view",
    "clear_notifications_view",
]
