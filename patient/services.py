import json
import os
from urllib import error, request

from django.utils import timezone

from accounts.models import Doctor
from prescriptions.models import FollowUp, Prescription, ReminderSchedule


TIMING_LABELS = {
    "before_meal": {"bn": "খাবারের আগে", "en": "before meals"},
    "after_meal": {"bn": "খাবারের পরে", "en": "after meals"},
    "with_meal": {"bn": "খাবারের সাথে", "en": "with meals"},
    "anytime": {"bn": "যেকোনো সময়", "en": "any time"},
}


def _resolve_provider():
    provider = (os.getenv("AI_PROVIDER") or "").strip().lower()
    gemini_key = os.getenv("GEMINI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")

    if provider == "gemini" or (not provider and gemini_key):
        return {
            "name": "gemini",
            "api_key": gemini_key,
            "url": f"https://generativelanguage.googleapis.com/v1beta/models/{os.getenv('GEMINI_MODEL') or 'gemini-1.5-flash'}:generateContent?key={gemini_key}",
            "model": os.getenv("GEMINI_MODEL") or "gemini-1.5-flash",
        }
    if provider == "groq" or (not provider and groq_key):
        return {
            "name": "groq",
            "api_key": groq_key,
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "model": os.getenv("GROQ_MODEL") or "llama3-8b-8192",
        }
    if provider == "openai" or (not provider and openai_key):
        return {
            "name": "openai",
            "api_key": openai_key,
            "url": "https://api.openai.com/v1/chat/completions",
            "model": os.getenv("OPENAI_MODEL") or "gpt-4o-mini",
        }
    if provider == "deepseek" or (not provider and deepseek_key):
        return {
            "name": "deepseek",
            "api_key": deepseek_key,
            "url": "https://api.deepseek.com/chat/completions",
            "model": os.getenv("DEEPSEEK_MODEL") or "deepseek-chat",
        }
    return None


def _request_chat_completion_messages(messages, provider=None, model=None):
    config = provider or _resolve_provider()
    if not config or not config.get("api_key"):
        return None

    if config["name"] == "gemini":
        prompt_parts = []
        for msg in messages:
            role_prefix = "User: " if msg["role"] == "user" else ("System: " if msg["role"] == "system" else "Assistant: ")
            prompt_parts.append(f"{role_prefix}{msg['content']}")
        full_prompt = "\n\n".join(prompt_parts)
        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1024},
        }
        try:
            req = request.Request(
                config["url"],
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
            candidates = data.get("candidates") or []
            if candidates:
                parts = candidates[0].get("content", {}).get("parts") or []
                if parts and parts[0].get("text"):
                    return parts[0]["text"].strip()
        except Exception:
            return None
        return None

    model = model or config["model"]
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 1024,
    }

    try:
        req = request.Request(
            config["url"],
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))

        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            text = (message.get("content") or "").strip()
            if text:
                return text
    except (error.URLError, error.HTTPError, KeyError, IndexError, ValueError, TimeoutError):
        return None

    return None


def build_patient_context(patient):
    """Collect everything the assistant should know about this patient."""
    if not patient:
        return "No patient profile available."

    user = patient.user
    today = timezone.localdate()
    lines = [
        "=== PATIENT PROFILE ===",
        f"Name: {user.get_full_name() or user.username}",
        f"Preferred language: {patient.get_preferred_language_display() if hasattr(patient, 'get_preferred_language_display') else patient.preferred_language}",
        f"Gender: {patient.gender or 'Not specified'}",
        f"Date of birth: {patient.date_of_birth or 'Not specified'}",
        "",
        "=== CAREBRIDGE SITE (what the patient can do) ===",
        "- Dashboard: see today's doses and next follow-up",
        "- Today's Doses: mark medicines as taken or skipped",
        "- Health Record: full prescription timeline",
        "- Follow-ups: upcoming, completed, and missed visits",
        "- Find Doctors: search verified doctors, view clinic location, book visit",
        "- AI Assistant: ask about prescriptions, medicines, doses, doctors (this chat)",
        "- Profile: update name, avatar, preferred language (Bangla/English)",
        "",
    ]

    prescriptions = (
        Prescription.objects.filter(patient=patient)
        .select_related("doctor__user")
        .prefetch_related("items__medicine", "follow_up")
        .order_by("-issued_at")
    )

    if prescriptions.exists():
        lines.append("=== PRESCRIPTIONS (FULL MEDICAL HISTORY) ===")
        for rx in prescriptions:
            doctor = rx.doctor
            lines.append(
                f"Prescription #{rx.pk} | Dr. {doctor.user.get_full_name()} ({doctor.specialty or 'General'}) "
                f"| Clinic: {doctor.clinic_name or 'N/A'} | Location: {doctor.location_text or 'N/A'} "
                f"| Status: {rx.get_status_display()} | Issued: {rx.issued_at:%Y-%m-%d}"
            )
            if rx.chief_complaints:
                lines.append(f"  Chief Complaints: {rx.chief_complaints}")
            if rx.diagnosis:
                lines.append(f"  Diagnosis/Condition: {rx.diagnosis}")
            if rx.tests_investigations:
                lines.append(f"  Tests/Investigations: {rx.tests_investigations}")
            if rx.advice_rules:
                lines.append(f"  Doctor Advice: {rx.advice_rules}")
            if rx.doctor_notes:
                lines.append(f"  Doctor Notes: {rx.doctor_notes}")
            lines.append("  Medicines:")
            for item in rx.items.all():
                med = item.medicine
                timing = TIMING_LABELS.get(item.timing_relation_to_meal, {}).get("en", item.timing_relation_to_meal)
                lines.append(
                    f"    - Brand: {med.brand_name} | Generic: {med.generic_name} | Form: {med.form} | Manufacturer: {med.manufacturer or 'N/A'}"
                )
                lines.append(
                    f"      Dosage: {item.dosage} | Frequency: {item.frequency} times/day | Duration: {item.duration_days} days | Timing: {timing}"
                )
                if item.special_instructions:
                    lines.append(f"      Instructions: {item.special_instructions}")
            if hasattr(rx, "follow_up") and rx.follow_up:
                fu = rx.follow_up
                lines.append(f"  Follow-up: {fu.scheduled_date} — {fu.get_status_display()}")
            lines.append("")
    else:
        lines.append("=== PRESCRIPTIONS ===\nNo prescriptions on record yet.\n")

    doses_today = ReminderSchedule.objects.filter(
        prescription_item__prescription__patient=patient,
        scheduled_date=today,
    ).select_related("prescription_item__medicine")

    lines.append("=== TODAY'S DOSES ===")
    if doses_today.exists():
        for schedule in doses_today:
            item = schedule.prescription_item
            lines.append(
                f"- {item.medicine}: {item.dosage} — status: {schedule.get_status_display()}"
            )
    else:
        lines.append("No dose reminders scheduled for today.")

    upcoming_followups = FollowUp.objects.filter(
        prescription__patient=patient,
        status="upcoming",
    ).select_related("prescription__doctor__user").order_by("scheduled_date")

    lines.append("\n=== UPCOMING FOLLOW-UPS ===")
    if upcoming_followups.exists():
        for fu in upcoming_followups:
            lines.append(
                f"- {fu.scheduled_date} with Dr. {fu.prescription.doctor.user.get_full_name()} "
                f"({fu.prescription.doctor.specialty or 'General'})"
            )
    else:
        lines.append("No upcoming follow-ups.")

    verified_doctors = Doctor.objects.filter(is_verified=True).select_related("user")[:15]
    lines.append("\n=== AVAILABLE DOCTORS ON CAREBRIDGE ===")
    for doctor in verified_doctors:
        lines.append(
            f"- Dr. {doctor.user.get_full_name()} | {doctor.specialty or 'General Physician'} "
            f"| {doctor.clinic_name or 'Clinic N/A'} | {doctor.location_text or 'Location N/A'}"
        )

    from patient.models import PatientHealthReport
    reports = PatientHealthReport.objects.filter(patient=patient).order_by("-date_performed")
    lines.append("\n=== HEALTH REPORTS / MEDICAL HISTORY ===")
    if reports.exists():
        for r in reports:
            lines.append(
                f"- [{r.date_performed}] {r.title} ({r.get_report_type_display()}) "
                f"| Doctor/Clinic: {r.doctor_or_clinic_name or 'N/A'}"
            )
            if r.result_description:
                lines.append(f"  Result: {r.result_description}")
    else:
        lines.append("No health reports uploaded yet.")

    return "\n".join(lines)


def _system_prompt(language, patient_context):
    language_name = "Bangla (বাংলা)" if language == "bn" else "English"
    return (
        "You are CareBridge AI — an expert medical assistant for patients in Bangladesh. "
        f"Always reply in {language_name} unless the patient explicitly asks for the other language.\n\n"
        "You have COMPLETE access to this patient's real medical records below. "
        "You are a MEDICINE EXPERT — when asked about any medicine, explain:\n"
        "- What it is used for (uses, conditions treated)\n"
        "- How to take it (dosage, frequency, timing, with/without food)\n"
        "- What to do if a dose is missed\n"
        "- Common side effects and what to watch for\n"
        "- Precautions and warnings\n"
        "- Storage instructions\n"
        "- Drug interactions if relevant\n"
        "Always reference the specific prescription data provided (medicine names, dosages, timing, duration, doctor advice). "
        "Do NOT give generic health advice when the user asks about their specific prescription or medicines. "
        "Be precise, empathetic, and structured. Use bullet points and bold text for clarity.\n\n"
        "Rules:\n"
        "- Be clear, empathetic, and concise. Use structured bullet points where appropriate.\n"
        "- Never diagnose or prescribe. For emergencies, urge immediate medical attention.\n"
        "- If data is missing, state it clearly and guide them on how to update it in CareBridge.\n"
        "- For medicine questions: ALWAYS use the prescription data. Explain uses, side effects, how to take, what to do if missed, precautions.\n"
        "- For prescription questions: Reference the exact prescription, doctor, diagnosis, and medicines.\n\n"
        f"PATIENT DATA:\n{patient_context}"
    )


