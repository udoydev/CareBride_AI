from django.contrib import admin, messages
from django.utils.html import format_html, mark_safe
from decimal import Decimal
from .models import DoctorSchedule, Appointment


@admin.register(DoctorSchedule)
class DoctorScheduleAdmin(admin.ModelAdmin):
    list_display = ("doctor", "day_of_week", "start_time", "end_time", "is_active")
    list_filter = ("day_of_week", "is_active")
    search_fields = ("doctor__user__first_name", "doctor__user__last_name", "doctor__user__email")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        "apt_id_display",
        "patient_info",
        "doctor_info",
        "schedule_info",
        "fee_and_tx",
        "payment_proof_display",
        "status_badge",
        "payment_status_badge",
        "appeal_info",
    )
    list_filter = (
        ("doctor", admin.RelatedOnlyFieldListFilter),
        "status",
        "payment_status",
        "consultation_type",
        "is_payment_appeal_requested",
        "payment_appeal_status",
        "refund_status",
        "appointment_date",
    )
    search_fields = (
        "id",
        "patient__user__first_name",
        "patient__user__last_name",
        "patient__user__email",
        "doctor__user__first_name",
        "doctor__user__last_name",
        "doctor__user__email",
        "doctor__specialty",
        "doctor__clinic_name",
        "transaction_id",
        "payment_notes",
        "payment_appeal_reason",
    )
    date_hierarchy = "appointment_date"
    ordering = ("-id",)
    list_per_page = 20

    def get_search_results(self, request, queryset, search_term):
        if not search_term or not search_term.strip():
            return super().get_search_results(request, queryset, search_term)

        from django.db.models import Q, Value
        from django.db.models.functions import Concat

        term = search_term.strip()
        clean_term = term
        if clean_term.upper().startswith("#APT-"):
            clean_term = clean_term[5:].strip()

        # Annotate full names for accurate string matching
        queryset = queryset.annotate(
            doc_full_name=Concat(
                Value("Dr. "), "doctor__user__first_name", Value(" "), "doctor__user__last_name"
            ),
            doc_simple_name=Concat(
                "doctor__user__first_name", Value(" "), "doctor__user__last_name"
            ),
            pat_full_name=Concat(
                "patient__user__first_name", Value(" "), "patient__user__last_name"
            ),
        )

        q_objects = Q()

        # 1. Match ID if numeric
        if clean_term.isdigit():
            q_objects |= Q(id=clean_term)

        # 2. Whole query matching
        q_objects |= Q(doc_full_name__icontains=clean_term)
        q_objects |= Q(doc_simple_name__icontains=clean_term)
        q_objects |= Q(pat_full_name__icontains=clean_term)
        q_objects |= Q(doctor__user__email__icontains=clean_term)
        q_objects |= Q(patient__user__email__icontains=clean_term)
        q_objects |= Q(doctor__specialty__icontains=clean_term)
        q_objects |= Q(doctor__clinic_name__icontains=clean_term)
        q_objects |= Q(transaction_id__icontains=clean_term)
        q_objects |= Q(payment_notes__icontains=clean_term)

        # 3. Multi-word search scoped per entity (Doctor OR Patient)
        # Prevents word1 matching Patient and word2 matching Doctor
        words = clean_term.split()
        if len(words) > 1:
            doc_q = Q()
            pat_q = Q()
            for w in words:
                doc_q &= (
                    Q(doctor__user__first_name__icontains=w)
                    | Q(doctor__user__last_name__icontains=w)
                    | Q(doctor__user__email__icontains=w)
                    | Q(doctor__specialty__icontains=w)
                )
                pat_q &= (
                    Q(patient__user__first_name__icontains=w)
                    | Q(patient__user__last_name__icontains=w)
                    | Q(patient__user__email__icontains=w)
                )
            q_objects |= doc_q
            q_objects |= pat_q

        return queryset.filter(q_objects).distinct(), False

    fieldsets = (
        ("📌 Basic Information", {
            "fields": ("patient", "doctor", "appointment_date", "start_time", "end_time", "consultation_type", "status", "chief_complaint")
        }),
        ("💳 Payment & Verification Proof", {
            "fields": ("fee_bdt", "payment_status", "payment_method", "transaction_id", "payment_notes", "payment_proof", "payment_proof_detail_preview")
        }),
        ("⚖️ Payment Appeal & Refund Management", {
            "fields": ("is_payment_appeal_requested", "payment_appeal_status", "payment_appeal_reason", "payment_appeal_submitted_at", "payment_appeal_admin_notes", "refund_status", "refund_amount")
        }),
    )

    readonly_fields = ("payment_proof_detail_preview", "payment_appeal_submitted_at")

    actions = [
        "grant_full_refund_to_wallet",
        "verify_and_confirm_payment",
        "mark_as_confirmed",
        "mark_as_cancelled",
        "mark_as_completed",
    ]

    # --- Display Helpers ---
    @admin.display(description="APT #", ordering="id")
    def apt_id_display(self, obj):
        return format_html('<span style="font-family: monospace; font-weight: bold; color: #4f46e5;">#APT-{}</span>', obj.id)

    @admin.display(description="Patient")
    def patient_info(self, obj):
        if obj.patient:
            name = obj.patient.user.get_full_name() or obj.patient.user.username
            return format_html('<b>{}</b><br><span style="color: #6b7280; font-size: 11px;">{}</span>', name, obj.patient.user.email)
        return "-"

    @admin.display(description="Doctor")
    def doctor_info(self, obj):
        if obj.doctor:
            name = obj.doctor.get_full_name()
            spec = obj.doctor.specialty or "General"
            return format_html('<b>{}</b><br><span style="color: #0d9488; font-size: 11px;">{}</span>', name, spec)
        return "-"

    @admin.display(description="Date & Time", ordering="appointment_date")
    def schedule_info(self, obj):
        return format_html('<b>{}</b><br><span style="color: #4b5563; font-size: 11px;">{}</span>', obj.appointment_date.strftime('%d %b %Y'), obj.start_time.strftime('%I:%M %p'))

    @admin.display(description="Fee & TxID")
    def fee_and_tx(self, obj):
        tx = obj.transaction_id or "No TxID"
        method = (obj.payment_method or "bKash").upper()
        return format_html('<b style="color: #059669;">৳{}</b><br><span style="color: #6b7280; font-size: 11px;">{} • {}</span>', obj.fee_bdt, method, tx)

    @admin.display(description="Payment Proof")
    def payment_proof_display(self, obj):
        if obj.payment_proof:
            return format_html(
                '<a href="{}" target="_blank" style="display: inline-block; background: #0f766e; color: #ffffff; padding: 3px 10px; border-radius: 12px; font-weight: bold; text-decoration: none; font-size: 11px;">📄 View Proof</a>',
                obj.payment_proof.url
            )
        return mark_safe('<span style="color: #9ca3af; font-style: italic;">No File</span>')

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        colors = {
            "confirmed": ("#dcfce7", "#166534"),
            "pending": ("#fef3c7", "#92400e"),
            "completed": ("#f3f4f6", "#374151"),
            "cancelled": ("#fee2e2", "#991b1b"),
            "missed": ("#fee2e2", "#991b1b"),
        }
        bg, fg = colors.get(obj.status, ("#e5e7eb", "#374151"))
        return format_html('<span style="background: {}; color: {}; padding: 3px 10px; border-radius: 12px; font-weight: bold; font-size: 11px;">{}</span>', bg, fg, obj.get_status_display())

    @admin.display(description="Payment Status", ordering="payment_status")
    def payment_status_badge(self, obj):
        colors = {
            "paid": ("#dcfce7", "#166534"),
            "pending_verification": ("#f3e8ff", "#6b21a8"),
            "pending": ("#fef3c7", "#92400e"),
            "refunded": ("#dbeafe", "#1e40af"),
        }
        bg, fg = colors.get(obj.payment_status, ("#e5e7eb", "#374151"))
        return format_html('<span style="background: {}; color: {}; padding: 3px 10px; border-radius: 12px; font-weight: bold; font-size: 11px;">{}</span>', bg, fg, obj.payment_status.replace('_', ' ').title())

    @admin.display(description="Appeal Status")
    def appeal_info(self, obj):
        if obj.is_payment_appeal_requested:
            reason = obj.payment_appeal_reason or "Verification overdue appeal"
            short_reason = reason[:40] + ("..." if len(reason) > 40 else "")
            if obj.payment_appeal_status == "pending" and obj.status not in ["cancelled", "refunded"]:
                return format_html(
                    '<div style="background: #ffe4e6; color: #9f1239; padding: 4px 8px; border-radius: 8px; font-size: 11px; max-width: 180px;">'
                    '<b>⚠️ Appeal Pending</b><br><span style="font-style: italic;">"{}"</span></div>',
                    short_reason
                )
            elif obj.payment_appeal_status == "approved_refund" or obj.payment_status == "refunded":
                return format_html(
                    '<div style="background: #dbeafe; color: #1e40af; padding: 4px 8px; border-radius: 8px; font-size: 11px; max-width: 180px;">'
                    '<b>✓ Resolved (Refunded)</b><br><span style="font-style: italic;">"{}"</span></div>',
                    short_reason
                )
            elif obj.payment_appeal_status == "approved_payment":
                return format_html(
                    '<div style="background: #dcfce7; color: #166534; padding: 4px 8px; border-radius: 8px; font-size: 11px; max-width: 180px;">'
                    '<b>✓ Resolved (Confirmed)</b><br><span style="font-style: italic;">"{}"</span></div>',
                    short_reason
                )
            else:
                return format_html(
                    '<div style="background: #f3f4f6; color: #374151; padding: 4px 8px; border-radius: 8px; font-size: 11px; max-width: 180px;">'
                    '<b>Resolved ({})</b></div>',
                    obj.get_payment_appeal_status_display()
                )
        elif obj.is_verification_overdue and obj.payment_status == 'pending_verification':
            return mark_safe('<span style="background: #fef3c7; color: #92400e; padding: 3px 8px; border-radius: 8px; font-weight: bold; font-size: 11px;">⏰ Overdue</span>')
        return mark_safe('<span style="color: #9ca3af;">-</span>')

    @admin.display(description="Uploaded Payment Proof Image")
    def payment_proof_detail_preview(self, obj):
        if obj.payment_proof:
            return format_html(
                '<div><a href="{0}" target="_blank"><img src="{0}" style="max-height: 250px; max-width: 100%; border-radius: 12px; border: 2px solid #0d9488; margin-bottom: 8px;" /></a><br>'
                '<a href="{0}" target="_blank" style="color: #0d9488; font-weight: bold;">🔍 Click to Open Full Proof Image in New Tab</a></div>',
                obj.payment_proof.url
            )
        return mark_safe('<span style="color: #9ca3af; font-style: italic;">No payment proof image uploaded for this appointment.</span>')

    # --- Actions ---
    @admin.action(description="💰 Grant 100 Percent Full Refund to Patient Wallet for Selected Appeals")
    def grant_full_refund_to_wallet(self, request, queryset):
        refunded_count = 0
        for apt in queryset:
            refund_amount = apt.fee_bdt
            apt.status = "cancelled"
            apt.payment_status = "refunded"
            apt.refund_status = "full"
            apt.refund_amount = refund_amount
            apt.platform_fee_bdt = Decimal("0.00")
            apt.net_doctor_payout_bdt = Decimal("0.00")
            apt.payment_appeal_status = "approved_refund"
            apt.payment_appeal_admin_notes = "100% Full refund granted via Django Admin."
            apt.save()

            patient = apt.patient
            patient.balance = (patient.balance or Decimal("0.00")) + refund_amount
            patient.save(update_fields=["balance"])
            refunded_count += 1

        messages.success(request, f"✓ Successfully granted 100% full refund to wallet for {refunded_count} appointment(s).")

    @admin.action(description="✓ Confirm Payment & Approve Booking")
    def verify_and_confirm_payment(self, request, queryset):
        count = 0
        for apt in queryset:
            apt.payment_status = "paid"
            apt.payment_verified = True
            apt.status = "confirmed"
            apt.paid_amount = apt.fee_bdt
            apt.payment_appeal_status = "approved_payment"
            apt.save()
            count += 1
        messages.success(request, f"✓ Payment verified and {count} appointment(s) confirmed.")

    @admin.action(description="Mark selected appointments as Confirmed")
    def mark_as_confirmed(self, request, queryset):
        count = queryset.update(status="confirmed")
        messages.success(request, f"{count} appointment(s) updated to Confirmed.")

    @admin.action(description="Mark selected appointments as Cancelled")
    def mark_as_cancelled(self, request, queryset):
        from decimal import Decimal
        count = 0
        for appointment in queryset:
            appointment.status = "cancelled"
            if appointment.payment_status == "paid":
                appointment.payment_status = "refunded"
                appointment.refund_status = "full"
                appointment.refund_amount = appointment.fee_bdt
                appointment.platform_fee_bdt = Decimal("0.00")
                appointment.net_doctor_payout_bdt = Decimal("0.00")
            appointment.save()
            count += 1
        messages.success(request, f"{count} appointment(s) updated to Cancelled.")

    @admin.action(description="Mark selected appointments as Completed")
    def mark_as_completed(self, request, queryset):
        count = queryset.update(status="completed")
        messages.success(request, f"{count} appointment(s) updated to Completed.")
