from decimal import Decimal

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
from django.urls import reverse_lazy, reverse
from django.shortcuts import redirect, render, get_object_or_404
from django.http import JsonResponse
from django.utils import timezone


from .decorators import never_cache_auth
from .forms import (
    LoginForm,
    ProfileForm,
    RegisterForm,
    CareBridgePasswordResetForm,
    CareBridgeSetPasswordForm,
)
from .models import AIProvider, Doctor, Patient, AppNotification
from doctors.models import Appointment


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
                )

            # Log the user in specifying backend explicitly
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
            # Block admin/staff users from logging in through patient/doctor portal
            if user.is_superuser or user.is_staff:
                messages.error(request, "Admin accounts must log in through the Admin Dashboard. Please use /admin/ to log in.")
                return redirect("accounts:login")
            login(request, user)
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
    extra_email_context = {"url_name": "accounts:password_reset_confirm"}



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

    # If user is superuser or already verified, redirect to dashboard
    if request.user.is_superuser or (doctor and doctor.is_verified) or (patient and patient.is_verified):
        return redirect("accounts:post_login_redirect")

    return render(
        request,
        "accounts/verification_pending.html",
        {"is_doctor": is_doctor, "is_patient": is_patient},
    )


@login_required
def post_login_redirect(request):
    """Send doctors and patients to the dashboard matching their role, checking verification status."""
    if request.user.is_superuser or request.user.is_staff:
        return redirect("admin:index")

    if hasattr(request.user, "doctor_profile"):
        if not request.user.doctor_profile.is_verified:
            return redirect("accounts:verification_pending")
        return redirect("doctors:dashboard")

    if hasattr(request.user, "patient_profile"):
        if not request.user.patient_profile.is_verified:
            return redirect("accounts:verification_pending")
        return redirect("patient:dashboard")

    return redirect("home")



@login_required
@never_cache_auth
def profile_view(request):
    patient = getattr(request.user, "patient_profile", None)
    doctor = getattr(request.user, "doctor_profile", None)

    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()
        preferred_language = request.POST.get("preferred_language", "bn")
        avatar_file = request.FILES.get("avatar")

        if full_name:
            names = full_name.split(" ", 1)
            request.user.first_name = names[0]
            request.user.last_name = names[1] if len(names) > 1 else ""
            request.user.save()

        if patient:
            patient.preferred_language = preferred_language
            if avatar_file:
                patient.avatar = avatar_file
                patient.avatar_updated_at = timezone.now()
            patient.save()
            patient.refresh_from_db()
        elif doctor:
            if avatar_file:
                old_avatar = doctor.avatar
                doctor.avatar = avatar_file
                doctor.avatar_updated_at = timezone.now()
                if old_avatar and old_avatar.name != doctor.avatar.name:
                    old_avatar.delete(save=False)
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
                "preferred_language": patient.preferred_language if patient else "bn",
            }
        )

    return render(
        request,
        "accounts/profile.html",
        {"form": form, "patient": patient, "doctor": doctor},
    )


