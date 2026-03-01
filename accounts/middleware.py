from django.shortcuts import redirect
from django.urls import reverse


class RoleBasedAccessMiddleware:
    """
    Enforces role-based access control and verification status:
    - Admin/staff users can only access admin panel and admin-provided spaces
    - Doctor users can only access doctor panel and patient-facing spaces (for their own patients)
    - Patient users can only access patient panel
    - Unverified users are redirected to verification pending page
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.allowed_common_paths = [
            "/accounts/",
            "/profile/",
            "/language/",
            "/prescriptions/",
            "/api/",
            "/voice/",
            "/logout/",
            "/payment/",
            "/session-ping/",
            "/session-end/",
            "/notifications/",
        ]
        self.allowed_admin_paths = self.allowed_common_paths + [
            "/admin/",
            "/ai-providers/",
            "/admin-unverified/",
            "/analytics/",
        ]

    def __call__(self, request):
        if request.user.is_authenticated:
            path = request.path
            
            # Skip static/media files
            if path.startswith("/static/") or path.startswith("/media/"):
                return self.get_response(request)
            
            # Allow common authenticated paths for everyone
            if any(path.startswith(allowed) for allowed in self.allowed_common_paths):
                return self.get_response(request)
            
            # Admin/staff bypass verification
            if request.user.is_superuser or request.user.is_staff:
                if any(path.startswith(allowed) for allowed in self.allowed_admin_paths):
                    return self.get_response(request)
                if path in ["/", "/home/"]:
                    return self.get_response(request)
                return redirect("admin:index")

            # Check verification status for patient/doctor
            is_verified = True
            if hasattr(request.user, "patient_profile"):
                is_verified = request.user.patient_profile.is_verified
            elif hasattr(request.user, "doctor_profile"):
                is_verified = request.user.doctor_profile.is_verified

            if not is_verified:
                # Allow verification pending page and public pages
                if path == "/verification-pending/":
                    return self.get_response(request)
                if path in ["/", "/home/"]:
                    return self.get_response(request)
                # Redirect all other unverified users to verification pending
                return redirect("accounts:verification_pending")

            # Doctor users
            if hasattr(request.user, 'doctor_profile'):
                if path.startswith("/doctors/") or path.startswith("/doctor/"):
                    return self.get_response(request)
                if path in ["/", "/home/"]:
                    return self.get_response(request)
                return redirect("doctors:dashboard")
            
            # Patient users
            if hasattr(request.user, 'patient_profile'):
                if path.startswith("/patient/"):
                    return self.get_response(request)
                if path in ["/", "/home/"]:
                    return self.get_response(request)
                return redirect("patient:dashboard")

        return self.get_response(request)


class AdminStaffAccessRestrictionMiddleware:
    """
    Deprecated: Use RoleBasedAccessMiddleware instead.
    Kept for backward compatibility.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)


class NoCacheAuthenticationMiddleware:
    """
    Prevents caching of authenticated pages.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated:
            response["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0, private"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
        return response
