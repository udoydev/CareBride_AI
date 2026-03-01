import json

from accounts.models import Doctor
from carebridge.ai_services import GeminiAIService
from prescriptions.models import Prescription


def analyze_prescription_deep(prescription, language="en"):
    """Generate a deep, structured analysis of a prescription using Gemini AI."""
    items = list(prescription.items.select_related("medicine").all())
    doctor = prescription.doctor
    doctor_name = doctor.user.get_full_name() or doctor.user.username
    specialty = doctor.specialty or "General Physician"
    clinic = doctor.clinic_name or "CareBridge Health Center"
    location = doctor.location_text or "Bangladesh"
    is_bn = language == "bn"

    # Build structured medicine data for AI
    medicine_lines = []
    for idx, item in enumerate(items, 1):
        med = item.medicine
        timing_bn = {
            "before_meal": "খাবারের আগে",
            "after_meal": "খাবারের পরে",
            "with_meal": "খাবারের সাথে",
            "anytime": "যেকোনো সময়",
        }.get(item.timing_relation_to_meal, item.timing_relation_to_meal)
        timing_en = {
            "before_meal": "Before meals",
            "after_meal": "After meals",
            "with_meal": "With meals",
            "anytime": "Anytime",
        }.get(item.timing_relation_to_meal, item.timing_relation_to_meal)

        medicine_lines.append(
            f"Medicine {idx}:\n"
            f"  Brand: {med.brand_name}\n"
            f"  Generic: {med.generic_name}\n"
            f"  Form: {med.form or 'N/A'}\n"
            f"  Manufacturer: {med.manufacturer or 'N/A'}\n"
            f"  Dosage: {item.dosage}\n"
            f"  Frequency: {item.frequency} time(s) per day\n"
            f"  Duration: {item.duration_days} days\n"
            f"  Timing: {timing_bn} / {timing_en}\n"
            f"  Special Instructions: {item.special_instructions or 'None'}"
        )

    # Build context for AI
    prompt = (
        "You are CareBridge AI — an expert medical prescription analyzer for patients in Bangladesh. "
        f"Analyze this prescription in extreme detail and provide a comprehensive, structured, patient-friendly report.\n\n"
        f"Language: {'Bangla (বাংলা)' if is_bn else 'English'}\n\n"
        f"=== PRESCRIPTION DATA ===\n"
        f"Doctor: {doctor_name}\n"
        f"Specialty: {specialty}\n"
        f"Clinic: {clinic}\n"
        f"Location: {location}\n"
        f"Issued: {prescription.issued_at.strftime('%d %B %Y')}\n"
        f"Status: {prescription.get_status_display()}\n\n"
        f"Chief Complaints: {prescription.chief_complaints or 'Not specified'}\n"
        f"Diagnosis: {prescription.diagnosis or 'Not specified'}\n"
        f"Tests/Investigations: {prescription.tests_investigations or 'Not specified'}\n"
        f"Doctor Notes: {prescription.doctor_notes or 'None'}\n"
        f"Doctor Advice: {prescription.advice_rules or 'None'}\n\n"
        f"=== MEDICINES ===\n"
        f"{chr(10).join(medicine_lines)}\n\n"
        f"=== INSTRUCTIONS ===\n"
        f"Generate a JSON object with these exact keys (NO markdown wrappers, pure JSON):\n"
        f"{{\n"
        f'  "overview": "2-3 sentence summary of what this prescription treats and the doctor\'s approach",\n'
        f'  "medicines_breakdown": [\n'
        f"    {{\n"
        f'      "name": "Medicine name",\n'
        f'      "generic": "Generic name",\n'
        f'      "purpose": "What this medicine does in simple terms",\n'
        f'      "how_to_take": "Step-by-step instructions for taking this medicine",\n'
        f'      "duration_guidance": "How long to take and what to expect",\n'
        f'      "side_effects": ["Common side effect 1", "Common side effect 2", "When to stop and see a doctor"]\n'
        f"    }}\n"
        f"  ],\n"
        f'  "diet_interactions": ["Food/drink to avoid with these medicines", "Best foods to take with them", "Timing tips"],\n'
        f'  "lifestyle_tips": ["Exercise recommendations", "Sleep advice", "Stress management specific to this condition"],\n'
        f'  "warning_signs": ["Red flag symptom 1 requiring immediate hospital", "Red flag symptom 2", "When to call doctor urgently"],\n'
        f'  "follow_up_guidance": "What to expect at follow-up and what to bring",\n'
        f'  "faq": [\n'
        f'    {{"q": "Common question patients ask", "a": "Clear answer in simple terms"}}\n'
        f"  ]\n"
        f"}}\n\n"
        f"IMPORTANT: Make the content very detailed, empathetic, and easy for a non-medical person to understand. "
        f"Use simple Bangla or English terms. Include specific warnings relevant to each medicine. "
        f"Do NOT include any markdown code blocks — output pure JSON only."
    )

    # Try AI first
    ai_result = None
    try:
        ai_result = GeminiAIService.chat_with_patient_vision(
            user_message=prompt,
            image_file=None,
            conversation_history=[],
            preferred_language=language,
        )
    except Exception:
        pass

    if ai_result and ai_result.get("reply_text"):
        try:
            raw = ai_result["reply_text"].strip()
            # Clean markdown wrappers
            raw = raw.replace("```json", "").replace("```", "").strip()
            # Try to parse JSON
            if raw.startswith("{"):
                data = json.loads(raw)
                data["source"] = "ai"
                return data
        except (json.JSONDecodeError, Exception):
            pass

    # Fallback: build structured local analysis
    return _build_local_deep_analysis(prescription, language, items, doctor_name, specialty, clinic)


