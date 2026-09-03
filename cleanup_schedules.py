import os
import sys
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carebridge.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from doctors.models import DoctorSchedule
from accounts.models import Doctor

print("=== Cleaning up duplicate schedules ===")
doctors = Doctor.objects.all()
for doctor in doctors:
    for day in DoctorSchedule.DAY_CHOICES:
        day_code = day[0]
        schedules = DoctorSchedule.objects.filter(doctor=doctor, day_of_week=day_code).order_by('id')
        count = schedules.count()
        if count > 1:
            print(f"Doctor {doctor.user.get_full_name()}: {count} schedules for {day_code}")
            # Keep the first one, delete the rest
            keep = schedules.first()
            for sched in schedules[1:]:
                print(f"  Deleting duplicate ID {sched.id}")
                sched.delete()
        elif count == 1:
            pass  # OK
        else:
            pass  # No schedule for this day

print("\n=== Verifying cleanup ===")
for doctor in doctors:
    for day in DoctorSchedule.DAY_CHOICES:
        day_code = day[0]
        count = DoctorSchedule.objects.filter(doctor=doctor, day_of_week=day_code).count()
        if count > 1:
            print(f"STILL DUPLICATE: Doctor {doctor.user.get_full_name()}, {day_code}: {count}")

print("Cleanup complete!")
