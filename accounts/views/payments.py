from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import AppNotification
from doctors.models import Appointment


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
        transaction_id = request.POST.get("transaction_id", "").strip()
        payment_notes = request.POST.get("payment_notes", "").strip()
        payment_proof = request.FILES.get("payment_proof")

        if not transaction_id and not payment_proof:
            messages.error(request, "Please provide either transaction ID or payment proof screenshot.")
            return redirect("accounts:payment_process", appointment_id=appointment.pk)

        appointment.payment_method = payment_method
        appointment.transaction_id = transaction_id or f"TXN-{appointment.pk}-{timezone.now().timestamp()}"
        appointment.payment_notes = payment_notes
        if payment_proof:
            appointment.payment_proof = payment_proof
        appointment.payment_status = "pending_verification"
        appointment.save()

        # Notify doctor for payment verification
        AppNotification.objects.create(
            user=appointment.doctor.user,
            title="💳 Payment Verification Required",
            message=f"Patient {patient.user.get_full_name()} has submitted payment proof for appointment on {appointment.appointment_date}. Please verify the payment.",
            notification_type="booking",
            link_url=reverse("doctors:verify_payment", kwargs={"appointment_id": appointment.pk}),
        )

        messages.success(request, "Payment proof submitted successfully. Please wait for doctor to verify your payment.")
        return redirect("patient:appointments")

    return render(request, "accounts/payment_process.html", {
        "appointment": appointment,
    })