def _history_to_messages(history, limit=30):
    messages = []
    for entry in history[-limit:]:
        role = entry.role if hasattr(entry, "role") else entry.get("role")
        content = entry.content if hasattr(entry, "content") else entry.get("text") or entry.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    return messages


MEDICAL_TOPICS = {
    "vomiting": {
        "keywords": ["বমি", "বমি ভাব", "বমি বমি", "বমি হচ্ছে", "বমিভাাব", "vomit", "vomiting", "nausea", "emesis"],
        "bn": (
            "🤢 **বমি ও বমি বমি ভাবের জন্য স্বাস্থ্য পরামর্শ:**\n\n"
            "• **খাবার ও তরল:** ভারী, তৈলাক্ত খাবার সম্পূর্ণ বন্ধ রাখুন। অল্প অল্প করে খাবার স্যালাইন (ORS), ডাবের পানি বা আদা চা পান করুন।\n"
            "• **ওষুধ (ডাক্তারের পরামর্শে):** ওনডানসেট্রন (Ondansetron / Emistat 4mg বা 8mg) বমি নিরোধক হিসেবে ডাক্তারের পরামর্শে সেবন করা হয়।\n"
            "• **সতর্কতা:** অতিরিক্ত বমির সাথে প্রস্রাব কমে যাওয়া, দুর্বলতা বা পেটে তীব্র ব্যথা হলে দ্রুত হাসপাতালের জরুরি বিভাগে যান বা গ্যাস্ট্রোএন্টারোলজিস্ট দেখান।\n\n"
            "💡 *CareBridge-এ পরিপাকতন্ত্র ও গ্যাস্ট্রো ডাক্তারের পরামর্শ নিতে 'ডাক্তার খুঁজুন' পেজে যান।*"
        ),
        "en": (
            "🤢 **Health Advice for Nausea & Vomiting:**\n\n"
            "• **Fluids & Rest:** Avoid oily/heavy foods. Sip Oral Rehydration Solution (ORS), coconut water, or ginger tea in small amounts.\n"
            "• **Medication:** Ondansetron (Emistat) is commonly prescribed under doctor supervision.\n"
            "• **Emergency Warning:** Severe abdominal pain or dehydration requires immediate medical care.\n\n"
            "💡 *Consult Gastroenterologists directly on CareBridge.*"
        )
    },
    "headache": {
        "keywords": ["মাথা ব্যথা", "মাথা ব্যাথা", "মাথা ঘোরে", "মাথা ঘোরা", "মাইগ্রেন", "মাথা ঝিমঝিম", "headache", "migraine", "dizziness"],
        "bn": (
            "🧠 **মাথা ব্যথা ও মাইগ্রেনের জন্য পরামর্শ:**\n\n"
            "• **প্রাথমিক সমাধান:** পর্যাপ্ত পানি পান করুন, অন্ধকার ও শান্ত ঘরে বিশ্রাম নিন। রোদে যাওয়ার সময় সানগ্লাস ব্যবহার করুন।\n"
            "• **ওষুধ:** প্রয়োজনে প্যারাসিটামল (Napa / Ace 500mg) সেবন করা যেতে পারে।\n"
            "• **জরুরি সতর্কতা:** হঠাৎ প্রচন্ড তীব্র মাথা ব্যথা, চোখ ঝাপসা হওয়া বা সাথে বমি থাকলে দ্রুত নিউরোলজি বা মেডিসিন ডাক্তার দেখান।\n\n"
            "💡 *CareBridge-এ মেডিসিন ও নিউরো ডাক্তারদের তালিকা দেখতে 'ডাক্তার খুঁজুন' মেনুতে ক্লিক করুন।*"
        ),
        "en": (
            "🧠 **Advice for Headache & Migraine:**\n\n"
            "• **First Steps:** Rest in a quiet, dark room and stay hydrated.\n"
            "• **Medication:** Paracetamol (Napa/Ace) for mild to moderate pain.\n"
            "• **Doctor Consultation:** Seek urgent help if accompanied by blurred vision or vomiting."
        )
    },
    "cough_cold": {
        "keywords": ["কাশি", "সর্দি", "গলা ব্যথা", "ঠান্ডা", "কফ", "হাঁচি", "cough", "cold", "sore throat", "flu"],
        "bn": (
            "🤧 **সর্দি, কাশি ও গলা ব্যথায় করণীয়:**\n\n"
            "• **ঘরোয়া যত্ন:** হালকা গরম পানিতে এক চিমটি লবণ দিয়ে গার্গল (কুলি) করুন। তুলসী পাতা, মধু ও আদা চা পান করুন।\n"
            "• **বাষ্প নেওয়া:** দিনে ২-৩ বার গরম পানির ভাপ (Steam Inhalation) নিলে নাক পরিষ্কার থাকে।\n"
            "• **ওষুধ:** অ্যান্টিহিস্টামিন (Fexo / Fexofenadine 120mg বা Histacin) সর্দির জন্য এবং প্যারাসিটামল ব্যথার জন্য ব্যবহৃত হয়।\n"
            "• **সতর্কতা:** ৭ দিনের বেশি কাশি স্থায়ী হলে বা কফের সাথে রক্ত এলে বক্ষব্যাধি (Pulmonologist) ডাক্তার দেখান।\n\n"
            "💡 *CareBridge-এর ইএনটি (ENT) ও মেডিসিন ডাক্তার দেখতে 'ডাক্তার খুঁজুন' পেজে যান।*"
        ),
        "en": (
            "🤧 **Care Advice for Cold & Cough:**\n\n"
            "• **Home Remedies:** Saltwater gargle, warm ginger honey tea, and steam inhalation.\n"
            "• **Medication:** Antihistamines like Fexofenadine (Fexo) as prescribed.\n"
            "• **Doctor Visit:** If cough exceeds 7 days, consult a Chest Specialist."
        )
    },
    "gastric": {
        "keywords": ["গ্যাস্ট্রিক", "এসিডিটি", "বুক জ্বালা", "গ্যাস", "পাকস্থলী", "gastric", "acidity", "seclo", "maxpro", "sergel", "heartburn"],
        "bn": (
            "🩺 **গ্যাস্ট্রিক ও বুক জ্বালাপোড়ার জন্য স্বাস্থ্য পরামর্শ:**\n\n"
            "• **জীবনযাত্রা ও খাদ্যভ্যাস:** তৈলাক্ত, ভাজাভুজি ও অতিরিক্ত মসলাযুক্ত খাবার এড়িয়ে চলুন। সময়মতো খাবার গ্রহণ করুন।\n"
            "• **পানি পান:** প্রতিদিন পর্যাপ্ত (২.৫ - ৩ লিটার) বিশুদ্ধ পানি পান করুন।\n"
            "• **সাধারণ ওষুধ (ডাক্তারের পরামর্শে):** ওমিপ্রাজল (Seclo/Sergel) বা ইসোমিপ্রাজল (Maxpro) সকালে খালি পেটে সেবন করা হয়।\n"
            "• **বিশেষজ্ঞ ডাক্তার:** তীব্র পেট ব্যথা হলে পরিপাকতন্ত্র ও গ্যাস্ট্রোএন্টারোলজি (Gastroenterologist) বিশেষজ্ঞের পরামর্শ নিন।\n\n"
            "💡 *CareBridge-এ গ্যাস্ট্রোএন্টারোলজিস্ট ডাক্তারের অ্যাপয়েন্টমেন্ট বুক করতে 'ডাক্তার খুঁজুন' পেজে যান।*"
        ),
        "en": (
            "🩺 **Health Advice for Gastritis & Acidity:**\n\n"
            "• **Diet & Lifestyle:** Avoid oily, spicy, and deep-fried foods. Eat meals at regular intervals.\n"
            "• **Hydration:** Drink at least 2.5–3 liters of clean water daily.\n"
            "• **Common OTC Options:** Proton pump inhibitors like Omeprazole (Seclo) or Esomeprazole (Maxpro) are typically taken before breakfast under medical advice.\n"
            "• **Consultation:** Consult a Gastroenterologist if pain persists or escalates.\n\n"
            "💡 *Search and book Gastroenterologists via our 'Find Doctors' section.*"
        )
    },
    "fever": {
        "keywords": ["জ্বর", "গা গরম", "তাপমাত্রা", "ডেঙ্গু", "fever", "feverish", "napa", "ace", "paracetamol", "dengue"],
        "bn": (
            "🌡️ **জ্বর ও শরীর ব্যথায় করণীয়:**\n\n"
            "• **প্রাথমিক চিকিৎসা:** প্যারাসিটামল (Napa/Ace 500mg) ডাক্তারের পরামর্শ অনুযায়ী সেবন করুন। শরীর হালকা গরম পানি দিয়ে মুছে দিন।\n"
            "• **তরল খাবার:** ডাবের পানি, খাবার স্যালাইন, লেবুর শরবত ও সুপ বেশি করে পান করুন। পর্যাপ্ত বিশ্রাম নিন।\n"
            "• **ডেঙ্গু সতর্কতা:** ৩ দিনের বেশি তীব্র জ্বর, গায়ে লাল র‍্যাশ বা রক্তে প্লাটিলেট কমলে দ্রুত CBC ও Dengue NS1 পরীক্ষা করান।\n"
            "• **জরুরি সতর্কতা:** ১০৩°F এর বেশি জ্বর হলে মেডিসিন (General Physician) বিশেষজ্ঞের পরামর্শ নিন।\n\n"
            "💡 *CareBridge-এর মেডিসিন বিশেষজ্ঞদের দেখতে 'ডাক্তার খুঁজুন' পেজে যান।*"
        ),
        "en": (
            "🌡️ **Fever & Dengue Care Advice:**\n\n"
            "• **First Aid:** Paracetamol (Napa/Ace 500mg) as advised by a doctor. Sponge body with lukewarm water.\n"
            "• **Fluids:** Drink coconut water, ORS saline, and clear soups. Rest adequately.\n"
            "• **Dengue Warning:** If high fever persists >3 days or rash occurs, test CBC & Dengue NS1 promptly.\n"
            "• **Doctor Visit:** Consult a General Physician if fever exceeds 102°F or does not abate.\n\n"
            "💡 *Book a General Physician directly on CareBridge.*"
        )
    },
    "diabetes": {
        "keywords": ["ডায়াবেটিস", "ডায়বেটিস", "রক্তে চিনি", "সুগার", "diabetes", "sugar", "metformin", "insulin"],
        "bn": (
            "🩸 **ডায়াবেটিস নিয়ন্ত্রণ ও যত্ন:**\n\n"
            "• **খাদ্যনিয়ন্ত্রণ:** চিনি, মিষ্টি, কোমল পানীয়, অতিরিক্ত ভাত ও শর্করা এড়িয়ে চলুন। শাকসবজি ও ফাইবারযুক্ত খাবার বেশি খান।\n"
            "• **শরীরচর্চা:** প্রতিদিন অন্তত ৩০ মিনিট দ্রুত হাঁটার অভ্যাস করুন।\n"
            "• **নিয়মিত পরীক্ষা:** মাসে অন্তত একবার খালি পেটে (Fasting) ও খাওয়ার ২ ঘণ্টা পর (2ABF) ব্লাড সুগার পরীক্ষা করুন।\n"
            "• **বিশেষজ্ঞ:** এন্ডোক্রাইনোলজি (Endocrinologist) বা মেডিসিন বিশেষজ্ঞের পরামর্শ অনুযায়ী ওষুধ সেবন করুন।\n\n"
            "💡 *আপনার ডায়াবেটিসের প্রেসক্রিপশন ও রিমাইন্ডার সেভ রাখতে CareBridge ব্যবহার করুন।*"
        ),
        "en": (
            "🩸 **Diabetes Management & Care:**\n\n"
            "• **Dietary Control:** Limit refined sugars, sweets, soft drinks, and excess carbs. Focus on high-fiber vegetables.\n"
            "• **Physical Activity:** Walk briskly for at least 30 minutes daily.\n"
            "• **Monitoring:** Check Fasting and 2-Hour Postprandial blood sugar regularly.\n"
            "• **Specialist:** Consult an Endocrinologist or Diabetologist for dosage guidance.\n\n"
            "💡 *Store your diabetes prescriptions and track dose schedules on CareBridge.*"
        )
    },
    "pressure": {
        "keywords": ["প্রেসার", "উচ্চ রক্তচাপ", "হাই প্রেসার", "বিপি", "pressure", "hypertension", "bp", "cardio", "amlodipine"],
        "bn": (
            "❤️ **উচ্চ রক্তচাপ (High BP) ও হৃদরোগ পরামর্শ:**\n\n"
            "• **খাবার সংযম:** কাঁচা লবণ সম্পূর্ণরূপে ত্যাগ করুন। চর্বিযুক্ত ও প্রসেসড খাবার এড়িয়ে চলুন।\n"
            "• **মানসিক চাপ:** মানসিক চাপ মুক্ত থাকুন এবং প্রতিদিন ৭-৮ ঘণ্টা পর্যাপ্ত ঘুমান।\n"
            "• **নিয়মিত চেকআপ:** সপ্তাহে অন্তত ১-২ বার রক্তচাপ মেপে ট্র্যাকিং রাখুন।\n"
            "• **জরুরি চিহ্ন:** হঠাৎ তীব্র বুকে ব্যথা, শ্বাসকষ্ট বা বুক ধড়ফড় করলে অবিলম্বে কার্ডিওলোজিস্ট (Cardiologist) ডাক্তারের শরণাপন্ন হন।\n\n"
            "💡 *CareBridge-এর হৃদরোগ বিশেষজ্ঞ ডাক্তারদের দেখতে 'ডাক্তার খুঁজুন' মেনু ক্লিক করুন।*"
        ),
        "en": (
            "❤️ **Hypertension & Heart Health Advice:**\n\n"
            "• **Dietary Restrictions:** Eliminate raw table salt and restrict fatty, fried, processed foods.\n"
            "• **Lifestyle:** Manage stress and get 7–8 hours of restful sleep daily.\n"
            "• **Tracking:** Measure BP 1-2 times weekly and log changes.\n"
            "• **Red Flags:** Chest pain, shortness of breath, or numbness requires an immediate Cardiologist visit.\n\n"
            "💡 *Find verified Cardiologists on our Find Doctors page.*"
        )
    },
    "emergency": {
        "keywords": ["জরুরি", "হার্ট অ্যাটাক", "অচেতন", "শ্বাসকষ্ট", "emergency", "hospital", "999", "icu"],
        "bn": (
            "🚨 **জরুরি চিকিৎসা সতর্কতা!**\n\n"
            "আপনার বা আপনার পরিচিত কারও যদি তীব্র বুকে ব্যথা, মারাত্মক শ্বাসকষ্ট, হঠাৎ অজ্ঞান হয়ে যাওয়া বা অতিরিক্ত রক্তপাত হয়, **বিলম্ব না করে নিকটস্থ হাসপাতালের ইমার্জেন্সি বিভাগে যান অথবা জরুরি সেবা ৯৯৯-এ কল করুন।**\n\n"
            "জরুরি পরিস্থিতিতে অনলাইন বা এআই পরামর্শের জন্য অপেক্ষা করবেন না।"
        ),
        "en": (
            "🚨 **EMERGENCY MEDICAL WARNING!**\n\n"
            "If you or anyone nearby experiences severe chest pain, extreme breathlessness, sudden facial/arm numbness, or heavy bleeding, **immediately proceed to the nearest emergency hospital or call emergency services (999).**\n\n"
            "Do not delay for online consultation during critical symptoms."
        )
    }
}



