import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carebridge.settings')
import django
django.setup()
from django.test import Client
from accounts.models import Doctor
from doctors.models import Appointment
import re

doctor = Doctor.objects.filter(user__email='doctor1@gmail.com').first()
c = Client()
c.force_login(doctor.user)
r = c.get('/doctor/analytics/')
print('Status:', r.status_code)
content = r.content.decode('utf-8')

# Check for negative values
negatives = re.findall(r'>-([\d.]+)<', content)
if negatives:
    print(f'WARNING: Found negative values: {negatives}')
else:
    print('No negative values found')

# Check for old bad data patterns
bad_patterns = [
    '0.00</td>\\s*<td[^>]*>15.00',
    '0.00</td>\\s*<td[^>]*>485.00',
]
for pattern in bad_patterns:
    matches = re.findall(pattern, content)
    if matches:
        print(f'WARNING: Found old bad data pattern ({len(matches)} times)')

# Verify appointments data
appointments = Appointment.objects.filter(doctor=doctor)
print(f'\\nTotal appointments: {appointments.count()}')

# Check for inconsistencies
for apt in appointments:
    fee = float(apt.fee_bdt or 0)
    platform = float(apt.platform_fee_bdt or 0)
    net = float(apt.net_doctor_payout_bdt or 0)
    
    if apt.payment_status == 'paid' and fee > 0:
        expected_platform = round(fee * 0.03, 2)
        expected_net = round(fee - expected_platform - float(apt.refund_amount or 0), 2)
        if abs(platform - expected_platform) > 0.01 or abs(net - expected_net) > 0.01:
            print(f'  INCONSISTENT #{apt.pk}: fee={fee}, platform={platform} (expected {expected_platform}), net={net} (expected {expected_net})')
    elif apt.payment_status != 'paid':
        if platform != 0 or net != 0:
            print(f'  BAD #{apt.pk}: payment={apt.payment_status}, platform={platform}, net={net}')

print('\\nVerification complete')
