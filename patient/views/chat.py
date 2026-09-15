import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from accounts.models import Doctor
from carebridge.ai_services import GeminiAIService
from patient.models import ChatMessage, ChatSession
from patient.services import generate_patient_reply


def _get_patient(request):
    if not request.user.is_authenticated:
        return None
    return getattr(request.user, "patient_profile", None)


def _resolve_language(request, patient):
    lang = request.GET.get("lang") or request.POST.get("lang")
    if not lang:
        try:
            if request.body:
                lang = json.loads(request.body).get("lang")
        except (json.JSONDecodeError, AttributeError, Exception):
            pass
    lang = lang or request.session.get("site_lang") or (patient.preferred_language if patient else "en")
    return "bn" if lang == "bn" else "en"


def _get_active_ai_model():
    try:
        providers = GeminiAIService._get_db_providers()
        for p in providers:
            if p.is_available:
                return p.model_name or p.get_provider_display()
    except Exception:
        pass
    return "Gemini"


def _get_guest_qa():
    guest_qa = []
    try:
        from patient.services import GUEST_QA
        for key, qa in list(GUEST_QA.items())[:10]:
            guest_qa.append({
                "question_en": qa["en"].split("\n")[0].replace("**", "").strip(),
                "question_bn": qa["bn"].split("\n")[0].replace("**", "").strip(),
                "answer_en": qa["en"],
                "answer_bn": qa["bn"],
            })
    except Exception:
        pass
    return guest_qa


def _get_or_create_session(patient, session_id=None):
    if not patient:
        return None
    if session_id:
        try:
            return ChatSession.objects.filter(pk=session_id, patient=patient).first()
        except (ValueError, TypeError):
            pass
    session = ChatSession.objects.create(patient=patient, title="New Chat")
    first_msg = ChatMessage.objects.filter(patient=patient, session=session).order_by("created_at").first()
    if first_msg:
        session.title = first_msg.content[:50] or "New Chat"
        session.save(update_fields=["title", "updated_at"])
    return session


def chatbot(request):
    """Single-page chat endpoint supporting both GET and POST."""
    patient = _get_patient(request)
    lang = _resolve_language(request, patient)
    active_model = _get_active_ai_model()
    ai_available = GeminiAIService.is_ai_available()
    guest_qa = _get_guest_qa()

    chat_messages = []
    user_message = ""
    reply_text = ""

    if request.method == "POST":
        user_message = (request.POST.get("message") or "").strip()
        image_file = request.FILES.get("file") or request.FILES.get("image")
        session_id = request.POST.get("session_id")
        prescription_id = request.POST.get("prescription_id")

        if user_message or image_file:
            if patient:
                session = _get_or_create_session(patient, session_id)
                display_content = user_message or f"📎 [Attached File: {image_file.name}]"
                ChatMessage.objects.create(
                    patient=patient,
                    session=session,
                    role="user",
                    content=display_content,
                    language=lang,
                )
                try:
                    reply_text = generate_patient_reply(
                        user_message, language=lang, patient=patient, image_file=image_file, prescription_id=prescription_id
                    )
                except Exception:
                    reply_text = (
                        "দুঃখিত, এই মুহূর্তে এআই সেবায় সংযোগ করতে সমস্যা হচ্ছে। অনুগ্রহ করে কিছুক্ষণ পর আবার চেষ্টা করুন।"
                        if lang == "bn"
                        else "Sorry, we are experiencing temporary AI service limits. Please try again shortly."
                    )
                ChatMessage.objects.create(
                    patient=patient,
                    session=session,
                    role="assistant",
                    content=reply_text,
                    language=lang,
                )
                if session and session.title == "New Chat":
                    session.title = user_message[:50] or "New Chat"
                    session.save(update_fields=["title", "updated_at"])
            else:
                try:
                    reply_text = generate_patient_reply(
                        user_message, language=lang, patient=None, image_file=image_file, prescription_id=prescription_id
                    )
                except Exception:
                    reply_text = (
                        "দুঃখিত, এই মুহূর্তে এআই সেবায় সংযোগ করতে সমস্যা হচ্ছে। অনুগ্রহ করে কিছুক্ষণ পর আবার চেষ্টা করুন।"
                        if lang == "bn"
                        else "Sorry, we are experiencing temporary AI service limits. Please try again shortly."
                    )

    if patient:
        session = _get_or_create_session(patient)
        chat_messages = ChatMessage.objects.filter(patient=patient, session=session).order_by("created_at")

    return render(
        request,
        "patient/chatbot.html",
        {
            "patient": patient,
            "lang": lang,
            "site_lang": lang,
            "active_model": active_model,
            "ai_available": ai_available,
            "chat_messages": chat_messages,
            "guest_qa": guest_qa,
            "user_message": user_message,
            "reply_text": reply_text,
        },
    )


def chat_ui(request):
    patient = _get_patient(request)
    lang = _resolve_language(request, patient)
    active_model = _get_active_ai_model()
    ai_available = GeminiAIService.is_ai_available()
    session_id = request.GET.get("session_id") or request.GET.get("session")
    prescription_id = request.GET.get("prescription_id")

    sessions = ChatSession.objects.filter(patient=patient).order_by("-updated_at") if patient else []
    active_session = None
    if patient and sessions.exists():
        if session_id:
            active_session = sessions.filter(pk=session_id).first()
        if not active_session:
            active_session = sessions.first()

    chat_messages = []
    if patient and active_session:
        chat_messages = ChatMessage.objects.filter(patient=patient, session=active_session).order_by("created_at")

    suggested_doctors = Doctor.objects.filter(is_verified=True)[:3]

    return render(
        request,
        "patient/chat_ui.html",
        {
            "patient": patient,
            "lang": lang,
            "site_lang": lang,
            "active_model": active_model,
            "ai_available": ai_available,
            "sessions": sessions,
            "active_session": active_session,
            "current_session": active_session,
            "chat_messages": chat_messages,
            "prescription_id": prescription_id,
            "suggested_doctors": suggested_doctors,
        },
    )