def _build_local_deep_analysis(prescription, language, items, doctor_name, specialty, clinic):
    """Build a comprehensive local fallback analysis without AI."""
    is_bn = language == "bn"
    timing_labels = {
        "before_meal": "খাবারের আগে" if is_bn else "Before meals",
        "after_meal": "খাবারের পরে" if is_bn else "After meals",
        "with_meal": "খাবারের সাথে" if is_bn else "With meals",
        "anytime": "যেকোনো সময়" if is_bn else "Anytime",
    }

    medicines_breakdown = []
    for item in items:
        med = item.medicine
        medicines_breakdown.append({
            "name": med.brand_name or med.generic_name,
            "generic": med.generic_name,
            "purpose": (
                f"এই ওষুধ আপনার শারীরের সমস্যা সমাধান ও স্বাস্থ্য ফিরিয়ে আনার জন্য নির্ধারিত।"
                if is_bn else
                f"This medicine is prescribed to treat your condition and restore health."
            ),
            "how_to_take": (
                f"{item.dosage} সেবন করুন, দিনে {item.frequency} বার, {item.duration_days} দিনের জন্য, "
                f"{timing_labels.get(item.timing_relation_to_meal, 'যেকোনো সময়')}। "
                f"{item.special_instructions or 'ডাক্তারের পরামর্শ অনুযায়ী সেবন করুন।'}"
                if is_bn else
                f"Take {item.dosage}, {item.frequency} time(s) daily for {item.duration_days} days, "
                f"{timing_labels.get(item.timing_relation_to_meal, 'anytime')}. "
                f"{item.special_instructions or 'Follow your doctors instructions.'}"
            ),
            "duration_guidance": (
                f"পুরো {item.duration_days} দিনের জন্য নিয়মিত সেবন করুন। ওষুধ শেষ হলে Doctor-কে জানান।"
                if is_bn else
                f"Complete the full {item.duration_days} day course. Inform your doctor when finished."
            ),
            "side_effects": (
                [
                    "মাথা ব্যথা, বমি ভাব, বা পেটে অমিত্রസা হতে পারে।",
                    "ত্বকে র‍্যাশ বা শ্বাসকষ্ট হলে অবিলম্বে সেবন বন্ধ করুন।",
                    "হঠাৎ বুকে ব্যথা বা শ্বাসকষ্ট হলে দ্রুত ডাক্তারের পরামর্শ নিন।",
                ]
                if is_bn else
                [
                    "Mild headache, nausea, or stomach upset may occur initially.",
                    "Discontinue immediately if rash, breathing difficulty, or swelling appears.",
                    "Seek emergency care for severe chest pain or sudden breathlessness.",
                ]
            ),
        })

    diet_interactions = (
        [
            "তৈলাক্ত, ভাজাভুজি ও মসলাযুক্ত খাবার এড়িয়ে চলুন।",
            "ওষুধ সেবনের ৩০ মিনিট পর হালকা খাবার খাওয়া উত্তম।",
            "দুধ, ক্যাফেইন বা অ্যালকোহল সেবনে সতর্কতা করুন।",
        ]
        if is_bn else
        [
            "Avoid oily, fried, and overly spicy foods during treatment.",
            "Take medication 30 minutes before or 1 hour after meals as directed.",
            "Limit caffeine, alcohol, and grapefruit products which may interact.",
        ]
    )

    lifestyle_tips = (
        [
            "প্রতিদিন ৩০ মিনিট হালকা হাঁটা বা লম্বিত的运动 করুণ।",
            "প্রতিদিন ৭-৮ ঘণ্টা পর্যাপ্ত ঘুম নিন।",
            "মানসিক চাপ কমানোর জন্য মেডিটেশন বা গভীর শ্বাসপ্রশ্বাস অনুশীলন করুন।",
        ]
        if is_bn else
        [
            "30 minutes of light walking daily as tolerated.",
            "Aim for 7-8 hours of quality sleep each night.",
            "Practice stress reduction through meditation or deep breathing.",
        ]
    )

    warning_signs = (
        [
            "হঠাৎ তীব্র বুকে ব্যথা বা বুক ধড়ফড় — হাসপাতালে যান।",
            "অসুস্থতা ৩ দিনের বেশি বা হিংস্রতা ১০২°F+ — অবিলম্বে ডাক্তার দেখান।",
            "ত্বকে র‍্যাশ, শ্বাসকষ্ট, বা অজ্ঞান হওয়া — জরুরি চিকিৎসা নিন।",
        ]
        if is_bn else
        [
            "Severe chest pain or palpitations — go to hospital immediately.",
            "Symptoms worsening after 3 days or fever above 102°F — see doctor urgently.",
            "Rash, breathing difficulty, or confusion — seek emergency care.",
        ]
    )

    overview = (
        f"👨‍⚕️ ডা. {doctor_name} ({specialty}) আপনার জন্য এই প্রেসক্রিপশন দিয়েছেন। "
        f" Diagnosis: {prescription.diagnosis or 'নির্ধারিত হয়েছে'}। "
        f"মোট {len(items)} টি ওষুধ নির্ধারিত করা হয়েছে। নিয়মিত সেবন করুন ও follow-up তারিখ মেনে চলুন।"
        if is_bn else
        f"Dr. {doctor_name} ({specialty}) issued this prescription for your condition: "
        f"{prescription.diagnosis or 'as diagnosed'}. "
        f"{len(items)} medicine(s) prescribed. Take regularly and attend follow-up."
    )

    faq = (
        [
            {"q": "ওষুধ missed হলে করণীয়?", "a": "ওষুধ missed করে থাকলে সেই ওষুধটি skip করুন, পরের ডোজ scheduled সময়ে সেবন করুন।"},
            {"q": "কোনো ওষুধ বন্ধ করবো কিভাবে?", "a": "Doctor-এর পরামর্শ ব্যতিরেকে কোনো ওষুধ বন্ধ করবেন না। নইলে condition worse হতে পারে।"},
            {"q": "খাবার消化不良 হলে ওষুধ সেবন করবো?", "a": "prescribed timing অনুযায়ী সেবন করুন। meal-related timing হলে খাবার পরিবর্তন করুন।"},
        ]
        if is_bn else
        [
            {"q": "What if I miss a dose?", "a": "If you miss a dose, skip it and take the next dose at the scheduled time. Do not double up."},
            {"q": "Can I stop taking medicine early?", "a": "Complete the full course unless your doctor advises otherwise. Stopping early may cause recurrence."},
            {"q": "Should I take medicine with food?", "a": "Follow the timing instructions on your prescription. Some medicines require empty stomach, others with meals."},
        ]
    )

    follow_up_guidance = (
        "Follow-up এ Doctor আপনার improvement assess করবেন, necessary tests order করবেন, এবং prescription update করবেন। "
        "Your health journey timeline ও current symptoms Doctor-কে দেখান।"
        if is_bn else
        "At follow-up, your doctor will assess improvement, order any needed tests, and adjust treatment. "
        "Bring your health journey timeline and note any new symptoms."
    )

    return {
        "overview": overview,
        "medicines_breakdown": medicines_breakdown,
        "diet_interactions": diet_interactions,
        "lifestyle_tips": lifestyle_tips,
        "warning_signs": warning_signs,
        "follow_up_guidance": follow_up_guidance,
        "faq": faq,
        "source": "local",
    }
