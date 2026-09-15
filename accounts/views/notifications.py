from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect

from accounts.models import AppNotification


@login_required
def session_ping_view(request):
    """Keep session alive by resetting expiry timer on user activity."""
    request.session.modified = True
    return JsonResponse({"status": "ok"})


@login_required
def session_end_view(request):
    """Clear session when browser/tab is closed."""
    logout(request)
    request.session.flush()
    return JsonResponse({"status": "ended"})


@login_required
def delete_notification_view(request, notification_id):
    """Delete a single notification."""
    notification = get_object_or_404(AppNotification, pk=notification_id, user=request.user)
    notification.delete()
    messages.success(request, "Notification deleted.")
    return redirect(request.META.get("HTTP_REFERER", "patient:notifications"))


@login_required
def clear_notifications_view(request):
    """Clear all notifications for the current user."""
    if request.method == "POST":
        AppNotification.objects.filter(user=request.user).delete()
        messages.success(request, "All notifications cleared.")
    return redirect(request.META.get("HTTP_REFERER", "patient:notifications"))
