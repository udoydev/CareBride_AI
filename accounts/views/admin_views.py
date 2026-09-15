from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import AIProvider, AppNotification, Doctor, Patient
from doctors.models import Appointment


@login_required
def admin_unverified_dashboard_view(request):
    """Dedicated Admin Dashboard listing all unverified Patients & Doctors, as well as overdue payment verification appeals for instant resolution & full refunds."""
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "Access restricted to CareBridge Admin.")
        return redirect("home")

    if request.method == "POST":
        action_type = request.POST.get("action_type")
        user_id = request.POST.get("user_id")
        appointment_id = request.POST.get("appointment_id")

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

        elif action_type == "appeal_full_refund":
            appointment = get_object_or_404(Appointment, pk=appointment_id)
            patient = appointment.patient
            refund_amount = appointment.fee_bdt

            appointment.status = "cancelled"
            appointment.payment_status = "refunded"
            appointment.refund_status = "full"
            appointment.refund_amount = refund_amount
            appointment.platform_fee_bdt = Decimal("0.00")
            appointment.net_doctor_payout_bdt = Decimal("0.00")
            appointment.payment_appeal_status = "approved_refund"
            appointment.payment_appeal_admin_notes = request.POST.get("admin_notes", "Full refund granted by admin due to overdue payment verification appeal.")
            appointment.save()

            patient.balance = (patient.balance or Decimal("0.00")) + refund_amount
            patient.save(update_fields=["balance"])

            AppNotification.objects.create(
                user=patient.user,
                title="✓ Full Refund Issued to Wallet",
                message=f"CareBridge Admin reviewed your payment appeal for Appointment #{appointment.id} with Dr. {appointment.doctor.user.get_full_name()} and credited a 100% full refund of {refund_amount} BDT to your wallet.",
                notification_type="booking",
                link_url=reverse("patient:appointments"),
            )

            AppNotification.objects.create(
                user=appointment.doctor.user,
                title="Appointment Cancelled & Refunded by Admin",
                message=f"Appointment #{appointment.id} with {patient.user.get_full_name()} was cancelled with full refund by Admin due to overdue payment verification appeal.",
                notification_type="booking",
                link_url=reverse("doctors:appointment_list"),
            )

            messages.success(request, f"✓ Full refund of {refund_amount} BDT has been credited to Patient {patient.user.get_full_name() or patient.user.email}'s wallet!")

        elif action_type == "appeal_verify_payment":
            appointment = get_object_or_404(Appointment, pk=appointment_id)
            appointment.payment_status = "paid"
            appointment.payment_verified = True
            appointment.payment_verified_at = timezone.now()
            appointment.status = "confirmed"
            appointment.paid_amount = appointment.fee_bdt
            appointment.payment_appeal_status = "approved_payment"
            appointment.save()

            AppNotification.objects.create(
                user=appointment.patient.user,
                title="✓ Payment Verified & Booking Confirmed",
                message=f"Admin verified your payment for Appointment #{appointment.id} on {appointment.appointment_date}. Your booking is confirmed.",
                notification_type="booking",
                link_url=reverse("patient:appointment_detail", kwargs={"appointment_id": appointment.pk}),
            )
            messages.success(request, f"✓ Payment verified and Appointment #{appointment.id} confirmed!")

        elif action_type == "appeal_reject":
            appointment = get_object_or_404(Appointment, pk=appointment_id)
            appointment.payment_appeal_status = "rejected"
            appointment.payment_appeal_admin_notes = request.POST.get("admin_notes", "Payment appeal rejected by admin.")
            appointment.save()

            AppNotification.objects.create(
                user=appointment.patient.user,
                title="Payment Appeal Review",
                message=f"Your payment appeal for Appointment #{appointment.id} was reviewed by Admin. Reason: {appointment.payment_appeal_admin_notes}",
                notification_type="booking",
                link_url=reverse("patient:appointments"),
            )
            messages.info(request, f"Payment appeal for Appointment #{appointment.id} set to rejected.")

        return redirect("accounts:admin_unverified_dashboard")

    unverified_patients = Patient.objects.filter(is_verified=False).select_related("user").order_by("-id")
    unverified_doctors = Doctor.objects.filter(is_verified=False).select_related("user").order_by("-id")

    overdue_appeals = Appointment.objects.filter(
        Q(is_payment_appeal_requested=True) | Q(payment_status="pending_verification")
    ).select_related("patient__user", "doctor__user").order_by("-updated_at")

    return render(request, "accounts/admin_unverified_dashboard.html", {
        "unverified_patients": unverified_patients,
        "unverified_doctors": unverified_doctors,
        "overdue_appeals": overdue_appeals,
        "pending_patients_count": unverified_patients.count(),
        "pending_doctors_count": unverified_doctors.count(),
        "pending_appeals_count": overdue_appeals.count(),
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
