import io
import json
import logging
import os
import re

try:
    import requests
except ImportError:  # pragma: no cover - fallback for minimal environments
    requests = None

try:
    from gtts import gTTS
except ImportError:  # pragma: no cover - fallback for minimal environments
    gTTS = None

from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from .ai_services import GeminiAIService

logger = logging.getLogger(__name__)
SONIOX_VOICE_SERVICE_URL = os.environ.get("SONIOX_VOICE_SERVICE_URL", "http://localhost:5000")

def clean_text_for_speech(text, lang="bn"):
    """
    Strips all markdown formatting, symbols, colons, quotes, and emojis.
    Converts English terms in Bangla text into pure native Bangla phonetics
    so Google TTS pronounces fluent, natural, crystal-clear Bangla speech.
    """
    if not text:
        return ""

    cleaned = str(text)

    # Strip markdown headers, bold, italics, links, brackets
    cleaned = re.sub(r'\*\*(.*?)\*\*', r'\1', cleaned)
    cleaned = re.sub(r'\*(.*?)\*', r'\1', cleaned)
    cleaned = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', cleaned)
    cleaned = re.sub(r'https?:\/\/\S+', '', cleaned)
    cleaned = re.sub(r'<[^>]*>', ' ', cleaned)
    cleaned = re.sub(r'[\*\#\_\~`\•\-\>\🚨\💡\❤️\🤒\🩸\🤖\⚡\🎙️\🌐\📋\🗣️\📎\✅\ℹ️\💊\👨‍⚕️\📅]', ' ', cleaned)
    cleaned = re.sub(r'["\'\(\)\{\}\[\]\:\;\,]', ' ', cleaned)

    if lang == "bn":
        # Extended phonetic transliteration map for flawless Bangla TTS pronunciation
        phonetic_map = {
            r'\bCareBridge AI\b': 'কেয়ারব্রিজ এআই',
            r'\bCareBridge\b': 'কেয়ারব্রিজ',
            r'\bAI\b': 'এআই',
            r'\bHigh BP\b': 'উচ্চ রক্তচাপ',
            r'\bBP\b': 'রক্তচাপ',
            r'\bORS\b': 'স্যালইন',
            r'\bDoctor\b': 'ডাক্তার',
            r'\bHospital\b': 'হাসপাতাল',
            r'\bNapa\b': 'নাপা',
            r'\bAce\b': 'অ্যেস',
            r'\bParacetamol\b': 'প্যারাসিটামল',
            r'\bOmeprazole\b': 'অমিপ্রাজল',
            r'\bSeclo\b': 'সেক্লো',
            r'\bMetformin\b': 'মেটফরমিন',
            r'\bInsulin\b': 'ইনসুলিন',
            r'\bAmlodipine\b': 'অ্যামলোডিপিন',
            r'\bDiabetes\b': 'ডায়াবেটিস',
            r'\bHypertension\b': 'উচ্চ রক্তচাপ',
            r'\bGastritis\b': 'গ্যাস্ট্রিক',
            r'\bAcidity\b': 'এসিডিটি',
            r'\bMigraine\b': 'মাইগ্রেন',
            r'\bDengue\b': 'ডেঙ্গু',
            r'\bCBC\b': 'সিবিসি',
            r'\bNS1\b': 'এনএস১',
            r'\bICU\b': 'আইসিইউ',
            r'\b999\b': 'নাইন নাইন নাইন',
        }
        for pattern, replacement in phonetic_map.items():
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def voice_chatbot_view(request):
    """
    Renders the Carebridge Soniox Voice Chatbot & Explainer interface.
    """
    context = {
        "soniox_voice_port": os.environ.get("SONIOX_VOICE_PORT", 5000),
        "ws_url": os.environ.get("SONIOX_WS_URL", "ws://localhost:5000/ws/voice"),
    }
    return render(request, "voice_chatbot.html", context)