def _local_patient_reply(question, language, patient):
    """Smart fallback using real patient data + medical knowledge engine."""
    context = build_patient_context(patient)
    q = question.lower().strip()
    is_bn = language == "bn"

    # Check medical topics
    for topic_id, topic in MEDICAL_TOPICS.items():
        if any(w in q for w in topic["keywords"]):
            return topic["bn"] if is_bn else topic["en"]

    prescriptions = list(
        Prescription.objects.filter(patient=patient)
        .select_related("doctor__user")
        .prefetch_related("items__medicine", "follow_up")
        .order_by("-issued_at")[:3]
    ) if patient else []

    today = timezone.localdate()
    doses = ReminderSchedule.objects.filter(
        prescription_item__prescription__patient=patient,
        scheduled_date=today,
    ).select_related("prescription_item__medicine") if patient else []

    dose_keywords = ["আজ", "ডোজ", "ওষুধ", "ঔষধ", "খাওয়া", "খাবো", "dose", "today", "medicine", "pill", "tablet", "oshud", "osud", "aaj"]
    if any(w in q for w in dose_keywords):
        if doses and doses.exists():
            items = [f"• **{s.prescription_item.medicine}**: {s.prescription_item.dosage} ({s.get_status_display()})" for s in doses]
            if is_bn:
                return "📋 **আজকের ওষুধের তালিকা:**\n\n" + "\n".join(items) + "\n\n💡 *'আজকের ওষুধ' পেজে গিয়ে ওষুধ নিয়ে থাকলে mark করুন।*"
            return "📋 **Today's Dose Schedule:**\n\n" + "\n".join(items) + "\n\n💡 *Mark doses as taken on the 'Today's Doses' page.*"
        else:
            if is_bn:
                return "✅ **আজকের জন্য কোনো ওষুধের রিমাইন্ডার বাকি নেই।**\n\nআপনি প্রেসক্রিপশন বা যেকোনো শারীরিক সমস্যা নিয়ে প্রশ্ন করতে পারেন।"
            return "✅ **No medicine doses scheduled for today.**\n\nYou can ask me about symptoms, medicines, or doctors."

    followup_keywords = ["ফলো", "ফলোআপ", "সাক্ষাৎ", "ভিজিট", "অ্যাপয়েন্টমেন্ট", "follow", "followup", "appointment", "visit", "date", "apointment"]
    if any(w in q for w in followup_keywords):
        fus = FollowUp.objects.filter(prescription__patient=patient, status="upcoming").order_by("scheduled_date") if patient else []
        if fus and fus.exists():
            lines = [f"• **{fu.scheduled_date}** — Dr. {fu.prescription.doctor.user.get_full_name()}" for fu in fus]
            if is_bn:
                return "📅 **আপনার আসন্ন ফলো-আপের সময়সূচী:**\n\n" + "\n".join(lines) + "\n\n💡 *'ফলো-আপ' পেজে বিস্তারিত জানতে পারবেন।*"
            return "📅 **Your Upcoming Follow-up Visits:**\n\n" + "\n".join(lines) + "\n\n💡 *Check the 'Follow-ups' page for full details.*"
        else:
            if is_bn:
                return "ℹ️ **বর্তমানে আপনার কোনো নির্ধারিত ফলো-আপ নেই।**\n\nনতুন ডাক্তারের সাথে দেখা করতে 'ডাক্তার খুঁজুন' পেজে যান।"
            return "ℹ️ **No upcoming follow-up visits scheduled right now.**\n\nFind verified doctors on the 'Find Doctors' page."

    rx_keywords = ["প্রেসক্রিপশন", "প্রেসকৃপশন", "প্রেসক্রিপসন", "রেকর্ড", "ইতিহাস", "prescription", "rx", "record", "history", "script"]
    if any(w in q for w in rx_keywords):
        if prescriptions:
            rx = prescriptions[0]
            items = [f"• **{i.medicine}**: {i.dosage}, দিনে {i.frequency} বার ({i.duration_days} দিন)" for i in rx.items.all()]
            if is_bn:
                return (
                    f"💊 **সর্বশেষ প্রেসক্রিপশন (#{rx.pk})** — ডা. {rx.doctor.user.get_full_name()}:\n\n"
                    + "\n".join(items)
                    + "\n\n💡 *বিস্তারিত দেখতে 'স্বাস্থ্য রেকর্ড' পৃষ্ঠায় যান।*"
                )
            items_en = [f"• **{i.medicine}**: {i.dosage}, {i.frequency}x/day ({i.duration_days} days)" for i in rx.items.all()]
            return (
                f"💊 **Latest Prescription (#{rx.pk})** — Dr. {rx.doctor.user.get_full_name()}:\n\n"
                + "\n".join(items_en)
                + "\n\n💡 *View full prescription history on the 'Health Record' page.*"
            )
        else:
            if is_bn:
                return "ℹ️ **আপনার অ্যাকাউন্টে এখনও কোনো প্রেসক্রিপশন যোগ করা হয়নি।**"
            return "ℹ️ **No prescription records found on your account yet.**"

    doc_keywords = ["ডাক্তার", "ডাক্তারগণ", "ডাক্তারদের", "চিকিৎসক", "doctor", "doctors", "daktar", "physician", "specialist"]
    if any(w in q for w in doc_keywords):
        doctors = Doctor.objects.filter(is_verified=True).select_related("user")[:5]
        if doctors.exists():
            lines = [f"• **Dr. {d.user.get_full_name()}** — {d.specialty or 'General Physician'} ({d.clinic_name or 'CareBridge Clinic'})" for d in doctors]
            if is_bn:
                return "👨‍⚕️ **CareBridge-এর উপলব্ধ ডাক্তারবৃন্দ:**\n\n" + "\n".join(lines) + "\n\n💡 *'ডাক্তার খুঁজুন' পৃষ্ঠায় বুকিং দিন।*"
            return "👨‍⚕️ **Available Doctors on CareBridge:**\n\n" + "\n".join(lines) + "\n\n💡 *Book appointments via the 'Find Doctors' page.*"
        else:
            if is_bn:
                return "ℹ️ **বর্তমানে কোনো তালিকাভুক্ত ডাক্তার পাওয়া যায়নি।**"
            return "ℹ️ **No verified doctors available at the moment.**"

    if is_bn:
        return (
            f"📋 **আপনার প্রশ্নের উত্তর:**\n\n"
            f"প্রশ্ন: *\"{q}\"*\n\n"
            "• **স্বাস্থ্য পরামর্শ:** নিয়মিত সময়মতো ওষুধ সেবন করুন, পর্যাপ্ত পানি পান করুন এবং পুষ্টিকর খাবার গ্রহণ করুন।\n"
            "• **CareBridge সেবা:** আপনার প্রেসক্রিপশন দেখতে, আজকের ডোজ ট্র্যাক করতে বা অভিজ্ঞ ডাক্তারদের সিরিয়াল বুক করতে সংশ্লিষ্ট পেজে যান।\n\n"
            "💡 *গুরুতর শারীরিক অসুস্থতায় বিলম্ব না করে নিকটস্থ ডাক্তারের পরামর্শ নিন।*"
        )
    return (
        f"📋 **Health Query Answer:**\n\n"
        f"Question: *\"{q}\"*\n\n"
        "• **General Guidance:** Take all medications on time, stay well hydrated, and maintain adequate rest.\n"
        "• **CareBridge Services:** You can view your prescriptions, track dose reminders, or book doctor appointments.\n\n"
        "💡 *For severe or urgent symptoms, consult a specialist immediately.*"
    )


