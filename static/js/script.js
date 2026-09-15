const THEME_STORAGE_KEY = "carebridge-theme";

function updateThemeButtonsUI(theme) {
  const isDark = theme === "dark";
  const buttons = document.querySelectorAll("#themeBtnDesktop, #themeBtnMobile, [data-theme-toggle]");
  const isBn = document.documentElement.lang === "bn";
  const label = isDark
    ? (isBn ? "লাইট মোডে পরিবর্তন করুন" : "Switch to light mode")
    : (isBn ? "ডার্ক মোডে পরিবর্তন করুন" : "Switch to dark mode");

  buttons.forEach((btn) => {
    btn.setAttribute("aria-label", label);
    btn.setAttribute("title", label);
  });
}

function setTheme(theme) {
  const root = document.documentElement;
  const nextTheme = theme === "dark" ? "dark" : "light";
  root.classList.toggle("dark", nextTheme === "dark");
  root.dataset.theme = nextTheme;
  localStorage.setItem(THEME_STORAGE_KEY, nextTheme);

  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.setAttribute("content", nextTheme === "dark" ? "#0b1210" : "#0f766e");
  }

  updateThemeButtonsUI(nextTheme);
}

function toggleTheme() {
  const isDark = document.documentElement.classList.contains("dark");
  setTheme(isDark ? "light" : "dark");
}

