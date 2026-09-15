from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import (
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from accounts.decorators import never_cache_auth
from accounts.forms import (
    LoginForm,
    RegisterForm,
    CareBridgePasswordResetForm,
    CareBridgeSetPasswordForm,
)
from accounts.models import Doctor, Patient


@never_cache_auth
def register_view(request):
    if request.method == "POST":
        form = RegisterForm(request.POST, request.FILES)
        if form.is_valid():
            data = form.cleaned_data

            user = User.objects.create_user(
                username=data["email"],
                email=data["email"],
                password=data["password"],
                first_name=data["first_name"].strip(),
                last_name=data.get("last_name", "").strip(),
            )

            if data["role"] == "patient":
                patient_doc = request.FILES.get("patient_identity_doc")
                Patient.objects.create(
                    user=user,
                    phone_number=data["phone_number"],
                    district=data.get("district") or "Dhaka",
                    nid_or_birth_reg=data.get("patient_nid_or_birth_reg", "").strip(),
                    identity_document=patient_doc,
                    country="Bangladesh",
                    verification_status="pending",
                    is_verified=False,
                    date_of_birth=data.get("date_of_birth"),
                    gender=data.get("gender", "").strip(),
                )
            else:
                bmdc_file = request.FILES.get("bmdc_certificate")
                Doctor.objects.create(
                    user=user,
                    phone_number=data["phone_number"],
                    registration_number=data.get("bmdc_number", "").strip(),
                    nid_number=data.get("nid_number", "").strip(),
                    bmdc_certificate=bmdc_file,
                    specialty=data.get("specialty", "").strip() or "General Physician",
                    experience_years=data.get("experience_years", 0),
                    consultation_fee=data.get("consultation_fee", 0),
                    country="Bangladesh",
                    verification_status="pending",
                    is_verified=False,
                    date_of_birth=data.get("date_of_birth"),
                    gender=data.get("gender", "").strip(),
                )

            backend = "accounts.backends.EmailAuthBackend"
            login(request, user, backend=backend)
            messages.success(request, f"Welcome to CareBridge AI, {user.get_full_name() or user.email}!")
            return redirect("accounts:post_login_redirect")
    else:
        form = RegisterForm()

    return render(request, "accounts/register.html", {"form": form})


@never_cache_auth
def login_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:post_login_redirect")

    if request.method == "POST":
        form = LoginForm(request.POST, request=request)
        if form.is_valid():
            user = form.get_user()
            backend = "accounts.backends.EmailAuthBackend"
            login(request, user, backend=backend)
            messages.success(request, f"Welcome back, {user.get_full_name() or user.email}!")
            return redirect("accounts:post_login_redirect")
    else:
        form = LoginForm()

    return render(request, "accounts/login.html", {"form": form})


@never_cache_auth
def logout_view(request):
    logout(request)
    request.session.flush()
    messages.info(request, "You have been logged out securely.")
    response = redirect("home")
    response["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0, private"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    response["Clear-Site-Data"] = '"cache", "storage"'
    return response


class CustomPasswordResetView(PasswordResetView):
    template_name = "accounts/password_reset.html"
    form_class = CareBridgePasswordResetForm
    email_template_name = "registration/password_reset_email.html"
    subject_template_name = "registration/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")
    extra_email_context = {
        "url_name": "accounts:password_reset_confirm",
        "site_name": "CareBridge AI",
        "support_email": "mdimran095m@gmail.com",
    }


class CustomPasswordResetDoneView(PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    form_class = CareBridgeSetPasswordForm
    success_url = reverse_lazy("accounts:password_reset_complete")


class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


@login_required
def verification_pending_view(request):
    is_doctor = hasattr(request.user, "doctor_profile")
    is_patient = hasattr(request.user, "patient_profile")
    doctor = getattr(request.user, "doctor_profile", None)
    patient = getattr(request.user, "patient_profile", None)

    if request.user.is_superuser or (doctor and doctor.is_verified) or (patient and patient.is_verified):
        return redirect("accounts:post_login_redirect")

    return render(
        request,
        "accounts/verification_pending.html",
        {"is_doctor": is_doctor, "is_patient": is_patient},
    )


@login_required
def post_login_redirect(request):
    """Send doctors, patients, and admins directly to their respective dashboards or verification pending page."""
    if request.user.is_superuser or request.user.is_staff:
        return redirect("admin:index")

    if hasattr(request.user, "doctor_profile"):
        doctor = request.user.doctor_profile
        if not doctor.is_verified:
            return redirect("accounts:verification_pending")
        return redirect("doctors:dashboard")

    if hasattr(request.user, "patient_profile"):
        patient = request.user.patient_profile
        if not patient.is_verified:
            return redirect("accounts:verification_pending")
        return redirect("patient:dashboard")

    from datetime import date
    patient, _ = Patient.objects.get_or_create(
        user=request.user,
        defaults={
            "phone_number": "+8801700000000",
            "district": "Dhaka",
            "date_of_birth": date(1995, 1, 1),
            "gender": "Male",
            "is_verified": False,
            "verification_status": "pending",
        }
    )
    if not patient.is_verified:
        return redirect("accounts:verification_pending")
    return redirect("patient:dashboard")
