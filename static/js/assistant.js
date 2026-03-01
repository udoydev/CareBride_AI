/**
 * Carebridge AI Official Google Voice Assistant & Audio Player (v6.0.0)
 */
(function () {
  "use strict";

  const cfg = window.CAREBRIDGE_ASSISTANT || {};
  let isOpen = false;
  let isSending = false;
  let historyLoaded = false;
  let currentLang = cfg.lang || "bn";
  let attachedFile = null;
  let isListening = false;
  let activeRecognition = null;
  let lastAssistantReply = "";

  /**
   * Official Google Voice Audio Engine with fallback to SpeechSynthesis
   */
  class CarebridgeVoiceEngine {
    constructor() {
      this.currentAudio = null;
      this.isEnabled = true;
      this.currentText = "";
      this.currentLang = "bn";
      this.isPlaying = false;
    }

    cleanText(raw) {
      if (!raw) return "";
      return String(raw)
        .replace(/\*\*(.*?)\*\*/g, "$1")
        .replace(/\*(.*?)\*/g, "$1")
        .replace(/\[(.*?)\]\(.*?\)/g, "$1")
        .replace(/[\*\#\_\~`\•\-\>\🚨\💡\❤️\🤒\🩸\🤖\⚡\🎙️\🌐\📋\🗣️\📎\✅\ℹ️\💊\👨‍⚕️]/g, " ")
        .replace(/https?:\/\/\S+/g, "")
        .replace(/<[^>]*>/g, " ")
        .replace(/\d+\./g, " ")
        .replace(/["\'\(\)\{\}\[\]\:\;\,]/g, " ")
        .replace(/\s+/g, " ")
        .trim();
    }

    fallbackSpeak(text, lang) {
      if (!window.speechSynthesis) return;
      window.speechSynthesis.cancel();
      const cleaned = this.cleanText(text);
      if (!cleaned) return;
      const utterance = new SpeechSynthesisUtterance(cleaned);
      utterance.lang = lang === "en" ? "en-US" : "bn-BD";
      utterance.rate = lang === "en" ? 1.0 : 0.9;
      utterance.pitch = 1.0;
      window.speechSynthesis.speak(utterance);
    }

    play(text, lang = "bn", force = false) {
      if (!force && !this.isEnabled) {
        this.stop();
        return;
      }

      this.stop();
      this.currentText = text || this.currentText;
      this.currentLang = lang || currentLang;

      const cleaned = this.cleanText(this.currentText);
      if (!cleaned) return;

      const proxyUrl = `/api/voice/tts/?text=${encodeURIComponent(cleaned)}&lang=${encodeURIComponent(this.currentLang)}&t=${Date.now()}`;

      const audio = new Audio(proxyUrl);
      this.currentAudio = audio;

      audio.onplay = () => {
        this.isPlaying = true;
        this.updateStateUI();
      };

      audio.onended = () => {
        this.isPlaying = false;
        this.updateStateUI();
      };

      audio.onerror = () => {
        this.isPlaying = false;
        this.updateStateUI();
        this.fallbackSpeak(cleaned, this.currentLang);
      };

      audio.play().then(() => {
        this.isPlaying = true;
        this.updateStateUI();
      }).catch((e) => {
        console.warn("Audio play error, using fallback:", e);
        this.fallbackSpeak(cleaned, this.currentLang);
      });
    }

    stop() {
      if (this.currentAudio) {
        this.currentAudio.pause();
        this.currentAudio.currentTime = 0;
        this.currentAudio = null;
      }
      if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
      this.isPlaying = false;
      this.updateStateUI();
    }

    restart() {
      this.stop();
      if (this.currentText) {
        this.play(this.currentText, this.currentLang, true);
      }
    }

    updateStateUI() {
      const voiceStateText = document.getElementById("assistantVoiceState");
      if (voiceStateText) {
        if (!this.isEnabled) {
          voiceStateText.textContent = "OFF";
          voiceStateText.className = "font-bold text-rose-500 dark:text-rose-400";
        } else if (this.isPlaying) {
          voiceStateText.textContent = "PLAYING (Google AI)";
          voiceStateText.className = "font-bold text-teal-600 dark:text-teal-400 animate-pulse";
        } else {
          voiceStateText.textContent = "ON";
          voiceStateText.className = "font-bold text-emerald-600 dark:text-emerald-400";
        }
      }
    }
  }

  const voiceEngine = new CarebridgeVoiceEngine();

  // Voice Control Actions
  function setVoiceOn() {
    voiceEngine.isEnabled = true;
    voiceEngine.updateStateUI();
    if (lastAssistantReply) {
      voiceEngine.play(lastAssistantReply, currentLang, true);
    }
  }

  function setVoiceOff() {
    voiceEngine.isEnabled = false;
    voiceEngine.stop();
  }

  function setVoiceRestart() {
    voiceEngine.isEnabled = true;
    voiceEngine.updateStateUI();
    voiceEngine.restart();
  }

  // Global Event Delegation for ON, OFF, RESTART buttons
  document.addEventListener("click", function (e) {
    const btnOn = e.target.closest("#btnVoiceOn");
    if (btnOn) {
      e.preventDefault();
      setVoiceOn();
      return;
    }
    const btnOff = e.target.closest("#btnVoiceOff");
    if (btnOff) {
      e.preventDefault();
      setVoiceOff();
      return;
    }
    const btnRestart = e.target.closest("#btnVoiceRestart");
    if (btnRestart) {
      e.preventDefault();
      setVoiceRestart();
      return;
    }
  });

  window.CAREBRIDGE_VOICE_CTRL = function (action) {
    if (action === "on") setVoiceOn();
    else if (action === "off") setVoiceOff();
    else if (action === "restart") setVoiceRestart();
  };

  window.CareBridgeSpeech = {
    speakText: function (text, lang) {
      if (!text) return;
      voiceEngine.stop();
      voiceEngine.currentText = text;
      voiceEngine.currentLang = lang || currentLang;
      voiceEngine.play(text, lang || currentLang, true);
    },
    stop: function () {
      voiceEngine.stop();
    },
  };

  function getSpeechApi() {
    return window.SpeechRecognition || window.webkitSpeechRecognition || null;
  }

  function getSpeechLang(lang) {
    return (lang || currentLang) === "en" ? "en-US" : "bn-BD";
  }

  function setPanelOpen(open) {
    isOpen = open;
    const panel = document.getElementById("assistantPanel");
    const inputEl = document.getElementById("assistantInput");
    if (!panel) return;

    panel.setAttribute("aria-hidden", String(!open));
    panel.classList.toggle("pointer-events-none", !open);
    panel.classList.toggle("opacity-0", !open);
    panel.classList.toggle("scale-95", !open);
    panel.classList.toggle("opacity-100", open);
    panel.classList.toggle("scale-100", open);

    if (open && !historyLoaded) {
      loadHistory();
    }
    if (open) {
      setTimeout(() => inputEl?.focus(), 200);
    }
  }

  function scrollToBottom() {
    const messagesEl = document.getElementById("assistantMessages");
    if (messagesEl) {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  }

  function formatMarkdownHtml(text) {
    if (!text) return "";
    let html = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    html = html.replace(/\*\*(.*?)\*\*/g, "<strong class='font-bold text-teal-700 dark:text-teal-300'>$1</strong>");
    html = html.replace(/\*(.*?)\*/g, "<em>$1</em>");
    html = html.replace(/\n/g, "<br>");
    return html;
  }

  function renderMessage(role, content) {
    const welcomeEl = document.getElementById("assistantWelcome");
    const messagesEl = document.getElementById("assistantMessages");
    if (welcomeEl) welcomeEl.classList.add("hidden");

    const wrap = document.createElement("div");
    wrap.className = `flex ${role === "assistant" ? "justify-start" : "justify-end"}`;

    const bubble = document.createElement("div");
    bubble.className =
      "max-w-[88%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm " +
      (role === "assistant"
        ? "bg-stone-100 text-stone-800 dark:bg-slate-800 dark:text-stone-100"
        : "bg-teal-600 text-white");

    const text = document.createElement("div");
    text.className = "whitespace-pre-wrap break-words";
    text.innerHTML = formatMarkdownHtml(content);
    bubble.appendChild(text);

    if (role === "assistant") {
      lastAssistantReply = content;
      const actions = document.createElement("div");
      actions.className = "mt-2.5 flex items-center gap-2 pt-2 border-t border-stone-200/60 dark:border-slate-700/60";

      const listenBtn = document.createElement("button");
      listenBtn.type = "button";
      listenBtn.className =
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-teal-600 hover:bg-teal-500 text-white text-xs font-bold shadow-sm transition";
      listenBtn.innerHTML = `<i class="fa-solid fa-volume-high"></i> ${currentLang === "bn" ? "ভয়েস শুনুন (Google AI)" : "Play Voice (Google AI)"}`;
      listenBtn.addEventListener("click", () => voiceEngine.play(content, currentLang, true));

      const stopBtn = document.createElement("button");
      stopBtn.type = "button";
      stopBtn.className =
        "inline-flex items-center gap-1 px-2 py-1 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold shadow-sm transition";
      stopBtn.innerHTML = `<i class="fa-solid fa-square"></i> OFF`;
      stopBtn.addEventListener("click", () => voiceEngine.stop());

      const replayBtn = document.createElement("button");
      replayBtn.type = "button";
      replayBtn.className =
        "inline-flex items-center gap-1 px-2 py-1 rounded-xl bg-slate-700 hover:bg-slate-600 text-slate-100 text-xs font-bold shadow-sm transition";
      replayBtn.innerHTML = `<i class="fa-solid fa-rotate-left"></i> RESTART`;
      replayBtn.addEventListener("click", () => voiceEngine.restart());

      actions.appendChild(listenBtn);
      actions.appendChild(stopBtn);
      actions.appendChild(replayBtn);
      bubble.appendChild(actions);
    }

    wrap.appendChild(bubble);
    messagesEl?.appendChild(wrap);
    scrollToBottom();
  }

  async function loadHistory() {
    const welcomeEl = document.getElementById("assistantWelcome");
    try {
      const res = await fetch(cfg.urls.history, { credentials: "same-origin" });
      if (!res.ok) return;
      const data = await res.json();
      historyLoaded = true;

      if (data.messages && data.messages.length) {
        if (welcomeEl) welcomeEl.classList.add("hidden");
        data.messages.forEach((msg) => renderMessage(msg.role, msg.content));
      }
    } catch (_) {
      /* silent */
    }
  }

  function setSending(sending) {
    isSending = sending;
    const sendBtn = document.getElementById("assistantSendBtn");
    const typingEl = document.getElementById("assistantTyping");
    if (sendBtn) sendBtn.disabled = sending;
    if (typingEl) typingEl.classList.toggle("hidden", !sending);
    if (sending) scrollToBottom();
  }

  function clearAttachedFile() {
    attachedFile = null;
    const fileInputEl = document.getElementById("assistantFileInput");
    const filePreviewEl = document.getElementById("assistantFilePreview");
    if (fileInputEl) fileInputEl.value = "";
    if (filePreviewEl) filePreviewEl.classList.add("hidden");
  }

  async function sendMessage(text) {
    const inputEl = document.getElementById("assistantInput");
    const message = (text || inputEl?.value || "").trim();
    if ((!message && !attachedFile) || isSending) return;

    const currentFile = attachedFile;
    let displayMessage = message;
    if (currentFile) {
      displayMessage += ` 📎 [Attached File: ${currentFile.name}]`;
    }

    if (inputEl) {
      inputEl.value = "";
      inputEl.style.height = "auto";
    }
    clearAttachedFile();

    renderMessage("user", displayMessage);
    setSending(true);

    try {
      const formData = new FormData();
      formData.append("message", message);
      formData.append("lang", currentLang);
      if (currentFile) {
        formData.append("file", currentFile);
      }

      const res = await fetch(cfg.urls.send, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "X-CSRFToken": cfg.csrfToken,
        },
        body: formData,
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed");

      renderMessage("assistant", data.reply);
      voiceEngine.play(data.reply, data.language || currentLang, false);
    } catch (_) {
      renderMessage("assistant", cfg.strings.error);
    } finally {
      setSending(false);
    }
  }

  async function clearChat() {
    if (!confirm(currentLang === "bn" ? "সব কথোপকথন মুছে ফেলবেন?" : "Clear all chat history?")) return;

    const welcomeEl = document.getElementById("assistantWelcome");
    const messagesEl = document.getElementById("assistantMessages");
    try {
      await fetch(cfg.urls.clear, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": cfg.csrfToken },
      });
      voiceEngine.stop();
      messagesEl?.querySelectorAll(".flex.justify-start, .flex.justify-end").forEach((el) => el.remove());
      if (welcomeEl) {
        welcomeEl.classList.remove("hidden");
        renderMessage("assistant", cfg.strings.cleared);
      }
    } catch (_) {
      /* silent */
    }
  }

  function toggleVoiceInput() {
    const micBtn = document.getElementById("assistantMicBtn");
    const micIcon = document.getElementById("assistantMicIcon");
    const inputEl = document.getElementById("assistantInput");

    if (isListening && activeRecognition) {
      activeRecognition.stop();
      isListening = false;
      return;
    }

    const Recognition = getSpeechApi();
    if (!Recognition) {
      alert("Voice input is not supported on this browser.");
      return;
    }

    const recognition = new Recognition();
    activeRecognition = recognition;
    recognition.lang = getSpeechLang(currentLang);
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 3;

    isListening = true;
    micBtn?.classList.add("bg-teal-600", "text-white", "animate-pulse");
    if (micIcon) micIcon.className = "fa-solid fa-microphone-slash text-lg";

    recognition.onresult = (event) => {
      const transcript = Array.from(event.results || [])
        .map((r) => r[0]?.transcript || "")
        .join(" ")
        .trim();
      if (transcript) {
        if (inputEl) inputEl.value = transcript;
        sendMessage(transcript);
      }
    };

    recognition.onerror = () => resetMicUI();
    recognition.onend = () => resetMicUI();

    function resetMicUI() {
      isListening = false;
      activeRecognition = null;
      micBtn?.classList.remove("bg-teal-600", "text-white", "animate-pulse");
      if (micIcon) micIcon.className = "fa-solid fa-microphone text-lg";
    }

    recognition.start();
  }

  function toggleLang() {
    const next = currentLang === "bn" ? "en" : "bn";
    window.location.href = next === "bn" ? cfg.urls.setLangBn : cfg.urls.setLangEn;
  }

  document.addEventListener("DOMContentLoaded", function () {
    const toggle = document.getElementById("assistantToggle");
    const closeBtn = document.getElementById("assistantCloseBtn");
    const clearBtn = document.getElementById("assistantClearBtn");
    const langBtn = document.getElementById("assistantLangBtn");
    const sendBtn = document.getElementById("assistantSendBtn");
    const micBtn = document.getElementById("assistantMicBtn");
    const inputEl = document.getElementById("assistantInput");
    const fileInputEl = document.getElementById("assistantFileInput");
    const removeFileBtn = document.getElementById("assistantRemoveFileBtn");

    toggle?.addEventListener("click", () => setPanelOpen(!isOpen));
    closeBtn?.addEventListener("click", () => setPanelOpen(false));
    clearBtn?.addEventListener("click", clearChat);
    langBtn?.addEventListener("click", toggleLang);
    sendBtn?.addEventListener("click", () => sendMessage());
    micBtn?.addEventListener("click", toggleVoiceInput);

    fileInputEl?.addEventListener("change", (e) => {
      const file = e.target.files?.[0];
      const fileNameEl = document.getElementById("assistantFileName");
      const filePreviewEl = document.getElementById("assistantFilePreview");
      if (file) {
        attachedFile = file;
        if (fileNameEl) fileNameEl.textContent = file.name;
        if (filePreviewEl) filePreviewEl.classList.remove("hidden");
      } else {
        clearAttachedFile();
      }
    });

    removeFileBtn?.addEventListener("click", clearAttachedFile);

    inputEl?.addEventListener("input", () => {
      inputEl.style.height = "auto";
      inputEl.style.height = Math.min(inputEl.scrollHeight, 128) + "px";
    });

    inputEl?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isOpen) setPanelOpen(false);
  });

  if (new URLSearchParams(window.location.search).get("assistant") === "open") {
    setPanelOpen(true);
  }

  cfg.openWithText = function (text) {
    setPanelOpen(true);
    if (text) {
      setTimeout(() => sendMessage(text), 300);
    }
  };
})();
