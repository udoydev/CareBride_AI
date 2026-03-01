from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.utils import timezone
from prescriptions.models import ReminderSchedule, FollowUp
from accounts.models import AppNotification


class Command(BaseCommand):
    help = "Sends email and in-app notifications for scheduled medication doses (10 mins prior) and follow-up reminders."

    def handle(self, *args, **options):
        now = timezone.localtime()
        current_time = now.time()
        today = now.date()

        self.stdout.write(f"Running CareBridgeAI reminder dispatcher at {now}...")

        # Calculate window: current time to +15 minutes ahead
        from datetime import time as dt_time, timedelta, datetime
        window_end_dt = datetime.combine(today, current_time) + timedelta(minutes=15)
        window_end_time = window_end_dt.time()

        # 1. Process Medication Dose Reminders (10 mins before scheduled time)
        # Find doses scheduled between now+10min and now+15min (to catch upcoming doses)
        upcoming_start = (datetime.combine(today, current_time) + timedelta(minutes=10)).time()
        
        doses = ReminderSchedule.objects.filter(
            scheduled_date=today,
            status="pending",
            reminder_time__gte=upcoming_start,
            reminder_time__lte=window_end_time,
        ).select_related(
            "prescription_item__medicine",
            "prescription_item__prescription__patient__user"
        )

        sent_doses = 0
        for dose in doses:
            patient_user = dose.prescription_item.prescription.patient.user
            med_name = dose.prescription_item.medicine.brand_name
            dosage = dose.prescription_item.dosage
            timing = dose.prescription_item.get_timing_relation_to_meal_display()
            dose_time = dose.reminder_time or "09:00"

            subject = f"💊 CareBridgeAI Dose Reminder: {med_name} ({dosage}) in 10 minutes"
            body = (
                f"Dear {patient_user.get_full_name() or patient_user.email},\n\n"
                f"This is your automated CareBridgeAI medication reminder.\n\n"
                f"⏰ Your dose is scheduled for: {dose_time}\n\n"
                f"• Medicine: {med_name}\n"
                f"• Dosage: {dosage}\n"
                f"• Timing: {timing}\n\n"
                f"Please take your medication as directed by your physician.\n\n"
                f"Best regards,\n"
                f"CareBridgeAI Healthcare Team"
            )

            # Send Email
            if patient_user.email:
                try:
                    send_mail(
                        subject=subject,
                        message=body,
                        from_email=None,
                        recipient_list=[patient_user.email],
                        fail_silently=True,
                    )
                except Exception:
                    pass

            # Create In-App Notification
            AppNotification.objects.create(
                user=patient_user,
                title=f"💊 Dose Reminder: {med_name}",
                message=f"Scheduled dose in 10 minutes at {dose_time}. Please take your medication.",
                notification_type="dose_reminder",
                link_url="/patient/doses/today/"
            )
            sent_doses += 1

        # 2. Process Scheduled Follow-up Reminders (sent on the day)
        followups = FollowUp.objects.filter(scheduled_date=today, status="upcoming").select_related(
            "prescription__patient__user",
            "prescription__doctor__user"
        )

        sent_followups = 0
        for fu in followups:
            patient_user = fu.prescription.patient.user
            doctor_name = fu.prescription.doctor.user.get_full_name() or fu.prescription.doctor.user.username

            subject = f"📅 CareBridgeAI Today's Follow-up Reminder with Dr. {doctor_name}"
            body = (
                f"Dear {patient_user.get_full_name() or patient_user.email},\n\n"
                f"You have a medical follow-up appointment scheduled for TODAY with Dr. {doctor_name}.\n\n"
                f"• Date: {fu.scheduled_date}\n"
                f"• Clinic: {fu.prescription.doctor.clinic_name or 'CareBridgeAI Health Center'}\n"
                f"• Address: {fu.prescription.doctor.location_text or 'Uttara Medical Zone, Dhaka'}\n\n"
                f"Please make sure to attend your appointment.\n\n"
                f"Best regards,\n"
                f"CareBridgeAI Healthcare Team"
            )

            # Send Email
            if patient_user.email:
                try:
                    send_mail(
                        subject=subject,
                        message=body,
                        from_email=None,
                        recipient_list=[patient_user.email],
                        fail_silently=True,
                    )
                except Exception:
                    pass

            # Create In-App Notification
            AppNotification.objects.create(
                user=patient_user,
                title=f"📅 Today's Follow-up Appointment",
                message=f"Your follow-up with Dr. {doctor_name} is scheduled for today.",
                notification_type="followup_reminder",
                link_url="/patient/follow-ups/"
            )
            sent_followups += 1

        self.stdout.write(self.style.SUCCESS(f"✓ Dispatched {sent_doses} dose reminders and {sent_followups} follow-up notifications."))