@login_required
def admin_unverified_dashboard_view(request):
    """Dedicated Admin Dashboard listing all unverified Patients & Doctors for instant document review & approval."""
    if not request.user.is_superuser:
        messages.error(request, "Access restricted to CareBridge Admin superusers.")
        return redirect("home")

    if request.method == "POST":
        action_type = request.POST.get("action_type")
        user_id = request.POST.get("user_id")

        if action_type == "verify_patient":
            patient = get_object_or_404(Patient, pk=user_id)
            patient.verification_status = "verified"
            patient.is_verified = True
            patient.save()
            messages.success(request, f"✓ Successfully verified Patient {patient.user.get_full_name() or patient.user.email}!")

        elif action_type == "verify_doctor":
            doctor = get_object_or_404(Doctor, pk=user_id)
            doctor.verification_status = "verified"
            doctor.is_verified = True
            doctor.save()
            messages.success(request, f"✓ Successfully verified Doctor {doctor.user.get_full_name() or doctor.user.email}!")

        elif action_type == "reject_patient":
            patient = get_object_or_404(Patient, pk=user_id)
            patient.verification_status = "rejected"
            patient.is_verified = False
            patient.save()
            messages.info(request, f"Rejected verification for Patient {patient.user.get_full_name() or patient.user.email}.")

        elif action_type == "reject_doctor":
            doctor = get_object_or_404(Doctor, pk=user_id)
            doctor.verification_status = "rejected"
            doctor.is_verified = False
            doctor.save()
            messages.info(request, f"Rejected verification for Doctor {doctor.user.get_full_name() or doctor.user.email}.")

        return redirect("accounts:admin_unverified_dashboard")

    unverified_patients = Patient.objects.filter(is_verified=False).select_related("user").order_by("-id")
    unverified_doctors = Doctor.objects.filter(is_verified=False).select_related("user").order_by("-id")

    return render(request, "accounts/admin_unverified_dashboard.html", {
        "unverified_patients": unverified_patients,
        "unverified_doctors": unverified_doctors,
        "pending_patients_count": unverified_patients.count(),
        "pending_doctors_count": unverified_doctors.count(),
    })


@login_required
def ai_provider_list(request):
    if not request.user.is_superuser:
        messages.error(request, "Access restricted to admin.")
        return redirect("home")

    providers = AIProvider.objects.all().order_by("priority", "created_at")
    from carebridge.ai_services import GeminiAIService
    ai_status = GeminiAIService.get_available_providers_info()

    if ai_status.get("all_unavailable"):
        messages.error(request, "⚠️ All AI APIs are currently unavailable. Users will see limited responses. Please add or activate a provider.")

    return render(request, "accounts/ai_provider_list.html", {
        "providers": providers,
        "ai_status": ai_status,
    })


@login_required
def ai_provider_add(request):
    if not request.user.is_superuser:
        messages.error(request, "Access restricted to admin.")
        return redirect("home")

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        provider = request.POST.get("provider", "gemini")
        api_key = request.POST.get("api_key", "").strip()
        model_name = request.POST.get("model_name", "").strip()
        base_url = request.POST.get("base_url", "").strip()
        priority = int(request.POST.get("priority", 100))
        max_rpm = int(request.POST.get("max_requests_per_minute", 60))
        is_active = request.POST.get("is_active") == "on"

        DEFAULT_BASE_URLS = {
            "groq": "https://api.groq.com/openai/v1",
            "openai": "https://api.openai.com/v1",
            "deepseek": "https://api.deepseek.com/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "custom": "https://api.openai.com/v1",
        }

        DEFAULT_MODELS = {
            "gemini": "gemini-2.0-flash",
            "groq": "llama-3.3-70b-versatile",
            "openai": "gpt-4o-mini",
            "deepseek": "deepseek-chat",
            "openrouter": "meta-llama/llama-3.1-70b-instruct",
            "custom": "gpt-4o-mini",
        }

        if provider != "gemini" and not base_url:
            base_url = DEFAULT_BASE_URLS.get(provider, "")
        if not model_name:
            model_name = DEFAULT_MODELS.get(provider, "gemini-2.0-flash")

        if name and api_key:
            AIProvider.objects.create(
                name=name,
                provider=provider,
                api_key=api_key,
                model_name=model_name,
                base_url=base_url,
                priority=priority,
                max_requests_per_minute=max_rpm,
                is_active=is_active,
            )
            messages.success(request, f"AI Provider '{name}' added successfully.")
            return redirect("accounts:ai_provider_list")
        else:
            messages.error(request, "Name and API Key are required.")

    providers = AIProvider.PROVIDER_CHOICES
    return render(request, "accounts/ai_provider_form.html", {"providers": providers, "provider": None})


