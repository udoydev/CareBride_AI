from django.contrib import admin
from django.db.models import Count, Sum, Q
from django.utils import timezone
from django.shortcuts import render
from datetime import timedelta

from accounts.models import Patient, Doctor, AppNotification, AIProvider, SiteSettings, News
from doctors.models import Appointment
from prescriptions.models import Prescription, FollowUp, ReminderSchedule
from patient.models import PatientVisit, PatientHealthReport


class AnalyticsDashboardAdmin(admin.ModelAdmin):
    change_list_template = "admin/analytics_dashboard.html"

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path("", self.admin_site.admin_view(self.dashboard_view), name="analytics_dashboard"),
        ]
        return custom_urls + urls

    def dashboard_view(self, request):
        from accounts.models import SiteSettings
        from decimal import Decimal
        
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        
        settings_obj = SiteSettings.get_solo()
        commission_rate = Decimal(str(settings_obj.platform_commission_rate or "3.00"))

        paid_appointments = Appointment.objects.filter(payment_status="paid")
        total_platform_income = paid_appointments.aggregate(total=Sum("platform_fee_bdt"))["total"] or 0
        monthly_platform_income = paid_appointments.filter(appointment_date__gte=month_start).aggregate(total=Sum("platform_fee_bdt"))["total"] or 0
        weekly_platform_income = paid_appointments.filter(appointment_date__gte=week_start).aggregate(total=Sum("platform_fee_bdt"))["total"] or 0
        
        total_refunds = paid_appointments.filter(refund_amount__gt=0).aggregate(total=Sum("refund_amount"))["total"] or 0
        net_platform_income = max((total_platform_income or 0) - (total_refunds or 0), 0)
        
        total_appointments = Appointment.objects.count()
        total_patients = Patient.objects.count()
        total_doctors = Doctor.objects.count()

        recent_appointments = Appointment.objects.select_related("patient__user", "doctor__user").order_by("-appointment_date", "-start_time")[:15]

        # Doctor stats for the dashboard
        doctor_stats = []
        for doc in Doctor.objects.all().select_related("user")[:10]:
            doc_appointments = Appointment.objects.filter(doctor=doc)
            doctor_stats.append({
                "id": doc.pk,
                "name": doc.user.get_full_name() or doc.user.username,
                "specialty": doc.specialty or "General",
                "total_appointments": doc_appointments.count(),
                "completed": doc_appointments.filter(status="completed").count(),
                "missed": doc_appointments.filter(status="missed").count(),
                "cancelled": doc_appointments.filter(status="cancelled").count(),
                "total_patients": doc_appointments.values("patient").distinct().count(),
                "total_earnings": doc_appointments.filter(payment_status="paid").aggregate(total=Sum("net_doctor_payout_bdt"))["total"] or 0,
            })

        daily_revenue = (
            paid_appointments
            .values("appointment_date")
            .annotate(income=Sum("fee_bdt"))
            .order_by("appointment_date")[:30]
        )
        revenue_labels = [str(item["appointment_date"]) for item in daily_revenue]
        revenue_values = [float(item["income"] or 0) for item in daily_revenue]

        monthly_revenue_series = []
        for i in range(11, -1, -1):
            m = today - timedelta(days=30*i)
            month_s = m.replace(day=1)
            if m.month == 12:
                month_e = m.replace(year=m.year+1, month=1, day=1) - timedelta(days=1)
            else:
                month_e = m.replace(month=m.month+1, day=1) - timedelta(days=1)
            rev = paid_appointments.filter(appointment_date__range=(month_s, month_e)).aggregate(total=Sum("fee_bdt"))["total"] or 0
            monthly_revenue_series.append({
                "label": month_s.strftime("%b %Y"),
                "value": float(rev),
            })

        monthly_revenue_labels = [item["label"] for item in monthly_revenue_series]
        monthly_revenue_values = [item["value"] for item in monthly_revenue_series]

        status_counts = {
            "completed": Appointment.objects.filter(status="completed").count(),
            "missed": Appointment.objects.filter(status="missed").count(),
            "cancelled": Appointment.objects.filter(status="cancelled").count(),
            "pending": Appointment.objects.filter(status="pending").count(),
            "confirmed": Appointment.objects.filter(status="confirmed").count(),
        }

        news_list = News.objects.filter(is_active=True).order_by("-created_at")[:10]

        if request.method == "POST":
            title = request.POST.get("title", "").strip()
            message = request.POST.get("message", "").strip()
            target = request.POST.get("target_audience", "all")
            is_urgent = bool(request.POST.get("is_urgent"))
            if title and message:
                News.objects.create(
                    title=title,
                    message=message,
                    target_audience=target,
                    is_urgent=is_urgent,
                )
                messages.success(request, "News published successfully.")
                return redirect("admin:analytics_dashboard")

        context = {
            "title": "CareBridge Platform Admin",
            "total_platform_income": total_platform_income,
            "monthly_platform_income": monthly_platform_income,
            "weekly_platform_income": weekly_platform_income,
            "total_refunds": total_refunds,
            "net_platform_income": net_platform_income,
            "commission_rate": commission_rate,
            "total_appointments": total_appointments,
            "total_patients": total_patients,
            "total_doctors": total_doctors,
            "recent_appointments": recent_appointments,
            "today": today,
            "revenue_labels": revenue_labels,
            "revenue_values": revenue_values,
            "monthly_revenue_labels": monthly_revenue_labels,
            "monthly_revenue_values": monthly_revenue_values,
            "status_counts": status_counts,
            "news_list": news_list,
            "doctor_stats": doctor_stats,
            "income_breakdown": {
                "site_commission": float(total_platform_income),
                "doctor_payout": float(paid_appointments.aggregate(total=Sum("net_doctor_payout_bdt"))["total"] or 0),
                "total_refunds": float(total_refunds),
                "gross_fees": float(total_platform_income + (paid_appointments.aggregate(total=Sum("net_doctor_payout_bdt"))["total"] or 0)),
            },
        }
        return render(request, "admin/analytics_dashboard.html", context)


admin.site.index_template = "admin/analytics_dashboard.html"
admin.site.index_title = "CareBridge Analytics"
admin.site.site_header = "CareBridge Admin"
admin.site.site_title = "CareBridge Admin"


def custom_admin_index(request, extra_context=None):
    return AnalyticsDashboardAdmin(AIProvider, admin.site).dashboard_view(request)


admin.site.index = custom_admin_index