def generate_patient_reply(question, language="bn", patient=None, history=None, image_file=None, prescription_id=None):
    from carebridge.ai_services import GeminiAIService

    language = language if language in {"bn", "en"} else "bn"

    # Guest user: try static Q&A first, then AI for text or image
    if not patient:
        guest_ans = guest_reply(question, language)
        if guest_ans:
            return guest_ans

        try:
            ai_res = GeminiAIService.chat_with_patient_vision(
                user_message=question or "দয়া করে এই আপলোড করা নথি/প্রেসক্রিপশনের ছবি বিশ্লেষণ করে পরামর্শ দিন।",
                image_file=image_file,
                conversation_history=[],
                preferred_language=language,
            )
            if ai_res.get("reply_text"):
                return ai_res["reply_text"]
        except Exception:
            pass

        return (
            "👋 CareBridge AI-এ স্বাগতম! নিচের বিষয়গুলি সম্পর্কে জানতে পারেন:\n"
            "• CareBridge AI কি ও কিভাবে কাজ করে?\n"
            "• Registration, verification, prescription system\n"
            "• AI chatbot, voice chat, dose reminders\n"
            "• Doctor booking ও health record management\n\n"
            "আপনার কোনো প্রশ্ন থাকলে জিজ্ঞাসা করুন!"
            if language == "bn" else
            "👋 Welcome to CareBridge AI! You can ask about:\n"
            "• What is CareBridge AI and how it works?\n"
            "• Registration, verification, prescription system\n"
            "• AI chatbot, voice chat, dose reminders\n"
            "• Doctor booking and health record management\n\n"
            "Feel free to ask any question!"
        )

    # Logged-in patient: full AI with patient data
    patient_context = build_patient_context(patient)

    # Build prescription-specific context if prescription_id is provided
    prescription_context = ""
    if prescription_id:
        try:
            from prescriptions.models import Prescription
            rx = Prescription.objects.filter(pk=prescription_id, patient=patient).select_related(
                "doctor__user"
            ).prefetch_related("items__medicine", "follow_up").first()
            if rx:
                rx_lines = [
                    f"=== PRESCRIPTION #{rx.pk} DETAILED CONTEXT ===",
                    f"Doctor: {rx.doctor.user.get_full_name()} ({rx.doctor.specialty or 'General'})",
                    f"Clinic: {rx.doctor.clinic_name or 'N/A'}",
                    f"Issued: {rx.issued_at:%Y-%m-%d}",
                    f"Status: {rx.get_status_display()}",
                    f"Chief Complaints: {rx.chief_complaints or 'N/A'}",
                    f"Diagnosis: {rx.diagnosis or 'N/A'}",
                    f"Tests: {rx.tests_investigations or 'N/A'}",
                    f"Advice: {rx.advice_rules or 'N/A'}",
                    f"Doctor Notes: {rx.doctor_notes or 'N/A'}",
                    "Medicines:",
                ]
                for item in rx.items.select_related("medicine").all():
                    timing = TIMING_LABELS.get(item.timing_relation_to_meal, {}).get("en", item.timing_relation_to_meal)
                    rx_lines.append(
                        f"  - {item.medicine} ({item.medicine.generic_name}): {item.dosage}, "
                        f"{item.frequency}x/day, {item.duration_days} days, {timing}"
                        + (f". Note: {item.special_instructions}" if item.special_instructions else "")
                    )
                if hasattr(rx, "follow_up") and rx.follow_up:
                    fu = rx.follow_up
                    rx_lines.append(f"Follow-up: {fu.scheduled_date} — {fu.get_status_display()}")
                prescription_context = "\n".join(rx_lines)
        except Exception:
            pass

    full_prompt = (
        f"User Question: {question or 'দয়া করে এই আপলোড করা নথি/প্রেসক্রিপশনের ছবি বিশ্লেষণ করে পরামর্শ দিন।'}\n\n"
        f"PATIENT CONTEXT & CAREBRIDGE RECORDS:\n{patient_context}\n\n"
    )
    if prescription_context:
        full_prompt += f"PRESCRIPTION-SPECIFIC CONTEXT (Answer questions about this prescription):\n{prescription_context}\n\n"

    history_list = _history_to_messages(history or [], limit=10)

    ai_res = GeminiAIService.chat_with_patient_vision(
        user_message=full_prompt,
        image_file=image_file,
        conversation_history=history_list,
        preferred_language=language,
    )

    if ai_res.get("reply_text"):
        reply = ai_res["reply_text"]
        if any(w in (question or "").lower() for w in ["pain", "fever", "doctor", "ডাক্তার", "prescription", "ব্যথা", "জ্বর", "medicine", "health", "test"]):
            doctor_suggestion = suggest_doctors_for_query(question, language)
            if doctor_suggestion:
                reply += f"\n\n{doctor_suggestion}"
        return reply

    fallback = _local_patient_reply(question, language, patient)
    if any(w in (question or "").lower() for w in ["pain", "fever", "doctor", "ডাক্তার", "prescription", "ব্যথা", "জ্বর", "medicine", "health", "test"]):
        doctor_suggestion = suggest_doctors_for_query(question, language)
        if doctor_suggestion:
            fallback += f"\n\n{doctor_suggestion}"
    return fallback



def _build_messages(prompt, content, language):
    language_name = "Bangla" if language == "bn" else "English"
    return [
        {
            "role": "system",
            "content": (
                "You are a safe, patient-friendly medical assistant for CareBridge AI. "
                "Be clear, concise, empathetic, and practical. "
                "Never claim to diagnose. Encourage professional care for urgent symptoms."
            ),
        },
        {
            "role": "user",
            "content": f"{prompt}\n\nReply in {language_name}.\n\n{content}",
        },
    ]


