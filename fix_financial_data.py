import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carebridge.settings')
import django
django.setup()
from doctors.models import Appointment
from decimal import Decimal

print("Fixing existing appointment financial data...")

appointments = Appointment.objects.all()
fixed = 0
for apt in appointments:
    old_platform = apt.platform_fee_bdt
    old_net = apt.net_doctor_payout_bdt
    
    # Trigger recalculation via save
    apt.save()
    
    if old_platform != apt.platform_fee_bdt or old_net != apt.net_doctor_payout_bdt:
        fixed += 1
        print(f"Fixed #{apt.pk}: platform {old_platform} -> {apt.platform_fee_bdt}, net {old_net} -> {apt.net_doctor_payout_bdt}")

print(f"\nTotal appointments: {appointments.count()}")
print(f"Fixed: {fixed}")

# Show summary
from django.db.models import Sum
paid = Appointment.objects.filter(payment_status="paid")
print(f"\nPaid appointments: {paid.count()}")
print(f"Total fee: {paid.aggregate(Sum('fee_bdt'))['fee_bdt__sum'] or 0}")
print(f"Total platform fee: {paid.aggregate(Sum('platform_fee_bdt'))['platform_fee_bdt__sum'] or 0}")
print(f"Total net payout: {paid.aggregate(Sum('net_doctor_payout_bdt'))['net_doctor_payout_bdt__sum'] or 0}")

missed = Appointment.objects.filter(status="missed")
print(f"\nMissed appointments: {missed.count()}")
for apt in missed[:5]:
    print(f"  #{apt.pk}: fee={apt.fee_bdt}, platform={apt.platform_fee_bdt}, net={apt.net_doctor_payout_bdt}")
