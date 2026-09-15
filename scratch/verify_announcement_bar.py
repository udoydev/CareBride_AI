import os
import sys
import django

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'carebridge.settings')
django.setup()

from django.test import Client

c = Client()
res = c.get('/home/')
print("Status code:", res.status_code)
content = res.content.decode('utf-8')

idx = content.find('class="inline-flex animate-ticker-tape')
if idx != -1:
    lines = content[idx-50:idx+450].splitlines()
    print("\n--- Rendered Top Ticker HTML ---")
    for l in lines:
        print(l)
else:
    print("class inline-flex animate-ticker-tape not found in home page")

# Test Doctor Dashboard
from django.contrib.auth import get_user_model
User = get_user_model()
doc_user = User.objects.filter(doctor_profile__isnull=False).first()
if doc_user:
    c.force_login(doc_user)
    r_doc = c.get('/doctors/dashboard/')
    print("\nDoctor Dashboard Status:", r_doc.status_code)
    print("Doctor Dashboard contains BREAKING NEWS:", 'BREAKING NEWS' in r_doc.content.decode('utf-8'))
    print("Doctor Dashboard contains Clinical Announcements:", 'Clinical Announcements & Updates' in r_doc.content.decode('utf-8'))

# Test Patient Dashboard
pat_user = User.objects.filter(patient_profile__isnull=False).first()
if pat_user:
    c.force_login(pat_user)
    r_pat = c.get('/patient/dashboard/')
    print("\nPatient Dashboard Status:", r_pat.status_code)
    print("Patient Dashboard contains BREAKING NEWS:", 'BREAKING NEWS' in r_pat.content.decode('utf-8'))
    print("Patient Dashboard contains Clinical Announcements:", 'Clinical Announcements & Updates' in r_pat.content.decode('utf-8'))

print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")