def _plain_prescription_summary(prescription, language):
    items = list(prescription.items.select_related("medicine").all())
    doctor_name = prescription.doctor.user.get_full_name() or prescription.doctor.user.username
    specialty = prescription.doctor.specialty or "মেডিসিন বিশেষজ্ঞ" if language == "bn" else "Medical Specialist"
    clinic = prescription.doctor.clinic_name or "CareBridge Health Center"
    notes = prescription.doctor_notes.strip() if prescription.doctor_notes else ""
    complaints = prescription.chief_complaints.strip() if prescription.chief_complaints else ""
    diagnosis = prescription.diagnosis.strip() if prescription.diagnosis else ""
    advice = prescription.advice_rules.strip() if prescription.advice_rules else ""
    tests = prescription.tests_investigations.strip() if prescription.tests_investigations else ""
    fu = getattr(prescription, "follow_up", None)
    is_bn = language == "bn"

    if is_bn:
        overview_parts = [
            f"👨‍⚕️ চিকিৎসক: ডা. {doctor_name} ({specialty} — {clinic})",
            f"📅 প্রেসক্রিপশন তারিখ: {prescription.issued_at:%d %B %Y}",
            f"💊 মোট নির্ধারিত ওষুধ: {len(items)} টি",
        ]
        if complaints:
            overview_parts.append(f"📋 উপসর্গ/সমস্যা (C/C): {complaints}")
        if diagnosis:
            overview_parts.append(f"🩺 ডায়াগনোসিস/রোগ নির্ণয়: {diagnosis}")
        if tests:
            overview_parts.append(f"🔬 ল্যাব টেস্ট/পরীক্ষা-নিরীক্ষা: {tests}")

        overview = "\n".join(overview_parts)

        schedule_lines = []
        precautions_lines = [
            "• সব ওষুধ নির্দিষ্ট সময়ে এক গ্লাস বিশুদ্ধ পানির সাথে সেবন করুন।",
            "• ডাক্তারের পরামর্শ ব্যতিরেকে ওষুধ সেবন বন্ধ করবেন না বা ডোজ পরিবর্তন করবেন না।",
        ]
        if advice:
            precautions_lines.append(f"• জীবনযাত্রা ও খাদ্যভ্যাস উপদেশ: {advice}")

        warnings_lines = [
            "• যেকোনো ওষুধের কারণে অ্যালার্জি, ত্বকে লাল ফুসকুড়ি, অস্বাভাবিক দুর্বলতা বা শ্বাসকষ্ট দেখা দিলে অবিলম্বে সেবন বন্ধ করে ডাক্তারের পরামর্শ নিন।",
            "• হঠাৎ অতিরিক্ত বুক ব্যথা, রক্তবমি বা চেতনা হারানোর মতো লক্ষণ দেখা দিলে নিকটস্থ হাসপাতালের জরুরি বিভাগে যোগাযোগ করুন।"
        ]

        for item in items:
            timing = TIMING_LABELS.get(item.timing_relation_to_meal, {}).get("bn", "যেকোনো সময়")
            line = f"💊 {item.medicine} ({item.medicine.generic_name}):\n  - মাত্রা: {item.dosage} | দিনে {item.frequency} বার\n  - সময়কাল: {item.duration_days} দিন | খাবার নিয়ম: {timing}"
            if item.special_instructions:
                line += f"\n  - বিশেষ নির্দেশিকা: {item.special_instructions}"
                precautions_lines.append(f"• {item.medicine}: {item.special_instructions}")
            schedule_lines.append(line)

        if notes:
            precautions_lines.append(f"• ডাক্তারের বিশেষ নোট: {notes}")
        if fu:
            precautions_lines.append(f"📅 আগামী ফলো-আপ তারিখ: {fu.scheduled_date} ({fu.get_status_display()})")

        full_text = f"{overview}\n\n=== ওষুধের সময়সূচী ও নিয়মাবলী ===\n\n" + "\n\n".join(schedule_lines)
        if precautions_lines:
            full_text += "\n\n=== সতর্কতা ও বিশেষ নিয়মাবলী ===\n\n" + "\n".join(precautions_lines)

        return {
            "text": full_text,
            "overview": overview,
            "schedule": "\n\n".join(schedule_lines) if schedule_lines else "কোনো ওষুধের তথ্য পাওয়া যায়নি।",
            "precautions": "\n".join(precautions_lines),
            "warnings": "\n".join(warnings_lines),
            "source": "local",
        }

    # English version
    overview_parts = [
        f"👨‍⚕️ Physician: Dr. {doctor_name} ({specialty} — {clinic})",
        f"📅 Date Issued: {prescription.issued_at:%d %B %Y}",
        f"💊 Total Prescribed Medicines: {len(items)} item(s)",
    ]
    if complaints:
        overview_parts.append(f"📋 Chief Complaints: {complaints}")
    if diagnosis:
        overview_parts.append(f"🩺 Clinical Diagnosis: {diagnosis}")
    if tests:
        overview_parts.append(f"🔬 Investigations/Tests: {tests}")

    overview = "\n".join(overview_parts)

    schedule_lines = []
    precautions_lines = [
        "• Take all medications strictly at scheduled times with a full glass of water.",
        "• Do not stop or alter prescribed dosages without consulting your attending physician.",
    ]
    if advice:
        precautions_lines.append(f"• Lifestyle & Dietary Advice: {advice}")

    warnings_lines = [
        "• If you experience severe allergic reactions, skin rashes, or sudden dizziness, discontinue the medication and notify your doctor immediately.",
        "• For severe symptoms such as acute chest pain or loss of consciousness, seek emergency hospital care instantly."
    ]

    for item in items:
        timing = TIMING_LABELS.get(item.timing_relation_to_meal, {}).get("en", "Anytime")
        line = f"💊 {item.medicine} ({item.medicine.generic_name}):\n  - Dosage: {item.dosage} | Frequency: {item.frequency} time(s) daily\n  - Duration: {item.duration_days} days | Timing: {timing}"
        if item.special_instructions:
            line += f"\n  - Special Note: {item.special_instructions}"
            precautions_lines.append(f"• {item.medicine}: {item.special_instructions}")
        schedule_lines.append(line)

    if notes:
        precautions_lines.append(f"• Doctor's Additional Note: {notes}")
    if fu:
        precautions_lines.append(f"📅 Scheduled Follow-Up Date: {fu.scheduled_date} ({fu.get_status_display()})")

    full_text = f"{overview}\n\n=== Comprehensive Medication Schedule ===\n\n" + "\n\n".join(schedule_lines)
    if precautions_lines:
        full_text += "\n\n=== Safety & Precautions ===\n\n" + "\n".join(precautions_lines)

    return {
        "text": full_text,
        "overview": overview,
        "schedule": "\n\n".join(schedule_lines) if schedule_lines else "No medicine details available.",
        "precautions": "\n".join(precautions_lines),
        "warnings": "\n".join(warnings_lines),
        "source": "local",
    }


def summarize_prescription(prescription, language="en"):
    language = language if language in {"bn", "en"} else "en"
    item_lines = []
    for item in prescription.items.select_related("medicine").all():
        item_lines.append(
            f"- Medicine: {item.medicine} (Generic: {item.medicine.generic_name}); dosage: {item.dosage}; frequency: {item.frequency} per day; "
            f"duration: {item.duration_days} days; timing: {item.get_timing_relation_to_meal_display()}; "
            f"instructions: {item.special_instructions or 'None'}"
        )

    prompt = (
        "Analyze this medical prescription thoroughly and generate a comprehensive, highly detailed patient-friendly guide. "
        "Include:\n"
        "1. Overview & Doctor Details\n"
        "2. Exact Daily Medication Schedule (Dosage, Timing, Meals)\n"
        "3. Dietary Precautions & Food Interactions\n"
        "4. Red-Flag Warning Symptoms requiring immediate hospital care."
    )
    content = "\n".join([
        f"Doctor: {prescription.doctor.user.get_full_name()} ({prescription.doctor.specialty})",
        f"Chief Complaints: {prescription.chief_complaints or 'N/A'}",
        f"Diagnosis: {prescription.diagnosis or 'N/A'}",
        f"Doctor notes: {prescription.doctor_notes or 'None'}",
        "Prescription items:",
        *item_lines,
    ])
    ai_text = _request_chat_completion_messages(_build_messages(prompt, content, language))
    provider = _resolve_provider()

    local_fallback = _plain_prescription_summary(prescription, language)
    if ai_text:
        return {
            "text": ai_text,
            "overview": local_fallback["overview"],
            "schedule": local_fallback["schedule"],
            "precautions": local_fallback["precautions"],
            "warnings": local_fallback["warnings"],
            "source": provider["name"] if provider else "ai",
        }

    return local_fallback


