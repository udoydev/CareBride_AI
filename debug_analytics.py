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
content = r.content.decode('utf-8')

# Find the exact matches with context
matches = list(re.finditer(r'0\.00</td>\s*<td[^>]*>15\.00', content))
print(f'Found {len(matches)} matches for pattern 0.00 -> 15.00')

for i, match in enumerate(matches[:5]):
    start = max(0, match.start() - 200)
    end = min(len(content), match.end() + 200)
    context = content[start:end]
    print(f'\n--- Match {i+1} ---')
    print(context)
    print('---')

# Also check for 0.00 -> 485.00
matches2 = list(re.finditer(r'0\.00</td>\s*<td[^>]*>485\.00', content))
print(f'\nFound {len(matches2)} matches for pattern 0.00 -> 485.00')

for i, match in enumerate(matches2[:3]):
    start = max(0, match.start() - 200)
    end = min(len(content), match.end() + 200)
    context = content[start:end]
    print(f'\n--- Match {i+1} ---')
    print(context)
    print('---')
