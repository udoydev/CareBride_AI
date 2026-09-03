import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carebridge.settings')
import django
django.setup()
from django.test import Client
from accounts.models import Doctor
from carebridge.reports_utils import compute_appointment_report

doctor = Doctor.objects.first()
c = Client()
c.force_login(doctor.user)

r = c.get('/doctors/reports/')
print(f'Reports page: {r.status_code}')

# Check metrics
from doctors.models import Appointment
qs = Appointment.objects.filter(doctor=doctor)
metrics = compute_appointment_report(qs)
print(f'Total Earnings: {metrics["income_total"]}')
print(f'Platform Profit: {metrics["site_charge"]}')
print(f'Net Profit (Doctor): {metrics["revenue"]}')
print(f'Total Refund: {metrics["refund_total"]}')
print(f'Cancelled: {metrics["cancelled_count"]}')

# Check for negative values
if metrics['revenue'] < 0:
    print('WARNING: Net profit is negative!')
else:
    print('OK: Net profit is positive')