GUEST_QA = {
    "what_is_carebridge": {
        "keywords": ["carebridge", "কেয়ারব্রীজ", "কারেব্রীজ", "ক্যারব্রিজ", "what is", "কি এই", "about", "সম্পর্কে"],
        "bn": (
            "🏥 **CareBridge AI কি?**\n\n"
            "CareBridge AI একটি স্মার্ট বাংলাদেশি টেলিমেডিসিন প্ল্যাটফর্ম যা রোগীদের verified ডাক্তারের সাথে সংযুক্ত করে।\n\n"
            "**প্রধান সেবাসমূহ:**\n"
            "• 💊 ডাক্তারPrescription digitally manage ও AI summary\n"
            "• 🤖 Gemini AI চ্যাটবট — ওষুধ, ডোজ, follow-up প্রশ্নে উত্তর\n"
            "• 🗓️ Follow-up tracking ও dose reminder system\n"
            "• 👨‍⚕️ Verified doctors খুঁজুন ও appointment book করুন\n"
            "• 📄 Prescription OCR scanning — ছবি থেকে medicine auto-extract\n"
            "• 🌐 bilingual support (বাংলা + English)\n\n"
            "💡 Register করে সম্পূর্ণ সুবিধা নিন!"
        ),
        "en": (
            "🏥 **What is CareBridge AI?**\n\n"
            "CareBridge AI is a smart Bangladeshi telemedicine platform connecting patients with verified doctors.\n\n"
            "**Key Features:**\n"
            "• 💊 Digital prescription management with AI-powered summaries\n"
            "• 🤖 Gemini AI chatbot for medicine, dose, and follow-up questions\n"
            "• 🗓️ Follow-up tracking and dose reminder system\n"
            "• 👨‍⚕️ Search verified doctors and book appointments\n"
            "• 📄 Prescription OCR scanning — auto-extract medicines from images\n"
            "• 🌐 Full bilingual support (Bangla + English)\n\n"
            "💡 Register to access all features!"
        ),
    },
    "how_to_register": {
        "keywords": ["register", "sign up", "account", "রেজিস্টার", "সাইন", "অ্যাকাউন্ট", "খোল", "join", "যোগ"],
        "bn": (
            "📝 **কিভাবে Register করবেন?**\n\n"
            "1. **Register** পেজে যান\n"
            "2. আপনার নাম, email, password দিন\n"
            "3. Role select করুন: **Patient** বা **Doctor**\n"
            "4. Patient হলে: district, NID/Birth Reg, identity doc upload\n"
            "5. Doctor হলে: BMDC number, certificate, specialty, clinic info\n"
            "6. Submit করুন — Admin verification অপেক্ষা করুন\n"
            "7. Verification complete হলে সম্পূর্ণ access পাবেন\n\n"
            "⚠️ Doctor registration requires BMDC certificate for verification."
        ),
        "en": (
            "📝 **How to Register?**\n\n"
            "1. Go to the **Register** page\n"
            "2. Enter your name, email, and password\n"
            "3. Select your role: **Patient** or **Doctor**\n"
            "4. For Patients: district, NID/Birth Reg, identity document upload\n"
            "5. For Doctors: BMDC number, certificate, specialty, clinic info\n"
            "6. Submit — wait for Admin verification\n"
            "7. Once verified, you get full platform access\n\n"
            "⚠️ Doctor registration requires BMDC certificate for verification."
        ),
    },
    "how_prescription_works": {
        "keywords": ["prescription", "prescribe", "medicine", "ঔষধ", "প্রেসক্রিপশন", "রxd", "dose", "ডোজ", "ওষুধ"],
        "bn": (
            "💊 **Prescription System কেমন কাজ করে?**\n\n"
            "1. **Doctor** patient খুঁজে assess করে\n"
            "2. Diagnosis, complaints, advice দিয়ে prescribe creates\n"
            "3. Medicines add করুন: brand, generic, dosage, frequency, duration\n"
            "4. Follow-up date set করুন\n"
            "5. Prescription automatically patient dashboard-এ appears\n"
            "6. Patient получит AI summary ও detailed guide\n"
            "7. Dose reminders automatically create হয়\n"
            "8. Patient doses mark করে track পারে\n\n"
            "AI-powered OCR: Prescription image upload করলেই Gemini Vision medicines auto-extract করে!"
        ),
        "en": (
            "💊 **How Does the Prescription System Work?**\n\n"
            "1. **Doctor** assesses the patient\n"
            "2. Creates prescription with diagnosis, complaints, and advice\n"
            "3. Adds medicines: brand, generic, dosage, frequency, duration\n"
            "4. Sets follow-up date\n"
            "5. Prescription automatically appears on patient dashboard\n"
            "6. Patient receives AI summary and detailed guide\n"
            "7. Dose reminders are automatically created\n"
            "8. Patient marks doses and tracks adherence\n\n"
            "AI-powered OCR: Upload a prescription image and Gemini Vision auto-extracts medicines!"
        ),
    },
    "how_ai_chatbot_works": {
        "keywords": ["chatbot", "chat", "bot", "AI assistant", "চ্যাট", "বট", "এআই", "assistant", "সহকারী", "ask"],
        "bn": (
            "🤖 **AI Chatbot কিভাবে কাজ করে?**\n\n"
            "CareBridge AI Chatbot Gemini-powered medical assistant:\n\n"
            "• **Prescription Q&A**: ওষudukের dosage, timing, side effect প্রশ্ন করুন\n"
            "• **Health Guidance**: symptoms, diet, lifestyle সম্পর্কে জিজ্ঞাসা করুন\n"
            "• **Doctor Suggestions**: আপনার condition অনুযায়ী verified doctors suggest পাবেন\n"
            "• **Document Analysis**: prescription image upload করলেই বিশ্লেষণ পাবেন\n"
            "• **Bilingual**: বাংলা ও English উভภาษাতে উত্তর\n\n"
            "Loginrequired না — Guest mode-এও ব্যবহার করতে পারবেন (logged in patients-এর জন্য personalized answer)!"
        ),
        "en": (
            "🤖 **How Does the AI Chatbot Work?**\n\n"
            "CareBridge AI Chatbot is a Gemini-powered medical assistant:\n\n"
            "• **Prescription Q&A**: Ask about medicine dosage, timing, side effects\n"
            "• **Health Guidance**: Ask about symptoms, diet, lifestyle\n"
            "• **Doctor Suggestions**: Get verified doctor suggestions based on your condition\n"
            "• **Document Analysis**: Upload prescription images for instant analysis\n"
            "• **Bilingual**: Answers in both Bangla and English\n\n"
            "No login required — use in Guest mode! (Logged-in patients get personalized answers)"
        ),
    },
    "how_verification_works": {
        "keywords": ["verification", "verify", "approved", "pending", "ভেরিফিকেশন", "অনুমোদন", "অপেক্ষা", "approve", "reject"],
        "bn": (
            "🔒 **Verification System:**\n\n"
            "সমস্ত users কে Admin verification বাধ্যতামূলক:\n\n"
            "**Patient verification:**\n"
            "• NID / Birth Registration number submit\n"
            "• Identity document upload (NID card / Birth cert)\n"
            "• Admin review করে approve বা reject করে\n\n"
            "**Doctor verification:**\n"
            "• BMDC registration number required\n"
            "• BMDC certificate upload required\n"
            "• Clinic details verify হয়\n"
            "• Admin final approval অপেক্ষা\n\n"
            "❌ Verificationpending থাকলে platform access নেই। Verified হলে সম্পূর্ণ功能 ব্যবহার করতে পারবেন।"
        ),
        "en": (
            "🔒 **Verification System:**\n\n"
            "All users require Admin verification before full access:\n\n"
            "**Patient verification:**\n"
            "• Submit NID / Birth Registration number\n"
            "• Upload identity document (NID card / Birth cert)\n"
            "• Admin reviews and approves/rejects\n\n"
            "**Doctor verification:**\n"
            "• BMDC registration number required\n"
            "• BMDC certificate upload required\n"
            "• Clinic details verified\n"
            "• Awaiting final Admin approval\n\n"
            "❌ Pending verification = no platform access. Once verified, full features unlock."
        ),
    },
    "how_dose_reminder_works": {
        "keywords": ["reminder", "dose", "schedule", "রিমাইন্ডার", "ডোজ", "টাইম", "alarm", "notification", "বার"],
        "bn": (
            "⏰ **Dose Reminder System:**\n\n"
            "Prescription create হলে automatically dose schedules generate হয়:\n\n"
            "• প্রতিটি medicine এর জন্য দিনwise reminder schedule\n"
            "• Timing: before_meal / after_meal / with_meal / anytime\n"
            "• Patient 'Today's Doses' পেজে marking করতে পারে: Taken / Skipped\n"
            "• Dashboard এ today's doses ও next follow-up দেখায়\n"
            "• Missed doses track করা হয়\n\n"
            "💡 Prescription এর duration যত থাকবে, reminder automatically生成 হবে।"
        ),
        "en": (
            "⏰ **Dose Reminder System:**\n\n"
            "When a prescription is created, dose schedules are auto-generated:\n\n"
            "• Per-medicine daily reminder schedules\n"
            "• Timing: before_meal / after_meal / with_meal / anytime\n"
            "• Patients mark doses on 'Today's Doses' page: Taken / Skipped\n"
            "• Dashboard shows today's doses and next follow-up\n"
            "• Missed doses are tracked\n\n"
            "💡 Reminders are auto-generated for the full prescription duration."
        ),
    },
    "how_followup_works": {
        "keywords": ["followup", "follow-up", "follow up", "ফলো", "ফলোআপ", "next visit", "checkup", "revisit"],
        "bn": (
            "📅 **Follow-up System:**\n\n"
            "• Doctor prescription এর সাথে follow-up date set করে\n"
            "• Patient 'Follow-ups' পেজে সব upcoming, completed, missed দেখতে পারে\n"
            "• Auto-completion: Doctor নতুন prescribe করলে automatically follow-up complete হয়\n"
            "• Auto-missed: date_pass হলে missed mark হয়\n"
            "• Patient বা Doctor follow-up manually complete marking করতে পারে\n\n"
            "📋 Follow-up এ攜帯 your health journey timeline for better consultation."
        ),
        "en": (
            "📅 **Follow-up System:**\n\n"
            "• Doctor sets follow-up date with prescription\n"
            "• Patients view all upcoming, completed, missed visits\n"
            "• Auto-completion: New prescription from same doctor auto-completes follow-up\n"
            "• Auto-missed: Past-due follow-ups marked as missed\n"
            "• Patients or Doctors can manually mark as completed\n\n"
            "📋 Bring your health journey timeline to follow-up for better consultation."
        ),
    },
    "how_ocr_scanning_works": {
        "keywords": ["ocr", "scan", "scanning", "extract", "image", "ছবি", "স্ক্যান", "অনুলিপি", "upload", "আপলোড", "prescription image"],
        "bn": (
            "📄 **Prescription OCR Scanning:**\n\n"
            "1. **Prescriptions > Scan Prescription** পেজে যান\n"
            "2. Prescription image (JPG/PNG) upload করুন\n"
            "3. Gemini Vision AI automatically analyze করে:\n"
            "   • Doctor name, hospital/clinic\n"
            "   • Patient name\n"
            "   • সব medicines (brand, generic, dosage, frequency)\n"
            "   • Follow-up date, notes\n"
            "4. Result দেখুন ও必要时 manually edit করুন\n\n"
            "✨ This saves time writing prescriptions manually!"
        ),
        "en": (
            "📄 **Prescription OCR Scanning:**\n\n"
            "1. Go to **Prescriptions > Scan Prescription**\n"
            "2. Upload prescription image (JPG/PNG)\n"
            "3. Gemini Vision AI automatically extracts:\n"
            "   • Doctor name, hospital/clinic\n"
            "   • Patient name\n"
            "   • All medicines (brand, generic, dosage, frequency)\n"
            "   • Follow-up date, notes\n"
            "4. Review results and edit manually if needed\n\n"
            "✨ This saves time entering prescriptions manually!"
        ),
    },
    "how_health_record_works": {
        "keywords": ["health record", "health journey", "timeline", "medical history", "স্বাস্থ্য রেকর্ড", "টাইমলাইন", "ইতিহাস", "report", "রিপোর্ট"],
        "bn": (
            "📋 **Health Record & Timeline:**\n\n"
            "• সব prescriptions ও uploaded reports একসাথে chronological timeline-এ দেখায়\n"
            "• Prescription details: doctor, diagnosis, medicines, advice\n"
            "• Lab reports, X-rays, external prescriptions upload করুন\n"
            "• AI Health Journey Assistant: আপনার medical history ভিত্তicamente প্রশ্ন করুন\n"
            "• Timeline automatically sorts by date\n\n"
            "💡 এটি আপনার সম্পূর্ণ medical journey digital रखে!"
        ),
        "en": (
            "📋 **Health Record & Timeline:**\n\n"
            "• All prescriptions and uploaded reports in one chronological timeline\n"
            "• Prescription details: doctor, diagnosis, medicines, advice\n"
            "• Upload lab reports, X-rays, external prescriptions\n"
            "• AI Health Journey Assistant: Ask questions based on your full medical history\n"
            "• Timeline auto-sorts by date\n\n"
            "💡 Keeps your complete medical journey digitally organized!"
        ),
    },
    "how_doctor_booking_works": {
        "keywords": ["book", "booking", "appointment", "অ্যাপয়েন্টমেন্ট", "বুক", "schedule", "সাক্ষাৎ"],
        "bn": (
            "👨‍⚕️ **Doctor Booking System:**\n\n"
            "1. **Find Doctors** পেজে যান\n"
            "2. specialty, location, name দিয়ে search করুন\n"
            "3. Verified doctors এর profile দেখুন (experience, clinic, ratings)\n"
            "4. Google Maps এ location দেখুন\n"
            "5. **Book Visit** click করুন\n"
            "6. Doctor কে notification পাঠায়\n"
            "7. Doctor confirm করলে appointment confirmed হয়\n\n"
            "💡 আগে verified doctors এর availability ও schedule দেখুন!"
        ),
        "en": (
            "👨‍⚕️ **Doctor Booking System:**\n\n"
            "1. Go to **Find Doctors** page\n"
            "2. Search by specialty, location, or name\n"
            "3. View verified doctor profiles (experience, clinic, ratings)\n"
            "4. See location on Google Maps\n"
            "5. Click **Book Visit**\n"
            "6. Doctor receives notification\n"
            "7. Once doctor confirms, appointment is confirmed\n\n"
            "💡 Check verified doctors' availability and schedules first!"
        ),
    },
    "is_carebridge_free": {
        "keywords": ["free", "cost", "price", "pay", "payment", "মুક্ত", "বিনামূল্যে", "খরচ", "টাকা", "subscription", "সাবস্ক্রিপশন"],
        "bn": (
            "💳 **CareBridge AI মূল্য নীতিমালা:**\n\n"
            "• **Free Plan**: Registration, health record, AI chatbot (limited), prescription view\n"
            "• **Premium Plans**: Unlimited AI, priority booking, advanced features\n"
            "• Doctors: Subscription plans for chamber management\n"
            "• Secure payment via bKash / Nagad / Card (coming soon)\n\n"
            "📞 Currently registration & core features are FREE for patients!"
        ),
        "en": (
            "💳 **CareBridge AI Pricing:**\n\n"
            "• **Free Plan**: Registration, health records, AI chatbot (limited), prescription viewing\n"
            "• **Premium Plans**: Unlimited AI, priority booking, advanced features\n"
            "• Doctors: Subscription plans for chamber management\n"
            "• Secure payment via bKash / Nagad / Card (coming soon)\n\n"
            "📞 Registration and core features are currently FREE for patients!"
        ),
    },
    "is_data_secure": {
        "keywords": ["secure", "security", "privacy", "data", "personal", "information", "সুরক্ষিত", "গোপনীয়তা", "নij", "confidential", "safe"],
        "bn": (
            "🔐 **Data Security & Privacy:**\n\n"
            "•HIPAA-inspired design principles\n"
            "• End-to-end encryption for sensitive medical data\n"
            "• Admin-only access to verification documents\n"
            "• Patient controls their own data (view, update, delete)\n"
            "• No data sharing with third parties without consent\n"
            "• Secure Django backend with CSRF protection\n\n"
            "🛡️ Your health data is safe with CareBridge."
        ),
        "en": (
            "🔐 **Data Security & Privacy:**\n\n"
            "• HIPAA-inspired design principles\n"
            "• End-to-end encryption for sensitive medical data\n"
            "• Admin-only access to verification documents\n"
            "• Patients control their own data (view, update, delete)\n"
            "• No third-party data sharing without consent\n"
            "• Secure Django backend with CSRF protection\n\n"
            "🛡️ Your health data is safe with CareBridge."
        ),
    },
    "how_to_contact_support": {
        "keywords": ["support", "help", "contact", "contact us", "problem", "issue", "error", "সহায়তা", "সমস্যা", "যোগাযোগ", "helpdesk"],
        "bn": (
            "📞 **Support & Help:**\n\n"
            "• **In-App Chat**: Use this AI assistant for instant help\n"
            "• **Email**: support@carebridge.ai\n"
            "• **Phone**: +880 1700-000000 (Coming soon)\n"
            "• **Emergency**: Call 999 for medical emergencies\n\n"
            "💡 For prescription or technical issues, describe your problem and we will guide you!"
        ),
        "en": (
            "📞 **Support & Help:**\n\n"
            "• **In-App Chat**: Use this AI assistant for instant help\n"
            "• **Email**: support@carebridge.ai\n"
            "• **Phone**: +880 1700-000000 (Coming soon)\n"
            "• **Emergency**: Call 999 for medical emergencies\n\n"
            "💡 For prescription or technical issues, describe your problem and we will guide you!"
        ),
    },
    "what_are_system_requirements": {
        "keywords": ["browser", "mobile", "phone", "app", "ios", "android", "device", "requirement", " ব্রাউজার", "মোবাইল", "অ্যাপ"],
        "bn": (
            "📱 **System Requirements:**\n\n"
            "• **Browser**: Chrome, Firefox, Safari, Edge (latest versions)\n"
            "• **Mobile**: Fully responsive — use on any smartphone\n"
            "• **Internet**: Stable connection for AI features\n"
            "• **Camera**: For uploading prescription images\n"
            "• **No app download needed** — works in browser\n\n"
            "💡 Best experienced on Chrome mobile or desktop."
        ),
        "en": (
            "📱 **System Requirements:**\n\n"
            "• **Browser**: Chrome, Firefox, Safari, Edge (latest versions)\n"
            "• **Mobile**: Fully responsive — works on any smartphone\n"
            "• **Internet**: Stable connection for AI features\n"
            "• **Camera**: For uploading prescription images\n"
            "• **No app download needed** — works in browser\n\n"
            "💡 Best experienced on Chrome mobile or desktop."
        ),
    },
    "how_voice_chat_works": {
        "keywords": ["voice", "speak", "microphone", "ভয়েস", "কথা", "বলা", "মাইক্রোফোন", "audio", "শোনা", "listen", "stt", "tts"],
        "bn": (
            "🎙️ **Voice Chat Feature:**\n\n"
            "• Voice input: মাইক্রোফোনে কথা বলুন — STT (Speech-to-Text) automatically convert করে\n"
            "• Voice output: AI Answers listen করুন — TTS (Text-to-Speech) Anglicizes\n"
            "• Bilingual: Bangla ও English voice support\n"
            "• Real-time: WebSocket-based low-latency voice streaming\n"
            "• Powered by Soniox STT + Google TTS\n\n"
            "🎧 Click microphone button to start voice chat!"
        ),
        "en": (
            "🎙️ **Voice Chat Feature:**\n\n"
            "• Voice input: Speak into microphone — STT (Speech-to-Text) auto-converts\n"
            "• Voice output: Listen to AI answers — TTS (Text-to-Speech) reads aloud\n"
            "• Bilingual: Bangla and English voice support\n"
            "• Real-time: WebSocket-based low-latency voice streaming\n"
            "• Powered by Soniox STT + Google TTS\n\n"
            "🎧 Click the microphone button to start voice chat!"
        ),
    },
    "how_to_update_profile": {
        "keywords": ["profile", "update", "edit", "change", "প্রোফাইল", "আপডেট", "পরিবর্তন", "name", "নাম", "avatar", "language", "ভাষা"],
        "bn": (
            "👤 **Profile Update:**\n\n"
            "1. **Profile** পেজে যান (loginrequired)\n"
            "2. Change করুন:\n"
            "   • Full Name\n"
            "   • Profile Avatar\n"
            "   • Preferred Language (বাংলা / English)\n"
            "3. Save cambios\n\n"
            "💡 Language change automatically entire site-এ apply হবে!"
        ),
        "en": (
            "👤 **Profile Update:**\n\n"
            "1. Go to **Profile** page (login required)\n"
            "2. Update:\n"
            "   • Full Name\n"
            "   • Profile Avatar\n"
            "   • Preferred Language (Bangla / English)\n"
            "3. Save changes\n\n"
            "💡 Language change applies across the entire site automatically!"
        ),
    },
    "how_to_reset_password": {
        "keywords": ["password", "reset", "forgot", "change", "পাসওয়ার্ড", "রিসেট", "ভুল", "লগইন", "login"],
        "bn": (
            "🔑 **Password Reset:**\n\n"
            "1. Login পেজে **Forgot Password?** click করুন\n"
            "2. আপনার registered email address দিন\n"
            "3. Reset link email-এ পাঠানো হবে\n"
            "4. Link click করে নতুন password set করুন\n"
            "5. Login করুন with new password\n\n"
            "⚠️ Email check করুন — spam folder-এও দেখুন।"
        ),
        "en": (
            "🔑 **Password Reset:**\n\n"
            "1. On Login page, click **Forgot Password?**\n"
            "2. Enter your registered email address\n"
            "3. Reset link will be sent to your email\n"
            "4. Click link and set a new password\n"
            "5. Log in with your new password\n\n"
            "⚠️ Check your email — also look in spam folder."
        ),
    },
    "what_specialties_available": {
        "keywords": ["specialist", "specialty", "department", "বিশেষজ্ঞ", "ডাক্তার", "কার্ডিও", "নিউরো", "গ্যাস্ট্রো", "endo", "medicine"],
        "bn": (
            "🏥 **Available Specialties:**\n\n"
            "CareBridge এ verified doctors এর specialties:\n\n"
            "• 🫀 Cardiology (Cardiac / Heart)\n"
            "• 🧠 Neurology (Brain & Nerves)\n"
            "• 🫁 Pulmonology (Chest & Lungs)\n"
            "• 🦴 Orthopedics (Bones & Joints)\n"
            "• 👁️ Ophthalmology (Eyes)\n"
            "• 👶 Pediatrics (Children)\n"
            "• 🤰 Gynecology (Women's Health)\n"
            "• 🧪 Dermatology (Skin)\n"
            "• 💊 General Medicine\n"
            "• 🧬 Endocrinology (Diabetes/Hormones)\n\n"
            "💡 আরো specialties যুক্ত হচ্ছে!"
        ),
        "en": (
            "🏥 **Available Specialties:**\n\n"
            "Verified doctors on CareBridge cover:\n\n"
            "• 🫀 Cardiology (Heart)\n"
            "• 🧠 Neurology (Brain & Nerves)\n"
            "• 🫁 Pulmonology (Chest & Lungs)\n"
            "• 🦴 Orthopedics (Bones & Joints)\n"
            "• 👁️ Ophthalmology (Eyes)\n"
            "• 👶 Pediatrics (Children)\n"
            "• 🤰 Gynecology (Women's Health)\n"
            "• 🧪 Dermatology (Skin)\n"
            "• 💊 General Medicine\n"
            "• 🧬 Endocrinology (Diabetes/Hormones)\n\n"
            "💡 More specialties being added regularly!"
        ),
    },
    "how_to_ask_doctor_questions": {
        "keywords": ["ask doctor", "consult", "second opinion", "question", "ডাক্তারকে প্রশ্ন", "পরামর্শ", "raħħa", "রਾਹা"],
        "bn": (
            "🩺 **Doctor Consultation Tips:**\n\n"
            "1. **Find Doctors** থেকে relevant specialist select করুন\n"
            "2. Profile দেখুন — experience, qualification, reviews\n"
            "3. **Book Visit** — doctor কে notification যায়\n"
            "4. Chatbot-এ symptoms describe করুন — AI guide করে\n"
            "5. Prescription upload করলেই AI analyze করে guide দেয়\n"
            "6. Follow-up schedule করুন\n\n"
            "💡 Clear symptoms describe করলে doctor better understand করতে পারেন!"
        ),
        "en": (
            "🩺 **Doctor Consultation Tips:**\n\n"
            "1. Select a relevant specialist from **Find Doctors**\n"
            "2. Check profile — experience, qualification, reviews\n"
            "3. **Book Visit** — doctor receives notification\n"
            "4. Describe symptoms in chatbot — AI guides you\n"
            "5. Upload prescription — AI analyzes and guides\n"
            "6. Schedule follow-up\n\n"
            "💡 Describe symptoms clearly for better doctor understanding!"
        ),
    },
    "how_prescription_download_works": {
        "keywords": ["download", "pdf", "print", "save", "ডাউনলোড", "পিডিএফ", "প্রিন্ট", "সংরক্ষণ"],
        "bn": (
            "📥 **Prescription Download:**\n\n"
            "1. Prescriptions timeline-এ Download Rx button click করুন\n"
            "2. Official medical prescription sheet opens\n"
            "3. Browser print dialog এ যান (Ctrl+P)\n"
            "4. **Save as PDF** select করুন\n"
            "5. Prescription official A4 format-এdownload হবে\n\n"
            "✨ Print-ready format with doctor signature block!"
        ),
        "en": (
            "📥 **Prescription Download:**\n\n"
            "1. Click **Download Rx** on prescription timeline\n"
            "2. Official medical prescription sheet opens\n"
            "3. Open browser print dialog (Ctrl+P)\n"
            "4. Select **Save as PDF**\n"
            "5. Prescription downloads in official A4 format\n\n"
            "✨ Print-ready format with doctor signature block!"
        ),
    },
    "how_notifications_work": {
        "keywords": ["notification", "alert", "notify", "বিজ্ঞপ্তি", "নোটিফিকেশন", "alarm", "message", "বার্তা"],
        "bn": (
            "🔔 **Notification System:**\n\n"
            "• Doctor নতুন prescribe করলে patient কে notification\n"
            "• Follow-up reminder notifications\n"
            "• Appointment booking confirmations\n"
            "• Verification status updates\n"
            "• In-app notification bell icon দেখুন\n\n"
            "💡 সব notifications patient ও doctor dashboard-এ available।"
        ),
        "en": (
            "🔔 **Notification System:**\n\n"
            "• Patient notified when doctor issues new prescription\n"
            "• Follow-up reminder notifications\n"
            "• Appointment booking confirmations\n"
            "• Verification status updates\n"
            "• Check notification bell icon in-app\n\n"
            "💡 All notifications available on patient and doctor dashboards."
        ),
    },
    "general_greeting": {
        "keywords": ["hello", "hi", "hey", "assalam", "salam", "প্রণাম", "হ্যালো", "হাই", "হే"],
        "bn": (
            "👋 **Assalamu Alaikum! CareBridge AI-এ স্বাগতম।**\n\n"
            "আমি আপনার স্বাস্থ্য সহায়ক। নিচের বিষয়গুলি সম্পর্কে জানতে পারেন:\n\n"
            "• CareBridge AI কি ও কিভাবে কাজ করে?\n"
            "• Registration ও verification process\n"
            "• Prescription, dose reminder, follow-up system\n"
            "• AI chatbot ও voice chat features\n"
            "• Doctor booking ও health record management\n\n"
            "আপনার কোনো প্রশ্ন থাকলে জিজ্ঞাসা করুন!"
        ),
        "en": (
            "👋 **Hello! Welcome to CareBridge AI.**\n\n"
            "I am your health assistant. You can ask about:\n\n"
            "• What is CareBridge AI and how it works?\n"
            "• Registration and verification process\n"
            "• Prescription, dose reminder, follow-up system\n"
            "• AI chatbot and voice chat features\n"
            "• Doctor booking and health record management\n\n"
            "Feel free to ask any question!"
        ),
    },
}