@login_required
def ai_provider_edit(request, provider_id):
    if not request.user.is_superuser:
        messages.error(request, "Access restricted to admin.")
        return redirect("home")

    provider = get_object_or_404(AIProvider, pk=provider_id)

    if request.method == "POST":
        provider.name = request.POST.get("name", "").strip()
        provider.provider = request.POST.get("provider", provider.provider)
        provider.api_key = request.POST.get("api_key", provider.api_key).strip()
        provider.model_name = request.POST.get("model_name", provider.model_name).strip()
        provider.base_url = request.POST.get("base_url", provider.base_url).strip()
        provider.priority = int(request.POST.get("priority", provider.priority))
        provider.max_requests_per_minute = int(request.POST.get("max_requests_per_minute", provider.max_requests_per_minute))
        provider.is_active = request.POST.get("is_active") == "on"

        DEFAULT_BASE_URLS = {
            "groq": "https://api.groq.com/openai/v1",
            "openai": "https://api.openai.com/v1",
            "deepseek": "https://api.deepseek.com/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "custom": "https://api.openai.com/v1",
        }

        DEFAULT_MODELS = {
            "gemini": "gemini-2.0-flash",
            "groq": "llama-3.3-70b-versatile",
            "openai": "gpt-4o-mini",
            "deepseek": "deepseek-chat",
            "openrouter": "meta-llama/llama-3.1-70b-instruct",
            "custom": "gpt-4o-mini",
        }

        if provider.provider != "gemini" and not provider.base_url:
            provider.base_url = DEFAULT_BASE_URLS.get(provider.provider, "")
        if not provider.model_name:
            provider.model_name = DEFAULT_MODELS.get(provider.provider, "gemini-2.0-flash")

        provider.save()
        messages.success(request, f"AI Provider '{provider.name}' updated successfully.")
        return redirect("accounts:ai_provider_list")

    providers = AIProvider.PROVIDER_CHOICES
    return render(request, "accounts/ai_provider_form.html", {"providers": providers, "provider": provider})


@login_required
def ai_provider_delete(request, provider_id):
    if not request.user.is_superuser:
        messages.error(request, "Access restricted to admin.")
        return redirect("home")

    provider = get_object_or_404(AIProvider, pk=provider_id)
    name = provider.name
    provider.delete()
    messages.success(request, f"AI Provider '{name}' deleted successfully.")
    return redirect("accounts:ai_provider_list")


@login_required
def ai_provider_toggle(request, provider_id):
    if not request.user.is_superuser:
        messages.error(request, "Access restricted to admin.")
        return redirect("home")

    provider = get_object_or_404(AIProvider, pk=provider_id)
    provider.is_active = not provider.is_active
    provider.save(update_fields=["is_active"])
    status = "activated" if provider.is_active else "deactivated"
    messages.success(request, f"AI Provider '{provider.name}' {status}.")
    return redirect("accounts:ai_provider_list")


@login_required
def payment_process_view(request, appointment_id):
    patient = getattr(request.user, "patient_profile", None)
    if not patient:
        messages.error(request, "Only patients can make payments.")
        return redirect("home")

    appointment = get_object_or_404(Appointment, pk=appointment_id, patient=patient)

    if appointment.payment_status == "paid":
        messages.info(request, "This appointment is already paid.")
        return redirect("patient:appointments")

    if request.method == "POST":
        payment_method = request.POST.get("payment_method", "cash")
        transaction_id = request.POST.get("transaction_id", f"TXN-{appointment.pk}-{timezone.now().timestamp()}")

        appointment.payment_status = "paid"
        appointment.payment_method = payment_method
        appointment.transaction_id = transaction_id
        appointment.paid_amount = appointment.fee_bdt
        appointment.platform_fee_bdt = (appointment.fee_bdt * Decimal("0.03")).quantize(Decimal("0.01"))
        appointment.net_doctor_payout_bdt = appointment.fee_bdt - appointment.platform_fee_bdt
        appointment.status = "confirmed"
        appointment.save()

        # Create receipt
        from prescriptions.views import _build_appointment_receipt_pdf
        receipt_buffer = _build_appointment_receipt_pdf(appointment)

        # Notify doctor
        AppNotification.objects.create(
            user=appointment.doctor.user,
            title="New Appointment Confirmed",
            message=f"Patient {patient.user.get_full_name()} booked an appointment on {appointment.appointment_date}. Payment received: {appointment.fee_bdt} BDT.",
            notification_type="booking",
            link_url=reverse("doctors:appointment_list"),
        )

        messages.success(request, f"Payment successful! Appointment confirmed. Receipt generated.")
        return redirect("patient:appointment_detail", appointment_id=appointment.pk)

    return render(request, "accounts/payment_process.html", {
        "appointment": appointment,
    })


