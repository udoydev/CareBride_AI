# 🏥 CareBridge AI — Smart Telemedicine & AI Health Assistant Platform

CareBridge AI is a state-of-the-art, full-stack clinical telemedicine, prescription translation, patient dose tracking, and doctor financial analytics platform built with **Django 4.2+**, **Google Gemini AI**, **ReportLab PDF**, and **Tailwind CSS**.

---

## 🌟 Key Platform Features

### 👤 1. Patient Portal
- **Interactive 2-Column Dashboard**: Displays patient ID (`#PAT-ID`), greeting, personal vitals, active dosage checklist, upcoming follow-ups, and an interactive schedule calendar.
- **Daily Dose Tracker & Reminders**: Real-time checklist for daily medication doses with time slots (*Morning, Afternoon, Evening, Night*), reminder alerts, and adherence calculation.
- **Follow-up Booking & Deadline Engine**: Calculates exact follow-up dates and booking deadlines to ensure patients book before deadlines.
- **AI Health Assistant & Voice Support**: Dual Bangla and English voice chatbot for prescription interpretation, medication advice, and symptom analysis powered by Google Gemini AI.
- **ReportLab Medical PDF Exporters**:
  - `Overall Medical Summary Report` (Vitals, Diagnoses, Medical History, Prescriptions).
  - `Dose Track Report` (Medication schedules, adherence percentage, taken/skipped logs).
  - `Payment History Report` (Receipts, fees paid, wallet refund transactions).

### 👨‍⚕️ 2. Doctor Portal
- **Professional 2-Column Dashboard**: Features Doctor ID (`#DOC-ID`), BMDC Verification badge, consultation fee, weekly schedule management, and pending appointment requests.
- **Digital Prescription Builder**: Complete clinical workflow supporting visit vitals (*Heart Rate, BP, SpO2, Temp, Weight, Height*), chief complaints, diagnosis, test requirements, medications, advice rules, and follow-up scheduling.
- **Virtual Digital Signature Box**: Every generated prescription PDF includes an official medical header, timestamped verification hash (`#CARE-RX-[id]-[timestamp]`), doctor credentials, and an embedded **Virtual Digital Signature Card**:
  ```
  +---------------------------------------------------------+
  | Dr. [Doctor Full Name]                                  |
  | Virtual Digital Signature                               |
  | [ ✓ DIGITALLY SIGNED & VERIFIED ]                       |
  | BMDC Reg No: #A-XXXXX                                   |
  | Signed Date: 03 Sep 2026, 02:30 PM                      |
  +---------------------------------------------------------+
  ```
- **Chamber Schedule & Availability Manager**: Configure weekly time slots, consultation fees, and appointment durations.
- **Patient Adherence Directory**: View past patient records, adherence percentages (`0-100%`), and issued prescription histories.

### 🛡️ 3. Admin & Doctor Tracking Analytics
- **Role-Based Access Control (RBAC)**: Custom `RoleBasedAccessMiddleware` ensuring strict path enforcement across Patient (`/patient/`), Doctor (`/doctors/`), and Admin (`/reports/admin/`) portals.
- **Doctor Performance & Financial Analytics**: Real-time breakdown of:
  - **Gross Revenue (BDT)**: Total consultation fees collected.
  - **Platform Commission (15%)**: Automated platform site fee calculations.
  - **Net Doctor Payout (BDT)**: Net earnings allocated to doctors.
  - **Total Refund (BDT)**: Audited patient wallet refunds.
- **Doctor Search & Dropdown Control**: Quick search input (`#docSearchInput`) integrated alongside the doctor selection dropdown.
- **Doctor Account Management & Safe Deletion**: Admin capability to track performance, export statements, or delete doctor profiles safely with confirmation modal protection.

---

## 💰 Financial & Refund Accounting Logics

CareBridge AI enforces strict financial accounting equations across all appointment transactions:

```
Gross Consultation Fee (BDT) = Patient Refund + Platform Fee + Net Doctor Payout
```

1. **Patient-Initiated Cancellation (35% Partial Refund)**:
   - `Patient Refund` = `Fee * 0.35`
   - `Platform Fee` = `Fee * 0.15`
   - `Net Doctor Payout` = `Fee - Platform Fee - Patient Refund`
2. **Doctor-Initiated Cancellation (100% Full Refund)**:
   - `Patient Refund` = `Fee`
   - `Platform Fee` = `0.00`
   - `Net Doctor Payout` = `0.00`

---

## 🛠️ Technology Stack

| Component | Technology / Library |
| :--- | :--- |
| **Backend Framework** | Python 3.13, Django 4.2+ |
| **Database** | SQLite (Default) / PostgreSQL Ready |
| **PDF Generation Engine** | ReportLab (with TTF Unicode Font Registration) |
| **AI Integration** | Google Gemini AI (`google-generativeai`) |
| **Frontend Styling** | Tailwind CSS, Custom CSS Design System |
| **Icons & Media** | FontAwesome 6 Pro, Custom Clinical Avatars |
| **Middleware** | RoleBasedAccessMiddleware, NoCacheAuthenticationMiddleware |

---

## 🚀 Installation & Local Development Setup

### 1. Prerequisites
- Python 3.10+
- Git

### 2. Clone Repository & Setup Virtual Environment
```bash
git clone https://github.com/udoydev/CareBride_AI.git
cd "Carebridge AI"

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables (`.env`)
Create a `.env` file in the project root:
```env
DEBUG=True
SECRET_KEY=your-django-secret-key
GEMINI_API_KEY=your-google-gemini-api-key
```

### 5. Run Database Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

### 6. Create Superuser (Admin)
```bash
python manage.py createsuperuser
```

### 7. Start Development Server
```bash
python manage.py runserver
```
Visit `http://127.0.0.1:8000/` in your browser.

---

## 🗺️ Key URL Sitemap

### 🔑 Authentication & Accounts
- `/login/` — Role-based Login Page (Patient, Doctor, Admin)
- `/register/` — Interactive 3-Step Multi-Section Registration Wizard
- `/password-reset/` — Password Reset Request
- `/logout/` — Secure Session Logout

### 🩺 Patient Portal
- `/patient/dashboard/` — Patient Daily Overview
- `/patient/doses/today/` — Daily Dose Checklist
- `/patient/doctors/` — Verified Doctor Directory
- `/patient/doctors/<id>/book/` — Appointment Booking & Slot Picker
- `/patient/chat-ui/` — AI Assistant Chatbot
- `/patient/reports/` — Patient Medical Reports Hub
- `/patient/overall-report/` — Overall Medical Summary PDF Download

### 👨‍⚕️ Doctor Portal
- `/doctors/dashboard/` — Doctor Command Center
- `/doctors/appointments/` — Appointments Management
- `/doctors/patients/<id>/prescribe/` — Digital Prescription Builder
- `/doctors/prescriptions/<id>/download/` — Prescription PDF with Virtual Signature
- `/doctors/schedule/` — Time Slot & Fee Configuration
- `/doctors/financial-report/export/` — Financial Statement PDF Export

### 🛡️ Admin & System Reports
- `/admin/` — Django Admin Panel
- `/reports/admin/doctors/tracking/` — Doctor Performance & Financial Analytics Dashboard
- `/reports/admin/doctors/<id>/delete/` — Safe Doctor Account Deletion

---

## 📄 License & Credits
Developed as part of the **CareBridge AI** Telemedicine Network. All rights reserved.