def guest_reply(question, language="bn"):
    """Return static Q&A answers for guest (non-logged-in) users."""
    q = (question or "").lower().strip()
    is_bn = language == "bn"

    for key, qa in GUEST_QA.items():
        if any(w in q for w in qa["keywords"]):
            return qa["bn"] if is_bn else qa["en"]

    return (
        "👋 CareBridge AI-এ স্বাগতম! নিচের বিষয়গুলি সম্পর্কে জানতে পারেন:\n"
        "• CareBridge AI কি ও কিভাবে কাজ করে?\n"
        "• Registration, verification, prescription system\n"
        "• AI chatbot, voice chat, dose reminders\n"
        "• Doctor booking ও health record management\n\n"
        "আপনার কোনো প্রশ্ন থাকলে জিজ্ঞাসা করুন!"
        if is_bn else
        "👋 Welcome to CareBridge AI! You can ask about:\n"
        "• What is CareBridge AI and how it works?\n"
        "• Registration, verification, prescription system\n"
        "• AI chatbot, voice chat, dose reminders\n"
        "• Doctor booking and health record management\n\n"
        "Feel free to ask any question!"
    )


def suggest_doctors_for_query(query, language="bn"):
    """Suggest relevant doctors based on user query symptoms/topics."""
    from accounts.models import Doctor

    q = (query or "").lower()
    is_bn = language == "bn"

    specialty_keywords = {
        "cardiology": ["হৃদ", "বুক", "chest pain", "pressure", "bp", "রক্তচাপ", "heart", "cardio"],
        "neurology": ["মাথা", "mind", "brain", "stroke", "neurologist", "নিউরোলজি", "migraine"],
        "pulmonology": ["কাশি", "cough", "lung", "breath", "শ্বাস", "chest", "asthma", "বক্ষ"],
        "orthopedics": ["bone", "joint", "fracture", "হাড়", "অর্থোপেডিক", "pain", "ব্যথা", "back pain", "কাঁধ"],
        "dermatology": ["skin", "ত্বকে", "র‍্যাশ", "rash", "itch", "চুলা", "dermatology", "হাইজেন"],
        "pediatrics": ["child", "kids", "শিশু", "babies", "infant", "শিশু"],
        "gynecology": ["pregnancy", "maternity", "women", "মহিলা", "গাইনোক", "menstrual", "পুরুষ"],
        "endocrinology": ["diabetes", "sugar", "thyroid", "ডায়াবেটিস", "থাইরয়েড", "endo", "হরমোন"],
        "gastroenterology": ["stomach", "গ্যাস", "গ্যাস্ট্রিক", "acidity", "পেট", "liver", "লিভার", "digest"],
        "psychiatry": ["mental", "anxiety", "depression", "sleep", "মন", "manobik", "sleep", "stress"],
        "ophthalmology": ["eye", "চোখ", "vision", "দৃষ্টি", "ophthalmo"],
        "ent": ["ear", "nose", "throat", "কান", "নাক", "গলা", "sore throat", "ENT"],
        "urology": ["urine", "urin", "kidney", "কিডনি", "মূত্র", "urology"],
        "nephrology": ["kidney", "কিডনি", "renal", "নেফ্র"],
    }

    matched_specialty = None
    for specialty, keywords in specialty_keywords.items():
        if any(w in q for w in keywords):
            matched_specialty = specialty
            break

    doctors = Doctor.objects.filter(is_verified=True).select_related("user")
    if matched_specialty:
        doctors = doctors.filter(specialty__icontains=matched_specialty)
    doctors = doctors[:5]

    if not doctors.exists():
        return None

    if is_bn:
        lines = [f"👨‍⚕️ **আপনার সাম garde Suggested Verified Doctors:**\n"]
        for d in doctors:
            lines.append(
                f"• **Dr. {d.user.get_full_name() or d.user.username}** — {d.specialty or 'General Physician'}\n"
                f"  Clinic: {d.clinic_name or 'N/A'} | Location: {d.location_text or 'N/A'}\n"
                f"  💡 Book appointment from 'Find Doctors' page"
            )
        return "\n".join(lines)
    else:
        lines = [f"👨‍⚕️ **Suggested Verified Doctors Based on Your Query:**\n"]
        for d in doctors:
            lines.append(
                f"• **Dr. {d.user.get_full_name() or d.user.username}** — {d.specialty or 'General Physician'}\n"
                f"  Clinic: {d.clinic_name or 'N/A'} | Location: {d.location_text or 'N/A'}\n"
                f"  💡 Book appointment from 'Find Doctors' page"
            )
        return "\n".join(lines)
