import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carebridge.settings')
import django
django.setup()
from doctors.models import Appointment
from decimal import Decimal

print("Fixing ALL appointment financial data...")

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
    if old_platform != apt.platform_fee_bdt or old_net != apt.net_doctor_payout_bdt or old_fee != apt.fee_bdt:
        apt.save(update_fields=["platform_fee_bdt", "net_doctor_payout_bdt"])
        fixed += 1
        print(f"Fixed #{apt.pk} ({apt.status}): fee={fee}, platform {old_platform} -> {apt.platform_fee_bdt}, net {old_net} -> {apt.net_doctor_payout_bdt}")

print(f"\nTotal appointments: {appointments.count()}")
print(f"Fixed: {fixed}")

# Verify no inconsistencies
inconsistent = 0
for apt in appointments:
    fee = Decimal(str(apt.fee_bdt or 0))
    platform = Decimal(str(apt.platform_fee_bdt or 0))
    net = Decimal(str(apt.net_doctor_payout_bdt or 0))
    refund = Decimal(str(apt.refund_amount or 0))
    
    if apt.payment_status == "paid":
        expected_platform = (fee * Decimal("0.03")).quantize(Decimal("0.01"))
        expected_net = fee - expected_platform - refund
        if platform != expected_platform or net != expected_net:
            inconsistent += 1
            print(f"INCONSISTENT #{apt.pk}: platform={platform} (expected {expected_platform}), net={net} (expected {expected_net})")

print(f"\nInconsistent: {inconsistent}")