@login_required
def doctor_analytics_view(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "Access restricted to doctors.")
        return redirect("home")

    from django.db.models import Sum, Count, Q
    from datetime import date, timedelta

    today = date.today()
    month_start = today.replace(day=1)

    # All completed appointments
    completed = Appointment.objects.filter(doctor=doctor, status="completed")
    cancelled = Appointment.objects.filter(doctor=doctor, status="cancelled")

    # This month's stats
    month_completed = completed.filter(appointment_date__gte=month_start)
    month_cancelled = cancelled.filter(appointment_date__gte=month_start)

    total_patients = Patient.objects.filter(prescriptions__doctor=doctor).distinct().count()
    total_appointments = completed.count()
    month_appointments = month_completed.count()

    # Financial calculations
    total_revenue = completed.aggregate(Sum("paid_amount"))["paid_amount__sum"] or 0
    month_revenue = month_completed.aggregate(Sum("paid_amount"))["paid_amount__sum"] or 0
    total_refunds = cancelled.aggregate(Sum("refund_amount"))["refund_amount__sum"] or 0
    month_refunds = month_cancelled.aggregate(Sum("refund_amount"))["refund_amount__sum"] or 0
    platform_fees = completed.aggregate(Sum("platform_fee_bdt"))["platform_fee_bdt__sum"] or 0
    net_earnings = total_revenue - total_refunds - platform_fees

    # Recent transactions
    recent_appointments = Appointment.objects.filter(doctor=doctor).order_by("-created_at")[:20]

    return render(request, "accounts/doctor_analytics.html", {
        "total_patients": total_patients,
        "total_appointments": total_appointments,
        "month_appointments": month_appointments,
        "total_revenue": total_revenue,
        "month_revenue": month_revenue,
        "total_refunds": total_refunds,
        "month_refunds": month_refunds,
        "platform_fees": platform_fees,
        "net_earnings": net_earnings,
        "recent_appointments": recent_appointments,
    })


