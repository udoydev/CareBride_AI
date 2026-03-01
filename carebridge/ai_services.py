import base64
import io
import json
import logging
import os
import re
from urllib import request as urllib_request, error as urllib_error
from PIL import Image
from django.conf import settings

logger = logging.getLogger(__name__)

FALLBACK_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

VISION_FALLBACK_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]


class GeminiAIService:
    """
    Unified AI Integration Service.
    Primary: Database-configured AI providers (admin-managed)
    Fallback: .env-configured Gemini/Groq keys
    Final fallback: Local keyword-based responses
    """

    @classmethod
    def _get_db_providers(cls):
        """Get active AI providers from database, ordered by priority."""
        try:
            from accounts.models import AIProvider
            return list(AIProvider.objects.filter(is_active=True).order_by("priority", "created_at"))
        except Exception:
            return []

    @classmethod
    def is_ai_available(cls):
        """Check if at least one AI provider is available (not rate-limited, has API key)."""
        db_providers = cls._get_db_providers()
        for provider in db_providers:
            if provider.is_available:
                return True

        gemini_key = cls.get_api_key()
        if gemini_key:
            return True

        groq_key = getattr(settings, "GROQ_API_KEY", "") or os.environ.get("GROQ_API_KEY", "")
        if groq_key:
            return True

        return False

    @classmethod
    def get_available_providers_info(cls):
        """Get info about available/unavailable providers for admin dashboard."""
        try:
            from accounts.models import AIProvider
            providers = list(AIProvider.objects.all().order_by("priority", "created_at"))
            available_count = sum(1 for p in providers if p.is_available)
            total_count = len(providers)
            has_env_fallback = bool(cls.get_api_key() or getattr(settings, "GROQ_API_KEY", "") or os.environ.get("GROQ_API_KEY", ""))
            return {
                "total": total_count,
                "available": available_count,
                "unavailable": total_count - available_count,
                "has_env_fallback": has_env_fallback,
                "all_unavailable": available_count == 0 and not has_env_fallback,
                "any_available": available_count > 0 or has_env_fallback,
            }
        except Exception:
            return {
                "total": 0,
                "available": 0,
                "unavailable": 0,
                "has_env_fallback": False,
                "all_unavailable": True,
                "any_available": False,
            }

    @classmethod
    def get_api_key(cls):
        return getattr(settings, "GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")

    @classmethod
    def get_client(cls):
        api_key = cls.get_api_key()
        if not api_key:
            return None
        try:
            from google import genai
            return genai.Client(api_key=api_key)
        except Exception as e:
            logger.error(f"Failed to initialize google.genai client: {e}")
            return None

    @classmethod
    def _call_openai_compatible(cls, provider, prompt, image_file=None):
        """Call OpenAI-compatible API (Groq, DeepSeek, OpenRouter, Custom, etc.)."""
        api_key = provider.api_key
        base_url = (provider.base_url or "").rstrip("/")
        model = provider.model_name

        DEFAULT_BASE_URLS = {
            "groq": "https://api.groq.com/openai/v1",
            "openai": "https://api.openai.com/v1",
            "deepseek": "https://api.deepseek.com/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "custom": "https://api.openai.com/v1",
        }

        if not base_url:
            base_url = DEFAULT_BASE_URLS.get(provider.provider, "https://api.openai.com/v1")

        url = f"{base_url}/chat/completions"

        messages = [{"role": "user", "content": prompt}]
        if image_file:
            messages.append({
                "role": "user",
                "content": "An image was attached for analysis. Please consider it in your response.",
            })

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 2048,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        if provider.provider == "openrouter":
            headers["HTTP-Referer"] = getattr(settings, "OPENROUTER_SITE_URL", "https://carebridge.ai")
            headers["X-OpenRouter-Title"] = getattr(settings, "OPENROUTER_SITE_TITLE", "CareBridge AI")

        try:
            req = urllib_request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=30) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                choices = res_data.get("choices") or []
                if choices:
                    text = choices[0].get("message", {}).get("content", "").strip()
                    if text:
                        provider.record_success()
                        return {"reply_text": text, "status": "success", "model": model}
        except Exception as err:
            provider.record_failure()
            logger.warning(f"Provider {provider.name} ({model}) failed: {err}")

        return None

    @classmethod
    def _call_gemini_sdk(cls, api_key, prompt, image_file=None):
        """Call Gemini via official SDK."""
        try:
            from google import genai
            client = genai.Client(api_key=api_key)

            contents = [prompt]
            if image_file:
                try:
                    if hasattr(image_file, "read"):
                        image_file.seek(0)
                        img = Image.open(image_file)
                        contents.append(img)
                except Exception as e:
                    logger.warning(f"Could not load image for Gemini SDK: {e}")

            models_to_try = VISION_FALLBACK_MODELS if image_file else FALLBACK_MODELS
            for model_name in models_to_try:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents,
                    )
                    if response and response.text:
                        return {"reply_text": response.text.strip(), "status": "success", "model": model_name}
                except Exception as e:
                    err_msg = str(e)
                    if "does not support image input" in err_msg or "image input" in err_msg:
                        logger.warning(f"Gemini model {model_name} does not support images, trying next vision model")
                        continue
                    logger.warning(f"Gemini SDK model {model_name} error: {e}")
                    continue
        except Exception as e:
            logger.error(f"Gemini SDK initialization failed: {e}")

        return None

    @classmethod
    def _call_gemini_rest(cls, api_key, prompt, image_file=None):
        """Call Gemini via REST API."""
        parts = [{"text": prompt}]
        if image_file:
            try:
                if hasattr(image_file, "read"):
                    image_file.seek(0)
                    img_bytes = image_file.read()
                elif isinstance(image_file, (bytes, bytearray)):
                    img_bytes = image_file
                else:
                    with open(image_file, "rb") as f:
                        img_bytes = f.read()
                mime = "image/jpeg"
                b64_data = base64.b64encode(img_bytes).decode("utf-8")
                parts.append({"inline_data": {"mime_type": mime, "data": b64_data}})
            except Exception as e:
                logger.warning(f"Could not encode image for REST: {e}")

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048}
        }

        models_to_try = VISION_FALLBACK_MODELS if image_file else FALLBACK_MODELS
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                req = urllib_request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib_request.urlopen(req, timeout=30) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    candidates = res_data.get("candidates") or []
                    if candidates:
                        text_parts = candidates[0].get("content", {}).get("parts") or []
                        if text_parts and text_parts[0].get("text"):
                            return {"reply_text": text_parts[0]["text"].strip(), "status": "success", "model": model}
            except Exception as err:
                err_msg = str(err)
                if "does not support image input" in err_msg or "image input" in err_msg:
                    logger.warning(f"Gemini REST model {model} does not support images, trying next vision model")
                    continue
                logger.warning(f"Gemini REST model {model} failed: {err}")
                continue

        return None

    @classmethod
    def _fallback_env_gemini(cls, prompt, image_file=None):
        """Try .env-configured Gemini key as fallback."""
        api_key = cls.get_api_key()
        if not api_key:
            return None

        res = cls._call_gemini_sdk(api_key, prompt, image_file)
        if res:
            return res
        return cls._call_gemini_rest(api_key, prompt, image_file)

    @classmethod
    def _fallback_env_groq(cls, prompt, image_file=None, preferred_language="bn"):
        """Try .env-configured Groq key as fallback."""
        api_key = getattr(settings, "GROQ_API_KEY", "") or os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            return None

        try:
            from accounts.models import AIProvider
            provider, _ = AIProvider.objects.get_or_create(
                provider="groq",
                defaults={
                    "name": "Env Groq Backup",
                    "api_key": api_key,
                    "model_name": "llama-3.3-70b-versatile",
                    "base_url": "https://api.groq.com/openai/v1",
                    "priority": 999,
                    "is_active": True,
                }
            )
            return cls._call_openai_compatible(provider, prompt, image_file)
        except Exception:
            pass

        messages = [{"role": "user", "content": prompt}]
        if image_file:
            messages.append({"role": "user", "content": "Image attached for analysis."})
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 2048,
        }
        url = "https://api.groq.com/openai/v1/chat/completions"
        try:
            req = urllib_request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=30) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                choices = res_data.get("choices") or []
                if choices:
                    text = choices[0].get("message", {}).get("content", "").strip()
                    if text:
                        return {"reply_text": text, "status": "success", "model": "groq-llama-3.3-70b"}
        except Exception as err:
            logger.warning(f"Env Groq fallback failed: {err}")

        return None

    @classmethod
    def generate_content_via_rest(cls, prompt, image_file=None):
        """Legacy REST fallback using .env Gemini key."""
        api_key = cls.get_api_key()
        if not api_key:
            return None
        return cls._call_gemini_rest(api_key, prompt, image_file)

    @classmethod
    def generate_content_via_groq(cls, prompt, image_file=None, preferred_language="bn"):
        """Legacy Groq fallback using .env key."""
        return cls._fallback_env_groq(prompt, image_file, preferred_language)

    @classmethod
    def generate_contextual_fallback(cls, query, lang="bn"):
        q = (query or "").lower()
        is_bn = lang == "bn"

        if any(w in q for w in ["ব্যথা", "জ্বর", "মাথা", "headache", "fever"]):
            return (
                "🤒 জ্বর ও মাথাব্যথা সংক্রান্ত প্রাথমিক পরামর্শ:\n"
                "• প্রচুর পানি ও স্যালাইন পান করুন এবং পর্যাপ্ত বিশ্রাম নিন।\n"
                "• মাথা ঠান্ডা পানিতে ভিজিয়ে মুছে দিতে পারেন।\n"
                "• জ্বর ১০২°F এর বেশি হলে বা ৩ দিনের বেশি থাকলে দ্রুত ডাক্তারের পরামর্শ নিন।"
                if is_bn else
                "🤒 Relief Advice for Fever & Headache:\n"
                "• Drink plenty of water and rest comfortably.\n"
                "• Use lukewarm water sponge to lower fever.\n"
                "• Consult a physician if fever exceeds 102°F or persists for more than 3 days."
            )
        elif any(w in q for w in ["রক্তচাপ", "bp", "blood pressure", "হাই প্রেসার"]):
            return (
                "❤️ উচ্চ রক্তচাপ (High BP) নিয়ন্ত্রণের নিয়ম:\n"
                "• খাবারে কাঁচা লবণ পুরোপুরি বর্জন করুন।\n"
                "• চর্বিযুক্ত খাবার এড়িয়ে চলুন এবং প্রতিদিন ৩০ মিনিট হাঁটুন।\n"
                "• ডাক্তারের প্রেসক্রিপশন অনুযায়ী নিয়মিত ওষুধ সেবন করুন।"
                if is_bn else
                "❤️ High Blood Pressure Management Tips:\n"
                "• Strictly reduce raw salt intake in food.\n"
                "• Avoid oily foods and engage in 30 minutes of daily light exercise.\n"
                "• Continue prescribed hypertension medication regularly."
            )
        elif any(w in q for w in ["ডায়াবেটিস", "সুগার", "diabetes", "sugar"]):
            return (
                "🩸 ডায়াবেটিস সচেতনতা ও পরামর্শ:\n"
                "• চিনিযুক্ত পানীয় ও মিষ্টি বর্জন করুন।\n"
                "• খালি পেটে রক্তে শর্করা পরিমাপ করুন এবং নিয়মিত ডায়াবেটিস ডায়রিতে লিখে রাখুন।\n"
                "• ডাক্তারের পরামর্শ অনুযায়ী ইনসুলিন বা ট্যাবলেট গ্রহণ করুন।"
                if is_bn else
                "🩸 Diabetes Care Guidelines:\n"
                "• Avoid sugary beverages and refined carbohydrates.\n"
                "• Monitor fasting blood sugar levels regularly.\n"
                "• Follow prescribed medication schedule and diet chart."
            )
        else:
            return (
                "👋 কেয়ারব্রীজ চিকিৎসা পরামর্শ:\n"
                "• আপনার শারীরিক সুস্থতার জন্য নিয়মিত ওষুধ সময়মতো সেবন করুন।\n"
                "• পর্যাপ্ত ঘুম, পুষ্টিকর খাবার এবং প্রচুর পানি পান করা আবশ্যক।\n"
                "• যেকোনো জটিলতা অনুভব করলে CareBridge অ্যাপ থেকে দ্রুত ডাক্তারের অ্যাপয়েন্টমেন্ট নিন।"
                if is_bn else
                "👋 CareBridge Health Guidelines:\n"
                "• Take all prescribed medications on schedule.\n"
                "• Maintain balanced diet, hydrate well, and get adequate rest.\n"
                "• If symptoms worsen, schedule an appointment with a specialist via CareBridge."
            )

    @classmethod
    def chat_with_patient(cls, user_message, conversation_history=None, preferred_language="bn"):
        return cls.chat_with_patient_vision(
            user_message=user_message,
            image_file=None,
            conversation_history=conversation_history,
            preferred_language=preferred_language,
        )
    @classmethod
    def chat_with_patient_vision(cls, user_message, image_file=None, conversation_history=None, preferred_language="bn"):
        lang_instruction = "Respond fluently, naturally, and warmly in Bangladeshi Bangla (বাংলা)." if preferred_language == "bn" else "Respond fluently, clearly, and warmly in English."

        base_prompt = (
            "System Instruction: You are CareBridge AI (কেয়ারব্রীজ এআই), an expert medical AI assistant for patients in Bangladesh. "
            f"{lang_instruction} "
            "Always include a brief friendly disclaimer that AI advice is for informational purposes.\n\n"
            f"User Message: {user_message or 'মেডিকেল তথ্য বিশ্লেষণ করুন।'}"
        )

        vision_prompt = base_prompt
        if image_file:
            try:
                if hasattr(image_file, "read"):
                    image_file.seek(0)
                    img = Image.open(image_file)
                    vision_prompt += f"\n\n[Note: User uploaded an image file '{getattr(image_file, 'name', 'document')}'. If you can see it, analyze it thoroughly. If not, respond based on text only and inform the user.]"
            except Exception as e:
                logger.warning(f"Could not load image attachment for vision prompt: {e}")
                vision_prompt += f"\n\n[Note: User attempted to upload a document/image, but it could not be processed.]"

        # 1. Try database-configured providers first
        db_providers = cls._get_db_providers()
        for provider in db_providers:
            if not provider.is_available:
                continue
            if provider.provider == "gemini":
                api_key = provider.api_key
                res = cls._call_gemini_sdk(api_key, vision_prompt, image_file)
                if not res:
                    res = cls._call_gemini_rest(api_key, vision_prompt, image_file)
                if res:
                    return res
            else:
                res = cls._call_openai_compatible(provider, base_prompt, image_file=None)
                if res:
                    return res

        # 2. Try .env-configured Gemini
        res = cls._fallback_env_gemini(vision_prompt, image_file)
        if res:
            return res

        # 3. Try .env-configured Groq
        res = cls._fallback_env_groq(base_prompt, image_file=None, preferred_language=preferred_language)
        if res:
            return res

        fallback_text = cls.generate_contextual_fallback(user_message, preferred_language)
        return {"reply_text": fallback_text, "status": "fallback"}

    @classmethod
    def generate_text(cls, prompt, language="bn"):
        res = cls.chat_with_patient(user_message=prompt, preferred_language=language)
        return res.get("reply_text") or cls.generate_contextual_fallback(prompt, language)

    @classmethod
    def scan_prescription_image(cls, image_file_path_or_bytes):
        db_providers = cls._get_db_providers()

        try:
            img = Image.open(image_file_path_or_bytes)
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to load image: {e}",
                "data": cls._empty_ocr_result(),
            }

        prompt = (
            "You are an expert medical OCR scanner for handwritten and printed doctor prescriptions in Bangladesh. "
            "Inspect this prescription image. Extract all details into a clean valid JSON object with NO markdown wrappers:\n"
            "{\n"
            '  "doctor_name": "Dr. Full Name or Unknown",\n'
            '  "hospital_or_clinic": "Hospital Name or Unknown",\n'
            '  "patient_name": "Patient Name or Unknown",\n'
            '  "medicines": [\n'
            "    {\n"
            '      "brand_name": "Napa",\n'
            '      "generic_name": "Paracetamol",\n'
            '      "dosage": "500mg",\n'
            '      "frequency_per_day": 3,\n'
            '      "timing_relation": "after_meal",\n'
            '      "duration_days": 5,\n'
            '      "instructions": "1 tablet after meals"\n'
            "    }\n"
            "  ],\n"
            '  "follow_up_days": 7,\n'
            '  "notes": "General advice"\n'
            "}"
        )

        # Try DB providers
        for provider in db_providers:
            if not provider.is_available:
                continue
            if provider.provider == "gemini":
                api_key = provider.api_key
                try:
                    from google import genai
                    client = genai.Client(api_key=api_key)
                    response = client.models.generate_content(
                        model=provider.model_name,
                        contents=[prompt, img],
                    )
                    if response and response.text:
                        raw_text = response.text.strip()
                        clean_json_str = raw_text.replace("```json", "").replace("```", "").strip()
                        parsed_data = json.loads(clean_json_str)
                        provider.record_success()
                        return {
                            "success": True,
                            "raw_text": raw_text,
                            "data": parsed_data,
                            "model": provider.model_name,
                        }
                except Exception as e:
                    provider.record_failure()
                    logger.warning(f"DB Provider {provider.name} OCR failed: {e}")
                    continue
            else:
                res = cls._call_openai_compatible(provider, prompt)
                if res:
                    return {
                        "success": True,
                        "raw_text": res["reply_text"],
                        "data": {"notes": res["reply_text"]},
                        "model": provider.model_name,
                    }

        # Fallback to .env Gemini
        api_key = cls.get_api_key()
        if api_key:
            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                for model_name in FALLBACK_MODELS:
                    try:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=[prompt, img],
                        )
                        if response and response.text:
                            raw_text = response.text.strip()
                            clean_json_str = raw_text.replace("```json", "").replace("```", "").strip()
                            parsed_data = json.loads(clean_json_str)
                            return {
                                "success": True,
                                "raw_text": raw_text,
                                "data": parsed_data,
                                "model": model_name,
                            }
                    except Exception:
                        continue
            except Exception:
                pass

        return {
            "success": False,
            "error": "OCR failed across all available providers.",
            "data": cls._empty_ocr_result(),
        }

    @classmethod
    def generate_clinical_summary(cls, patient_name, history_text, metrics_summary=""):
        db_providers = cls._get_db_providers()
        prompt = (
            f"You are a clinical AI assistant for doctors in Bangladesh. Generate a concise 3-bullet point "
            f"clinical summary and drug interaction check for doctor chamber review in Bangla:\n"
            f"Patient Name: {patient_name}\n"
            f"Medical History: {history_text}\n"
            f"Health Vitals: {metrics_summary}\n"
        )

        for provider in db_providers:
            if not provider.is_available:
                continue
            if provider.provider == "gemini":
                api_key = provider.api_key
                res = cls._call_gemini_sdk(api_key, prompt)
                if res:
                    return res["reply_text"]
            else:
                res = cls._call_openai_compatible(provider, prompt)
                if res:
                    return res["reply_text"]

        fallback_briefing = (
            f"📋 Clinical Briefing for {patient_name}:\n"
            f"• Patient History: {history_text}\n"
            f"• Current Vitals: {metrics_summary}\n"
            f"• Note: Standard record logged."
        )
        return fallback_briefing

    @staticmethod
    def _empty_ocr_result():
        return {
            "doctor_name": "Unspecified Doctor",
            "hospital_or_clinic": "Chamber / Clinic",
            "patient_name": "Patient",
            "medicines": [],
            "follow_up_days": 7,
            "notes": "Scanned document recorded.",
        }