@require_GET
def chat_api_history(request):
    patient = _get_patient(request)
    if not patient:
        return JsonResponse({"history": [], "messages": []})
    session_id = request.GET.get("session_id")
    session = _get_or_create_session(patient, session_id)

    if not session:
        return JsonResponse({"history": [], "messages": []})

    msgs = ChatMessage.objects.filter(patient=patient, session=session).order_by("created_at")
    data = [
        {
            "id": m.pk,
            "sender": m.role,
            "role": m.role,
            "content": m.content,
            "language": m.language,
            "created_at": m.created_at.strftime("%I:%M %p"),
        }
        for m in msgs
    ]
    return JsonResponse({"history": data, "messages": data, "session_id": session.pk, "title": session.title})


@require_POST
def chat_api_send(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError, Exception):
        body = {}

    user_msg = (body.get("message") or request.POST.get("message") or "").strip()
    session_id = body.get("session_id") or request.POST.get("session_id")
    prescription_id = body.get("prescription_id") or request.POST.get("prescription_id")
    image_file = request.FILES.get("file") or request.FILES.get("image")

    if not user_msg and not image_file:
        return JsonResponse({"error": "Message content or file is required."}, status=400)

    patient = _get_patient(request)
    lang = _resolve_language(request, patient)

    if not patient:
        try:
            reply_text = generate_patient_reply(
                user_msg, language=lang, patient=None, image_file=image_file, prescription_id=prescription_id
            )
        except Exception:
            reply_text = (
                "দুঃখিত, এই মুহূর্তে এআই সেবায় সংযোগ করতে সমস্যা হচ্ছে। অনুগ্রহ করে কিছুক্ষণ পর আবার চেষ্টা করুন।"
                if lang == "bn"
                else "Sorry, we are experiencing temporary AI service limits. Please try again shortly."
            )
        return JsonResponse(
            {
                "user_message": user_msg,
                "reply": reply_text,
                "bot_reply": reply_text,
                "session_id": None,
                "session_title": "Guest Chat",
                "message_id": None,
                "language": lang,
            }
        )

    session = _get_or_create_session(patient, session_id)

    display_content = user_msg
    if image_file and not display_content:
        display_content = f"📎 [Attached File: {image_file.name}]"

    ChatMessage.objects.create(
        patient=patient,
        session=session,
        role="user",
        content=display_content,
        language=lang,
    )

    try:
        reply_text = generate_patient_reply(
            user_msg, language=lang, patient=patient, image_file=image_file, prescription_id=prescription_id
        )
    except Exception:
        reply_text = (
            "দুঃখিত, এই মুহূর্তে এআই সেবায় সংযোগ করতে সমস্যা হচ্ছে। অনুগ্রহ করে কিছুক্ষণ পর আবার চেষ্টা করুন।"
            if lang == "bn"
            else "Sorry, we are experiencing temporary AI service limits. Please try again shortly."
        )

    bot_msg = ChatMessage.objects.create(
        patient=patient,
        session=session,
        role="assistant",
        content=reply_text,
        language=lang,
    )

    if session and session.title == "New Chat":
        session.title = user_msg[:50] or "New Chat"
        session.save(update_fields=["title", "updated_at"])

    return JsonResponse(
        {
            "user_message": user_msg,
            "reply": reply_text,
            "bot_reply": reply_text,
            "session_id": session.pk if session else None,
            "session_title": session.title if session else "Chat",
            "message_id": bot_msg.pk,
            "language": lang,
        }
    )


@require_POST
def chat_api_clear(request):
    patient = _get_patient(request)
    if patient:
        try:
            body = json.loads(request.body)
            session_id = body.get("session_id")
        except Exception:
            session_id = request.POST.get("session_id")

        if session_id:
            ChatSession.objects.filter(pk=session_id, patient=patient).delete()
        else:
            ChatSession.objects.filter(patient=patient).delete()

    return JsonResponse({"status": "cleared"})


@require_POST
def chat_api_translate(request):
    try:
        body = json.loads(request.body)
    except Exception:
        body = {}

    msg_id = body.get("message_id")
    text_content = body.get("text") or body.get("content")
    target_lang = body.get("target_lang", "bn")

    if msg_id:
        patient = _get_patient(request)
        if patient:
            msg = ChatMessage.objects.filter(pk=msg_id, patient=patient).first()
            if msg:
                text_content = msg.content

    if not text_content:
        return JsonResponse({"error": "No text provided to translate"}, status=400)

    try:
        translated = GeminiAIService.translate_text(text_content, target_lang=target_lang)
    except Exception:
        translated = text_content

    return JsonResponse({
        "translated_content": translated,
        "translated_text": translated,
        "target_lang": target_lang
    })


@require_GET
def chat_api_sessions(request):
    patient = _get_patient(request)
    if not patient:
        return JsonResponse({"sessions": []})
    sessions = ChatSession.objects.filter(patient=patient).order_by("-updated_at")
    data = [{"id": s.pk, "title": s.title, "updated_at": s.updated_at.strftime("%b %d, %I:%M %p")} for s in sessions]
    return JsonResponse({"sessions": data})


@require_POST
def chat_api_new_session(request):
    patient = _get_patient(request)
    if not patient:
        return JsonResponse({"session_id": None, "title": "Guest Chat"})
    session = ChatSession.objects.create(patient=patient, title="New Chat")
    return JsonResponse({"session_id": session.pk, "title": session.title})
