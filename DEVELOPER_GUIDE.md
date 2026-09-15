# CareBridge AI — Developer & Architectural Architecture Guide

Welcome to the **CareBridge AI** codebase! This guide provides a comprehensive overview of the system architecture, directory organization, domain modules, coding conventions, and instructions on how to modify existing features or add new features easily.

---

## 🏛️ High-Level System Architecture

CareBridge AI is built on **Django** using a domain-driven, modular package structure. Business logic and UI endpoints are split into distinct domain packages to prevent monolithic code bloat and ensure high maintainability.

```
Carebridge AI/
├── carebridge/            # Core project configuration & settings, root URLs, AI service layer
├── accounts/              # User Authentication, User Roles (Doctor/Patient/Admin), AI Providers
│   ├── models.py          # Custom User Profile models (Doctor, Patient, AppNotification, AIProvider)
│   ├── decorators.py      # Auth decorators (never_cache_auth, etc.)
│   ├── middleware.py      # Role-based access control & verification enforcement
│   └── views/             # Modularized Accounts Views Package
│       ├── __init__.py    # Re-exports all views for backwards compatibility
│       ├── auth.py        # Registration, Login, Logout, Password Reset, Verification Pending
│       ├── admin_views.py # Admin Verification Dashboard & AI Provider Management
│       ├── analytics.py   # System-wide Admin Analytics & Doctor Revenue Analytics
│       ├── payments.py    # Patient Payment Gateway / Proof Submission
│       ├── profile.py     # Profile Update Handler
│       └── notifications.py # Session Pings & Notification Clearing
├── doctors/               # Doctor Portal Domain
│   ├── models.py          # Appointment, DoctorSchedule, Slot Config
│   └── views/             # Modularized Doctor Views Package
│       ├── __init__.py    # Re-exports all doctor views
│       ├── dashboard.py   # Doctor Dashboard, Agenda & Urgent Actions Checklist
│       ├── appointments.py# Appointments List, Detail, Status Update, Cancellation Approval, Payment Verification
│       ├── patients.py    # Patient Directory & Clinical Detail View
│       ├── prescriptions.py # Prescription Creation, Finalization, Edit & PDF Export
│       ├── financials.py  # Doctor Financial Reports & Payout Export
│       └── profile.py     # Doctor Profile Settings & Schedule Management
├── patient/               # Patient Portal Domain
│   ├── models.py          # ChatSession, ChatMessage, HealthMetric, PatientHealthReport, MedicalHistory
│   └── views/             # Modularized Patient Views Package
│       ├── __init__.py    # Re-exports all patient views
│       ├── dashboard.py   # Patient Portal Home & Agenda
│       ├── appointments.py# Appointment Booking Flow, Cancellation Request & Payment Appeals
│       ├── doctors.py     # Doctor Search Directory & Profile View
│       ├── prescriptions.py # Prescription List, Detail View, Dose Tracking & Custom Timing
│       ├── chat.py        # Gemini AI Assistant Interface & API Endpoints
│       ├── reports.py     # Vitals History, Health Reports & PDF Summary Generation
│       └── analytics.py   # Patient Health & Financial Analytics
├── prescriptions/         # Prescriptions Domain
│   ├── models.py          # Prescription, PrescriptionItem, Medicine, ReminderSchedule, FollowUp
│   └── views.py           # Prescription PDF generator & internal utilities
└── templates/             # HTML Templates grouped by feature app (accounts, doctors, patient, etc.)
```

---

## 🚀 How to Add a New Feature (Step-by-Step)

### Step 1: Add or Update Database Models
If your new feature requires new data fields or tables:
1. Open the relevant app's `models.py` (e.g. `doctors/models.py` or `patient/models.py`).
2. Add your new Model or model fields.
3. Run migrations:
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

### Step 2: Create or Modify View Logic in the Modular View Packages
Choose the domain file under the relevant app's `views/` directory:
- **Doctor Portal**: `doctors/views/`
  - Add appointment logic to `appointments.py`
  - Add prescription logic to `prescriptions.py`
  - Add dashboard widgets to `dashboard.py`
- **Patient Portal**: `patient/views/`
  - Add booking/appointment logic to `appointments.py`
  - Add AI chat features to `chat.py`
  - Add health trackers to `reports.py` or `prescriptions.py`
- **User Accounts / Admin**: `accounts/views/`
  - Add admin tools to `admin_views.py`
  - Add auth logic to `auth.py`

*Note: Whenever you add a new view function, re-export it in `views/__init__.py` so it can be imported anywhere without breaking.*

### Step 3: Map URL Route in `urls.py`
Add your new endpoint in `urls.py` (e.g., `doctors/urls.py` or `patient/urls.py`):
```python
path("doctors/appointments/<int:appointment_id>/my-feature/", views.my_feature_view, name="my_feature"),
```

### Step 4: Create/Update HTML Template
Add or modify templates under `templates/<app_name>/`. Use Tailwind CSS and FontAwesome icons matching the existing modern design system.

---

## ⚡ Useful Development Commands

- **Run Dev Server**:
  ```bash
  python manage.py runserver
  ```
- **Check System Health**:
  ```bash
  python manage.py check
  ```
- **Create Admin Superuser**:
  ```bash
  python manage.py createsuperuser
  ```

---

## 🔐 Security & Access Control Guidelines
- Use `@login_required` and `@never_cache_auth` on sensitive views.
- Ensure user role checks exist (e.g., `hasattr(request.user, "doctor_profile")`).
- Use Django's `get_object_or_404(Model, pk=id, user=request.user)` to enforce strict data ownership.