function getTheme() {
  const saved = localStorage.getItem(THEME_STORAGE_KEY);
  if (saved === "dark" || saved === "light") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function setMenuState(open) {
  const mobileMenu = document.getElementById("mobileMenu");
  const menuBtn = document.getElementById("menuBtn");
  if (!mobileMenu || !menuBtn) return;
  mobileMenu.classList.toggle("hidden", !open);
  menuBtn.setAttribute("aria-expanded", String(open));
}

function getSpeechRecognition() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function normalizeSpeech(text) {
  return (text || "")
    .toLowerCase()
    .replace(/[^\w\s\u0980-\u09FF]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function pickVoice(lang) {
  const voices = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
  const lower = (lang || "bn-BD").toLowerCase();
  const isBn = lower.includes("bn") || lower.includes("bangla") || lower.includes("bengali");

  if (isBn) {
    const bnNeedles = ["bn-bd", "bn-in", "bangla", "bengali", "bn"];
    for (const needle of bnNeedles) {
      const match = voices.find((v) =>
        v.lang.toLowerCase().includes(needle) || v.name.toLowerCase().includes(needle)
      );
      if (match) return match;
    }
  } else {
    const enNeedles = ["en-us", "en-gb", "en"];
    for (const needle of enNeedles) {
      const match = voices.find((v) =>
        v.lang.toLowerCase().includes(needle) || v.name.toLowerCase().includes(needle)
      );
      if (match) return match;
    }
  }

  return voices[0] || null;
}

function cleanMarkdownForSpeech(text, isBn) {
  let cleaned = String(text || "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/\*(.*?)\*/g, "$1")
    .replace(/\[(.*?)\]\(.*?\)/g, "$1")
    .replace(/[\#\`\_\~\•\-\|]/g, " ")
    .replace(/Dr\./gi, isBn ? "ডাক্তার" : "Doctor")
    .replace(/Dr /gi, isBn ? "ডাক্তার " : "Doctor ")
    .replace(/BP/g, isBn ? "ব্লাড প্রেসার" : "Blood pressure")
    .replace(/Rx/gi, isBn ? "প্রেসক্রিপশন" : "Prescription")
    .replace(/mg/gi, isBn ? "মিলেগ্রাম" : "milligrams")
    .replace(/\n+/g, ". ")
    .replace(/\s+/g, " ")
    .trim();

  if (isBn) {
    const numMap = {'0':'০','1':'১','2':'২','3':'৩','4':'৪','5':'৫','6':'৬','7':'৭','8':'৮','9':'৯'};
    cleaned = cleaned.replace(/[0-9]/g, (w) => numMap[w] || w);
  }
  return cleaned;
}

function speakText(text, lang) {
  if (!window.speechSynthesis || !text) return;
  const isBn = (lang || "bn-BD").startsWith("bn");

  const cleaned = cleanMarkdownForSpeech(text, isBn);
  if (!cleaned) return;

  window.speechSynthesis.cancel();
  const chunks = cleaned.split(/(?<=[.!?।])\s+/).filter(Boolean);

  const queue = chunks.length ? chunks : [cleaned];
  queue.forEach((chunk) => {
    const utterance = new SpeechSynthesisUtterance(chunk);
    const voiceLang = isBn ? "bn-BD" : "en-US";
    utterance.lang = voiceLang;
    const voice = pickVoice(voiceLang);
    if (voice) utterance.voice = voice;
    utterance.rate = isBn ? 0.85 : 0.95;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;
    window.speechSynthesis.speak(utterance);
  });
}

function getVoiceModal(lang) {
  let modal = document.getElementById("carebridgeVoiceModal");
  const isEn = lang === "en" || document.documentElement.lang === "en";

  if (!modal) {
    modal = document.createElement("div");
    modal.id = "carebridgeVoiceModal";
    modal.className = "fixed inset-0 z-[200] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm transition-opacity opacity-0 pointer-events-none";
    modal.innerHTML = `
      <div class="w-full max-w-sm rounded-3xl border border-teal-500/30 bg-slate-900 p-6 text-center shadow-2xl text-white">
        <div id="carebridgeVoiceIcon" class="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-teal-500/20 text-teal-400 ring-4 ring-teal-500/30 animate-pulse">
          <i class="fa-solid fa-microphone-lines text-2xl"></i>
        </div>
        <h3 id="carebridgeVoiceTitle" class="mt-4 text-lg font-bold"></h3>
        <p id="carebridgeVoiceStatus" class="mt-2 text-xs text-slate-300"></p>

        <!-- Dynamic navbar command pills -->
        <div id="carebridgeVoicePills" class="mt-4 flex flex-wrap justify-center gap-1.5 text-xs">
        </div>

        <div class="mt-5 flex justify-center">
          <button id="carebridgeVoiceCloseBtn" type="button" class="rounded-full bg-white/10 px-5 py-2 text-xs font-semibold text-white transition hover:bg-white/20">
            ${isEn ? "Cancel" : "বাতিল / Cancel"}
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }
  
  const closeBtn = modal.querySelector("#carebridgeVoiceCloseBtn");
  if (closeBtn) {
    closeBtn.textContent = isEn ? "Cancel" : "বাতিল / Cancel";
  }

  return modal;
}

function renderVoiceModalPills(commands, lang) {
  const pillsContainer = document.getElementById("carebridgeVoicePills");
  if (!pillsContainer) return;

  const isEn = lang === "en" || document.documentElement.lang === "en";

  pillsContainer.innerHTML = "";
  (commands || []).forEach((cmd) => {
    if (!cmd.url || cmd.url.includes("/chat") || cmd.url.includes("chatbot")) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.onclick = () => { window.location.href = cmd.url; };
    const isScan = cmd.url.includes("scan");
    btn.className = isScan
      ? "rounded-full bg-teal-500/30 px-3 py-1 font-bold text-teal-300 hover:bg-teal-600 hover:text-white transition"
      : "rounded-full bg-white/10 px-3 py-1 text-slate-200 hover:bg-teal-600 hover:text-white transition";
    
    let label = isEn ? (cmd.labelEn || cmd.label) : (cmd.labelBn || cmd.label);
    btn.textContent = label || (cmd.terms && cmd.terms[0]) || "Nav";
    pillsContainer.appendChild(btn);
  });
}

function showVoiceModal(title, status, commands, lang) {
  const modal = getVoiceModal(lang);
  document.getElementById("carebridgeVoiceTitle").textContent = title;
  document.getElementById("carebridgeVoiceStatus").textContent = status;
  if (commands) {
    renderVoiceModalPills(commands, lang);
  }
  modal.classList.remove("opacity-0", "pointer-events-none");
  modal.classList.add("opacity-100");
}

function hideVoiceModal() {
  const modal = document.getElementById("carebridgeVoiceModal");
  if (modal) {
    modal.classList.remove("opacity-100");
    modal.classList.add("opacity-0", "pointer-events-none");
  }
}

async function startSpeechRecognition(options) {
  const Recognition = getSpeechRecognition();
  if (!Recognition) {
    alert("Voice recognition is not supported on this browser. Please use Chrome or Edge.");
    return null;
  }

  const recognition = new Recognition();
  recognition.lang = options.lang || "en-US";
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.maxAlternatives = 5;

  return new Promise((resolve, reject) => {
    recognition.onresult = (event) => {
      let results = [];
      if (event.results && event.results[0]) {
        for (let i = 0; i < event.results[0].length; i++) {
          results.push(event.results[0][i].transcript);
        }
      }
      const primary = results[0] || "";
      resolve({ primary, alternatives: results });
    };

    recognition.onerror = (event) => {
      reject(new Error(event.error || "speech recognition error"));
    };

    recognition.onend = () => {};
    recognition.start();
  });
}

function matchVoiceTarget(text, alternatives, targets) {
  const allTexts = [text, ...(alternatives || [])];
  for (const candidate of allTexts) {
    const normalized = normalizeSpeech(candidate);
    const matched = targets.find((target) =>
      target.terms.some((term) => normalized.includes(normalizeSpeech(term)))
    );
    if (matched) return matched;
  }
  return null;
}

const DEFAULT_VOICE_COMMANDS = [
  { terms: ["scan", "ocr", "prescription scan", "প্রেসক্রিপশন স্ক্যান", "স্ক্যান", "ছবি স্ক্যান", "প্রেসক্রিপশন"], url: "/prescriptions/scan/", labelEn: "📄 Scan", labelBn: "📄 স্ক্যান / Scan" },
  { terms: ["dashboard", "ড্যাশবোর্ড", "home", "হোম", "main page"], url: "/patient/dashboard/", labelEn: "Dashboard", labelBn: "ড্যাশবোর্ড / Dashboard" },
  { terms: ["today", "doses", "ডোজ", "আজ", "আজকের ওষুধ", "medicine", "oshud", "osud", "ওষুধ"], url: "/patient/doses/today/", labelEn: "Today's Doses", labelBn: "ওষুধ / Today" },
  { terms: ["records", "record", "health record", "রেকর্ড", "স্বাস্থ্য", "মেডিকেল হিস্ট্রি"], url: "/patient/health-record/", labelEn: "Health Records", labelBn: "রেকর্ড / Records" },
  { terms: ["appointments", "appointment", "অ্যাপয়েন্টমেন্ট", "ফলো আপ", "ফলোআপ", "visit"], url: "/patient/appointments/", labelEn: "Appointments", labelBn: "অ্যাপয়েন্টমেন্ট / Appointments" },
  { terms: ["analytics", "অ্যানালিটিক্স", "report", "রিপোর্ট"], url: "/patient/analytics/", labelEn: "Analytics", labelBn: "অ্যানালিটিক্স / Analytics" },
  { terms: ["overall report", "overall", "ওভারঅল রিপোর্ট"], url: "/patient/overall-report/", labelEn: "Overall Report", labelBn: "ওভারঅল / Overall Report" },
  { terms: ["doctor", "doctors", "ডাক্তার", "daktar", "physician", "ডাক্তার তালিকা", "ডাক্তার খুঁজুন"], url: "/patient/doctors/", labelEn: "Doctors", labelBn: "ডাক্তার / Doctors" },
  { terms: ["rules", "রুলস", "নিয়মাবলী", "নিয়ম"], url: "/patient/rules/", labelEn: "Rules", labelBn: "নিয়মাবলী / Rules" },
  { terms: ["profile", "প্রোফাইল", "account", "অ্যাকাউন্ট", "আমার প্রোফাইল"], url: "/accounts/profile/", labelEn: "Profile", labelBn: "প্রোফাইল / Profile" },
  { terms: ["logout", "log out", "exit", "বের হন", "লগ আউট"], url: "/accounts/logout/", labelEn: "Log out", labelBn: "লগ আউট / Logout" }
];

function getVoiceConfig() {
  const dynamic = (window.CAREBRIDGE_VOICE_COMMANDS && window.CAREBRIDGE_VOICE_COMMANDS.patient) || [];
  let baseConfig = dynamic.length ? dynamic : DEFAULT_VOICE_COMMANDS;
  
  // Filter out chat links completely
  baseConfig = baseConfig.filter(cmd => !cmd.url.includes("/chat") && !(cmd.terms && cmd.terms.some(t => t === "chat" || t === "চ্যাট")));

  // Dynamically attach labels if missing
  baseConfig.forEach(cmd => {
    if (!cmd.labelEn || !cmd.labelBn) {
      const matchDefault = DEFAULT_VOICE_COMMANDS.find(d => d.url === cmd.url);
      if (matchDefault) {
        cmd.labelEn = cmd.labelEn || matchDefault.labelEn;
        cmd.labelBn = cmd.labelBn || matchDefault.labelBn;
      } else {
        const fallback = cmd.terms && cmd.terms[0] ? cmd.terms[0] : "Nav";
        cmd.labelEn = cmd.labelEn || fallback;
        cmd.labelBn = cmd.labelBn || fallback;
      }
    }
  });

  return baseConfig;
}

async function runVoiceNavigation(button) {
  const pageLang = document.documentElement.lang || "en";
  const lang = button?.dataset.lang || pageLang;
  const isEn = lang === "en" || pageLang === "en";
  const config = getVoiceConfig();

  const initialTitle = isEn ? "Listening to Voice Command..." : "বাংলা ভয়েস কমান্ডে শুনছি...";
  const initialStatus = isEn
    ? "Say: Scan, Dashboard, Doses, Records, Appointments, Doctors..."
    : "বলুন: প্রেসক্রিপশন স্ক্যান, ড্যাশবোর্ড, ওষুধ, রেকর্ড, অ্যাপয়েন্টমেন্ট, ডাক্তার...";

  showVoiceModal(initialTitle, initialStatus, config, lang);

  const closeBtn = document.getElementById("carebridgeVoiceCloseBtn");
  let canceled = false;
  if (closeBtn) {
    closeBtn.onclick = () => {
      canceled = true;
      hideVoiceModal();
    };
  }

  try {
    const primaryLang = isEn ? "en-US" : "bn-BD";
    const secondaryLang = isEn ? "bn-BD" : "en-US";

    let res = await startSpeechRecognition({
      lang: primaryLang,
    }).catch(() => null);

    let matched = res && res.primary ? matchVoiceTarget(res.primary, res.alternatives, config) : null;
    let spoken = res ? res.primary : "";

    if (!matched && !canceled) {
      const secondaryRes = await startSpeechRecognition({
        lang: secondaryLang,
      }).catch(() => null);

      if (secondaryRes && secondaryRes.primary) {
        spoken = secondaryRes.primary;
        matched = matchVoiceTarget(secondaryRes.primary, secondaryRes.alternatives, config);
      }
    }

    if (canceled) {
      hideVoiceModal();
      return;
    }

    if (matched?.url) {
      const titleRecognized = isEn ? "Command Recognized!" : "কমান্ড সনাক্ত হয়েছে!";
      const statusRecognized = isEn
        ? `Heard: "${spoken}". Navigating...`
        : `শোনা গেছে: "${spoken}". নিয়ে যাচ্ছি...`;

      showVoiceModal(titleRecognized, statusRecognized, config, lang);
      
      const confirmSpeech = isEn ? "Command accepted. Navigating now." : "কমান্ড গ্রহণ করা হয়েছে। নেভিগেট করা হচ্ছে।";
      speakText(confirmSpeech, primaryLang);

      setTimeout(() => {
        hideVoiceModal();
        window.location.href = matched.url;
      }, 900);
      return;
    }

    if (spoken) {
      const titleUnmatched = isEn ? "No Matching Command" : "কমান্ড মেলেনি";
      const statusUnmatched = isEn
        ? `Heard: "${spoken}". Click any option below:`
        : `শোনা গেছে: "${spoken}"\nনিচের যেকোনো অপশনে ক্লিক করুন:`;

      showVoiceModal(titleUnmatched, statusUnmatched, config, lang);
      speakText(isEn ? "Sorry, no matching command found." : "দুঃখিত, কোনো কমান্ড মেলেনি।", primaryLang);
    } else {
      const titleNoSpeech = isEn ? "No Speech Detected" : "কিছু শোনা যায়নি";
      const statusNoSpeech = isEn
        ? "Click any option below to navigate:"
        : "নিচের বাটনে ক্লিক করে পেজে যেতে পারেন:";

      showVoiceModal(titleNoSpeech, statusNoSpeech, config, lang);
    }

    setTimeout(() => {
      if (!canceled) hideVoiceModal();
    }, 4000);
  } catch (error) {
    if (!canceled) {
      const titleError = isEn ? "Voice Navigation" : "ভয়েস নেভিগেশন";
      const statusError = isEn
        ? "Click any option below to navigate:"
        : "নিচের অপশনে ক্লিক করে নেভিগেট করুন:";

      showVoiceModal(titleError, statusError, config, lang);
      setTimeout(() => {
        if (!canceled) hideVoiceModal();
      }, 4000);
    }
  }
}

async function runVoiceInput(button) {
  const selector = button?.dataset.voiceInputTarget;
  if (!selector) return;
  const input = document.querySelector(selector);
  if (!input) return;

  button.disabled = true;
  button.classList.add("opacity-70");

  try {
    const isEn = document.documentElement.lang === "en";
    const res = await startSpeechRecognition({
      lang: isEn ? "en-US" : "bn-BD",
    });
    if (res && res.primary) {
      input.value = res.primary;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
  } catch (error) {
    alert("Voice input failed. Please try again.");
  } finally {
    button.disabled = false;
    button.classList.remove("opacity-70");
  }
}

window.CareBridgeSpeech = {
  speakText,
  startSpeechRecognition,
};

window.CareBridgeTheme = {
  setTheme,
  toggleTheme,
  getTheme,
  updateThemeButtonsUI,
};

function bindInteractions() {
  const menuBtn = document.getElementById("menuBtn");
  const mobileMenu = document.getElementById("mobileMenu");

  if (menuBtn && mobileMenu) {
    menuBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const isOpen = !mobileMenu.classList.contains("hidden");
      setMenuState(!isOpen);
    });

    mobileMenu.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => setMenuState(false));
    });

    document.addEventListener("click", (e) => {
      if (!mobileMenu.classList.contains("hidden") && !mobileMenu.contains(e.target) && !menuBtn.contains(e.target)) {
        setMenuState(false);
      }
    });

    window.addEventListener("resize", () => {
      if (window.innerWidth >= 768 && !mobileMenu.classList.contains("hidden")) {
        setMenuState(false);
      }
    });
  }

  document.getElementById("themeBtnDesktop")?.addEventListener("click", toggleTheme);
  document.getElementById("themeBtnMobile")?.addEventListener("click", toggleTheme);
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", toggleTheme);
  });

  updateThemeButtonsUI(document.documentElement.classList.contains("dark") ? "dark" : "light");

  document.querySelectorAll("[data-voice-nav]").forEach((button) => {
    button.addEventListener("click", () => runVoiceNavigation(button));
  });

  document.querySelectorAll("[data-voice-input]").forEach((button) => {
    button.addEventListener("click", () => runVoiceInput(button));
  });

  document.querySelectorAll("[data-speak-text]").forEach((button) => {
    button.addEventListener("click", () => {
      speakText(button.dataset.speakText || "", button.dataset.lang || "bn-BD");
    });
  });
}

(function initTheme() {
  setTheme(getTheme());
})();

if (window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    if (!localStorage.getItem(THEME_STORAGE_KEY)) {
      setTheme(e.matches ? "dark" : "light");
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindInteractions);
} else {
  bindInteractions();
}