def voice_tts_stream_api(request):
    """
    Official Google Text-to-Speech API Endpoint for Bangla (bn) & English (en).
    Generates official Google Audio MP3 streams directly for HTML5 Audio player.
    """
    text = request.GET.get("text") or request.POST.get("text") or ""
    lang = request.GET.get("lang") or request.POST.get("lang") or "bn"

    google_lang = "en" if lang == "en" else "bn"
    cleaned_text = clean_text_for_speech(text, lang=google_lang)
    if not cleaned_text:
        return HttpResponse(b"", content_type="audio/mpeg", status=400)

    short_text = cleaned_text[:220]

    if gTTS is None:
        logger.warning("gTTS is unavailable; returning empty audio response.")
        return HttpResponse(b"", content_type="audio/mpeg", status=502)

    try:
        tts = gTTS(text=short_text, lang=google_lang, slow=False)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return HttpResponse(fp.read(), content_type="audio/mpeg")
    except Exception as e:
        logger.error(f"Official Google TTS API error: {e}")

    return HttpResponse(b"", content_type="audio/mpeg", status=502)


@csrf_exempt
def voice_stt_demo_api(request):
    """
    API view to trigger Soniox real-time STT demo with bilingual translation.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    if requests is None:
        return JsonResponse({"success": False, "error": "The requests package is unavailable in this environment."}, status=503)

    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
        audio_url = data.get("audio_url", "https://soniox.com/media/examples/coffee_shop.mp3")

        response = requests.post(
            f"{SONIOX_VOICE_SERVICE_URL}/api/voice/demo-transcribe",
            json={"audio_url": audio_url},
            timeout=30
        )
        return JsonResponse(response.json(), status=response.status_code)
    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": f"Failed to communicate with Soniox Voice Service: {str(e)}",
            "hint": "Ensure 'npm start' in voice_service/ is running on port 5000."
        }, status=503)


@csrf_exempt
def voice_explainer_api(request):
    """
    Voice Explainer API: Accepts spoken or written medical topics,
    processes with Gemini AI, and formats clean response for speech synthesis.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
        query = data.get("query", "")
        language = data.get("language", "bn")

        q = (query or "").lower().strip()
        is_bn = language == "bn"

        # Dynamic medical topic detection for accurate, structured responses
        topic_prompts = {
            "fever": {
                "keywords_bn": ["জ্বর", "গরম", "তাপ", "ডেঙ্গু", "নাপা", "অ্যেস", "paracetamol"],
                "keywords_en": ["fever", "temperature", "dengue", "napa", "ace", "paracetamol", "hot"],
                "bn": (
                    "জ্বরের প্রাথমিক পরিচিতি: জ্বর সাধারণত শরীরের প্রতিরোধ不倒 System চ্যালেঞ্জের প্রতিক্রিয়া। "
                    "প্যারাসিটামল (নাপা/অ্যেস ৫০০মি.গ্রা.) ডাক্তারের পরামর্শ অনুযায়ী সেবন করুন। "
                    "ORS সেবন করুন, পর্যাপ্ত বিশ্রাম নিন। "
                    "সতর্কতা: ৩ দিনের বেশি জ্বর থাকলে বা গায়ে লাল র‍্যাশ দেখা দিলে CBC ও Dengue NS1 পরীক্ষা করান।"
                ),
                "en": (
                    "Fever is usually the body's immune response to infection. "
                    "Key steps: take paracetamol (Napa/Ace 500mg) as advised, stay hydrated with ORS, and rest. "
                    "Warning: if fever persists beyond 3 days or a rash appears, get a CBC and Dengue NS1 test promptly."
                ),
            },
            "bp": {
                "keywords_bn": ["রক্তচাপ", "প্রেসার", "উচ্চ", "হাই", "অ্যামলোডিপিন", "bp", "pressure"],
                "keywords_en": ["blood pressure", "bp", "hypertension", "pressure", "high", "amlodipine"],
                "bn": (
                    "উচ্চ রক্তচাপ নিয়ন্ত্রণের নিয়ম: কাঁচা লবণ সম্পূর্ণ বর্জন করুন, প্রতিদিন ৭-৮ ঘণ্টা ঘুমান, "
                    "সপ্তাহে ১-২ বার রক্তচাপ মেপে লিখে রাখুন। "
                    "ওষুধ: অ্যামলোডিপিন বা অন্যান্য ব্লড প্রেসার মেডিসিন ডাক্তারের পরামর্শে সেবন করুন। "
                    "জরুরি: তীব্র বুকে ব্যথা বা শ্বাসকষ্ট হলে অবিলম্বে হাসপাতালে যান।"
                ),
                "en": (
                    "High blood pressure management: eliminate raw salt, sleep 7-8 hours nightly, "
                    "track BP 1-2 times weekly. "
                    "Medication: Amlodipine or other BP meds as prescribed. "
                    "Emergency: chest pain or breathlessness needs immediate hospital care."
                ),
            },
            "diabetes": {
                "keywords_bn": ["ডায়াবেটিস", "চিনি", "শর্করা", "মেটফরমিন", "ইনসুলিন", "sugar", "diabetes"],
                "keywords_en": ["diabetes", "sugar", "glucose", "metformin", "insulin", "blood sugar"],
                "bn": (
                    "ডায়াবেটিস নিয়ন্ত্রণ: চিনি ও মিষ্টি এড়িয়ে চলুন, শাকসবজি ও ফাইবার বেশি খান, "
                    "প্রতিদিন ৩০ মিনিট হাঁটান। "
                    "রক্তে শর্করা পরিমাপ: fasting ও 2ABF পরীক্ষা নিয়মিত করুন। "
                    "ওষুধ: মেটফরমিন বা ইনসুলিন ডাক্তারের পরামর্শে সেবন করুন।"
                ),
                "en": (
                    "Diabetes management: avoid sugar and sweets, eat more vegetables and fiber, walk 30 minutes daily. "
                    "Monitoring: check fasting and 2-hour postprandial blood sugar regularly. "
                    "Medication: Metformin or insulin as prescribed by your doctor."
                ),
            },
            "gastric": {
                "keywords_bn": ["গ্যাস্ট্রিক", "এসিডিটি", "বুক জ্বালা", "গ্যাস", "পাকস্থলী", "অমিপ্রাজল", "সেক্লো", "gastric", "acidity"],
                "keywords_en": ["gastric", "acidity", "stomach", "acid", "heartburn", "omeprazole", "seclo"],
                "bn": (
                    "গ্যাস্ট্রিক ও বুক জ্বালাপোড়া: তৈলাক্ত ও ভাজাভুজি খাবার এড়িয়ে চলুন, সময়মতো খাবার খান, "
                    "প্রতিদিন ২.৫-৩ লিটার পানি পান করুন। "
                    "ওষুধ: অমিপ্রাজল (সেক্লো/সার্জেল) সকালে খালি পেটে সেবন করুন। "
                    "জরুরি: তীব্র পেট ব্যথা হলে গ্যাস্ট্রোএন্টারোলজিস্ট দেখান।"
                ),
                "en": (
                    "Gastritis and acidity: avoid oily and fried foods, eat on schedule, drink 2.5-3 liters of water daily. "
                    "Medication: Omeprazole (Seclo/Sergel) before breakfast. "
                    "See a gastroenterologist if severe stomach pain persists."
                ),
            },
            "headache": {
                "keywords_bn": ["মাথা ব্যথা", "মাথা ঘোরে", "মাইগ্রেন", "headache", "migraine", "napa"],
                "keywords_en": ["headache", "migraine", "head pain", "napa"],
                "bn": (
                    "মাথা ব্যথার প্রাথমিক ব্যবস্থা: পর্যাপ্ত পানি পান করুন, অন্ধকার ঘরে বিশ্রাম নিন, "
                    "প্যারাসিটামল (নাপা ৫০০মি.গ্রা.) সেবন করতে পারেন। "
                    "জরুরি: হঠাৎ প্রচন্ড মাথা ব্যথা, চোখ ঝাপসা বা সাথে বমি থাকলে নিউরোলজিস্ট দেখান।"
                ),
                "en": (
                    "Headache first aid: stay hydrated, rest in a dark quiet room, take paracetamol (Napa 500mg). "
                    "Urgent: sudden severe headache, blurred vision, or vomiting requires a neurologist visit."
                ),
            },
            "cough": {
                "keywords_bn": ["কাশি", "সর্দি", "গলা ব্যথা", "ঠান্ডা", "কফ", "হাঁচি", "fexo", "cough", "cold"],
                "keywords_en": ["cough", "cold", "sore throat", "flu", "fexo", "cough syrup"],
                "bn": (
                    "কাশি ও সর্দির প্রাথমিক ব্যবস্থা: গরম পানিতে লবণ দিয়ে গার্গল করুন, তুলসী leaves ও মধু চা পান করুন, "
                    "গরম পানির ভাপ নিন। "
                    "ওষুধ: অ্যান্টিহিস্টামিন (ফেক্সো/ফেক্সোফেনাদাইন) ডাক্তারের পরামর্শে সেবন করুন। "
                    "সতর্কতা: ৭ দিনের বেশি কাশি থাকলে বা রক্ত acompañed থাকলে বক্ষব্যাধি বিশেষজ্ঞ দেখান।"
                ),
                "en": (
                    "Cough and cold care: saltwater gargle, ginger-honey tea, steam inhalation. "
                    "Medication: antihistamines like Fexofenadine (Fexo) as advised. "
                    "Warning: cough beyond 7 days or blood-tinged phlegm needs a chest specialist."
                ),
            },
            "emergency": {
                "keywords_bn": ["জরুরি", "হার্ট অ্যাটাক", "অচেতন", "শ্বাসকষ্ট", "emergency", "999", "icu"],
                "keywords_en": ["emergency", "heart attack", "unconscious", "breathless", "999", "icu"],
                "bn": (
                    "জরুরি সতর্কতা: তীব্র বুকে ব্যথা, শ্বাসকষ্ট, অজ্ঞান বা রক্তপাত হলে "
                    "বিলম্ব না করে ৯৯৯-এ কল করুন বা নিকটস্থ হাসপাতালের ইমার্জেন্সি বিভাগে যান। "
                    "অনলাইন পরামর্শের জন্য অপেক্ষা করবেন না।"
                ),
                "en": (
                    "EMERGENCY: severe chest pain, breathlessness, unconsciousness, or heavy bleeding — "
                    "call 999 or go to the nearest emergency department immediately. "
                    "Do not wait for online advice in critical conditions."
                ),
            },
        }

        # Detect topic
        matched_topic = None
        for topic_id, topic in topic_prompts.items():
            if any(w in q for w in topic.get("keywords_bn", [])) or any(w in q for w in topic.get("keywords_en", [])):
                matched_topic = topic
                break

        if matched_topic:
            reply_text = matched_topic["bn"] if is_bn else matched_topic["en"]
        else:
            # Dynamic AI response for unmatched queries
            if is_bn:
                system_msg = (
                    "আপনি কেয়ারব্রিজ এআই — বাংলাদেশি টেলিমেডিসিন সহকারী। "
                    f"প্রশ্ন: {query}\n\n"
                    "নিচের নিয়মে স Haлítulosহ wartościuminous উত্তর দিন:\n"
                    "১. প্রাথমিক পরামর্শ (২-৩ পয়েন্ট)\n"
                    "২. সাধারণ ওষুধের নাম ও সেবনের নিয়ম (ডাক্তারের পরামর্শে)\n"
                    "৩. পুষ্টি ও জীবনের ব্যায়াম\n"
                    "৪. কখন ডাক্তারের দেখার জরুরি — সতর্কতা\n\n"
                    "সহজ বাংলায় লিখুন,_button❌ markdown ব্যবহার করবেন না।"
                )
            else:
                system_msg = (
                    "You are CareBridge AI — a Bangladeshi telemedicine assistant. "
                    f"Question: {query}\n\n"
                    "Answer with:\n"
                    "1. Primary advice (2-3 bullet points)\n"
                    "2. Common OTC medication names and how to take them (under medical advice)\n"
                    "3. Diet and lifestyle tips\n"
                    "4. Red flags — when to see a doctor urgently\n\n"
                    "Write in simple English, NO markdown formatting."
                )

            ai_response = GeminiAIService.chat_with_patient(
                user_message=system_msg,
                preferred_language=language
            )
            reply_text = ai_response.get("reply_text", "")

        speech_text = clean_text_for_speech(reply_text, lang=language)

        return JsonResponse({
            "success": True,
            "query": query,
            "language": language,
            "explanation": reply_text,
            "speech_text": speech_text,
            "status": "success",
        })
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)
