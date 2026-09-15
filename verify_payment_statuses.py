import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carebridge.settings')
import django
django.setup()
from doctors.models import Appointment

print("=== Valid PAYMENT_STATUS_CHOICES ===")
for val, label in Appointment.PAYMENT_STATUS_CHOICES:
    print(f"  {val}: {label}")

print("\n=== Valid STATUS_CHOICES ===")
for val, label in Appointment.STATUS_CHOICES:
    print(f"  {val}: {label}")

print("\n=== Valid PAYMENT_APPEAL_STATUS_CHOICES ===")
for val, label in Appointment.PAYMENT_APPEAL_STATUS_CHOICES:
    print(f"  {val}: {label}")

print("\n=== Database payment_status distribution ===")
from django.db.models import Count
qs = Appointment.objects.all().values('payment_status').annotate(count=Count('id')).order_by('-count')
for row in qs:
    print(f"  {row['payment_status']}: {row['count']}")

print("\n=== Database status distribution ===")
qs = Appointment.objects.all().values('status').annotate(count=Count('id')).order_by('-count')
for row in qs:
    print(f"  {row['status']}: {row['count']}")

print("\n=== Database payment_appeal_status distribution ===")
qs = Appointment.objects.all().values('payment_appeal_status').annotate(count=Count('id')).order_by('-count')
for row in qs:
    print(f"  {row['payment_appeal_status']}: {row['count']}")