@login_required
def admin_analytics_view(request):
    if not request.user.is_superuser:
        messages.error(request, "Access restricted to admin.")
        return redirect("home")

    from django.db.models import Sum, Count, Q
    from datetime import date, timedelta

    from doctors.models import Appointment, DoctorSchedule
    from prescriptions.models import Prescription, FollowUp
    from accounts.models import AppNotification

    today = date.today()
    month_start = today.replace(day=1)
    week_start = today - timedelta(days=today.weekday())

    total_doctors = Doctor.objects.count()
    total_patients = Patient.objects.count()
    total_appointments = Appointment.objects.count()
    confirmed_appointments = Appointment.objects.filter(status="confirmed").count()
    completed_appointments = Appointment.objects.filter(status="completed").count()
    cancelled_appointments = Appointment.objects.filter(status="cancelled").count()
    pending_appointments = Appointment.objects.filter(status="pending").count()
    missed_appointments = Appointment.objects.filter(status="missed").count()
    cancellation_pending = Appointment.objects.filter(status="cancellation_pending").count()

    verified_doctors = Doctor.objects.filter(is_verified=True).count()
    verified_patients = Patient.objects.filter(is_verified=True).count()
    pending_doctor_verifications = Doctor.objects.filter(verification_status="pending").count()
    pending_patient_verifications = Patient.objects.filter(verification_status="pending").count()

    total_schedules = DoctorSchedule.objects.filter(is_active=True).count()

    total_prescriptions = Prescription.objects.count()
    total_followups = FollowUp.objects.count()
    upcoming_followups = FollowUp.objects.filter(status="upcoming").count()
    completed_followups = FollowUp.objects.filter(status="completed").count()

    total_notifications = AppNotification.objects.count()
    unread_notifications = AppNotification.objects.filter(is_read=False).count()

    total_revenue = Appointment.objects.filter(payment_status="paid").aggregate(Sum("paid_amount"))["paid_amount__sum"] or 0
    month_revenue = Appointment.objects.filter(payment_status="paid", appointment_date__gte=month_start).aggregate(Sum("paid_amount"))["paid_amount__sum"] or 0
    week_revenue = Appointment.objects.filter(payment_status="paid", appointment_date__gte=week_start).aggregate(Sum("paid_amount"))["paid_amount__sum"] or 0
    total_refunds = Appointment.objects.filter(refund_amount__gt=0).aggregate(Sum("refund_amount"))["refund_amount__sum"] or 0
    partial_refunds = Appointment.objects.filter(refund_status="partial").count()
    full_refunds = Appointment.objects.filter(refund_status="full").count()
    platform_fees = Appointment.objects.filter(payment_status="paid").aggregate(Sum("platform_fee_bdt"))["platform_fee_bdt__sum"] or 0
    net_profit = platform_fees - total_refunds

    in_person_appointments = Appointment.objects.filter(consultation_type="in_person").count()
    video_appointments = Appointment.objects.filter(consultation_type="video_online").count()

    avg_appointments_per_doctor = round(total_appointments / total_doctors, 1) if total_doctors > 0 else 0
    avg_appointments_per_patient = round(total_appointments / total_patients, 1) if total_patients > 0 else 0

    recent_appointments = Appointment.objects.all().order_by("-created_at")[:20]

    daily_stats = []
    for i in range(7):
        day = today - timedelta(days=i)
        count = Appointment.objects.filter(appointment_date=day).count()
        daily_stats.append({"date": day.strftime("%Y-%m-%d"), "count": count})

    return render(request, "accounts/admin_analytics.html", {
        "total_doctors": total_doctors,
        "total_patients": total_patients,
        "total_appointments": total_appointments,
        "confirmed_appointments": confirmed_appointments,
        "completed_appointments": completed_appointments,
        "cancelled_appointments": cancelled_appointments,
        "pending_appointments": pending_appointments,
        "missed_appointments": missed_appointments,
        "cancellation_pending": cancellation_pending,
        "verified_doctors": verified_doctors,
        "verified_patients": verified_patients,
        "pending_doctor_verifications": pending_doctor_verifications,
        "pending_patient_verifications": pending_patient_verifications,
        "total_schedules": total_schedules,
        "total_prescriptions": total_prescriptions,
        "total_followups": total_followups,
        "upcoming_followups": upcoming_followups,
        "completed_followups": completed_followups,
        "total_notifications": total_notifications,
        "unread_notifications": unread_notifications,
        "total_revenue": total_revenue,
        "month_revenue": month_revenue,
        "week_revenue": week_revenue,
        "total_refunds": total_refunds,
        "partial_refunds": partial_refunds,
        "full_refunds": full_refunds,
        "platform_fees": platform_fees,
        "net_profit": net_profit,
        "in_person_appointments": in_person_appointments,
        "video_appointments": video_appointments,
        "avg_appointments_per_doctor": avg_appointments_per_doctor,
        "avg_appointments_per_patient": avg_appointments_per_patient,
        "recent_appointments": recent_appointments,
        "daily_stats": daily_stats,
    })


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

