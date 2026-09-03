import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carebridge.settings')
import django
django.setup()
from doctors.models import Appointment
from decimal import Decimal

print("Force-fixing ALL appointment financial data...")

appointments = Appointment.objects.all()
fixed = 0
for apt in appointments:
    old_platform = apt.platform_fee_bdt
    old_net = apt.net_doctor_payout_bdt
    old_fee = apt.fee_bdt
    
    # Force recalculation based on current payment_status
    fee = Decimal(str(apt.fee_bdt or 0))
    refund = Decimal(str(apt.refund_amount or 0))
    
    if apt.payment_status == "paid":
        apt.platform_fee_bdt = (fee * Decimal("0.03")).quantize(Decimal("0.01"))
        apt.net_doctor_payout_bdt = fee - apt.platform_fee_bdt - refund
    else:
        apt.platform_fee_bdt = Decimal("0.00")
        apt.net_doctor_payout_bdt = Decimal("0.00")
    
    # Only save if changed
    if old_platform != apt.platform_fee_bdt or old_net != apt.net_doctor_payout_bdt:
        apt.save(update_fields=["platform_fee_bdt", "net_doctor_payout_bdt"])
        fixed += 1
        print(f"Fixed #{apt.pk} ({apt.status}): fee={fee}, platform {old_platform} -> {apt.platform_fee_bdt}, net {old_net} -> {apt.net_doctor_payout_bdt}")

print(f"\nTotal appointments: {appointments.count()}")
print(f"Fixed: {fixed}")

# Verify no negative net payouts
negative = Appointment.objects.filter(net_doctor_payout_bdt__lt=0)
print(f"\nAppointments with negative net payout: {negative.count()}")
for apt in negative:
    print(f"  #{apt.pk}: fee={apt.fee_bdt}, platform={apt.platform_fee_bdt}, net={apt.net_doctor_payout_bdt}, refund={apt.refund_amount}, status={apt.status}, payment={apt.payment_status}")

# Show summary by status
from django.db.models import Sum
for status, label in Appointment.STATUS_CHOICES:
    qs = Appointment.objects.filter(status=status)
    if qs.exists():
        fee_sum = qs.aggregate(Sum('fee_bdt'))['fee_bdt__sum'] or 0
        platform_sum = qs.aggregate(Sum('platform_fee_bdt'))['platform_fee_bdt__sum'] or 0
        net_sum = qs.aggregate(Sum('net_doctor_payout_bdt'))['net_doctor_payout_bdt__sum'] or 0
        print(f"\n{label} ({qs.count()}): fee={fee_sum}, platform={platform_sum}, net={net_sum}")
