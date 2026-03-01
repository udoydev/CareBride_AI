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
    const icon = btn.querySelector("i");
    if (icon) {
      if (isDark) {
        icon.className = "fa-solid fa-sun text-amber-400 text-lg transition-transform hover:scale-110";
      } else {
        icon.className = "fa-solid fa-moon text-slate-200 text-lg transition-transform hover:scale-110";
      }
    }
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
  const lower = (lang || "en").toLowerCase();
  const isBn = lower.startsWith("bn");

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
  const isBn = (lang || "en").startsWith("bn");

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

function getVoiceModal() {
  let modal = document.getElementById("carebridgeVoiceModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "carebridgeVoiceModal";
    modal.className = "fixed inset-0 z-[200] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm transition-opacity opacity-0 pointer-events-none";
    modal.innerHTML = `
      <div class="w-full max-w-sm rounded-3xl border border-teal-500/30 bg-slate-900 p-6 text-center shadow-2xl text-white">
        <div id="carebridgeVoiceIcon" class="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-teal-500/20 text-teal-400 ring-4 ring-teal-500/30 animate-pulse">
          <i class="fa-solid fa-microphone-lines text-2xl"></i>
        </div>
        <h3 id="carebridgeVoiceTitle" class="mt-4 text-lg font-bold">Listening...</h3>
        <p id="carebridgeVoiceStatus" class="mt-2 text-xs text-slate-300">Say: Dashboard, Today, Doses, Doctors, Records...</p>
        <div class="mt-6 flex justify-center">
          <button id="carebridgeVoiceCloseBtn" type="button" class="rounded-full bg-white/10 px-5 py-2 text-xs font-semibold text-white transition hover:bg-white/20">
            Cancel
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }
  return modal;
}

function showVoiceModal(title, status) {
  const modal = getVoiceModal();
  document.getElementById("carebridgeVoiceTitle").textContent = title;
  document.getElementById("carebridgeVoiceStatus").textContent = status;
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
    alert("Voice input is not supported in this browser.");
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
  { terms: ["dashboard", "ড্যাশবোর্ড", "home", "হোম", "main", "মেইন"], url: "/patient/dashboard/" },
  { terms: ["today", "আজ", "আজকের ওষুধ", "ডোজ", "medicine", "oshud", "osud", "doses"], url: "/patient/doses/today/" },
  { terms: ["records", "record", "health record", "রেকর্ড", "স্বাস্থ্য"], url: "/patient/health-record/" },
  { terms: ["follow", "follow up", "ফলো আপ", "ফলোআপ", "appointment"], url: "/patient/follow-ups/" },
  { terms: ["doctor", "doctors", "ডাক্তার", "daktar", "physician"], url: "/patient/doctors/" },
  { terms: ["chat", "assistant", "চ্যাট", "সহায়তা", "help"], url: "/patient/chat/" },
  { terms: ["profile", "প্রোফাইল", "account", "অ্যাকাউন্ট"], url: "/accounts/profile/" },
  { terms: ["logout", "log out", "exit", "বের হন", "লগ আউট"], url: "/accounts/logout/" }
];

function getVoiceConfig() {
  const dynamic = (window.CAREBRIDGE_VOICE_COMMANDS && window.CAREBRIDGE_VOICE_COMMANDS.patient) || [];
  return dynamic.length ? dynamic : DEFAULT_VOICE_COMMANDS;
}

function getVoiceModal() {
  let modal = document.getElementById("carebridgeVoiceModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "carebridgeVoiceModal";
    modal.className = "fixed inset-0 z-[200] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm transition-opacity opacity-0 pointer-events-none";
    modal.innerHTML = `
      <div class="w-full max-w-sm rounded-3xl border border-teal-500/30 bg-slate-900 p-6 text-center shadow-2xl text-white">
        <div id="carebridgeVoiceIcon" class="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-teal-500/20 text-teal-400 ring-4 ring-teal-500/30 animate-pulse">
          <i class="fa-solid fa-microphone-lines text-2xl"></i>
        </div>
        <h3 id="carebridgeVoiceTitle" class="mt-4 text-lg font-bold">Listening...</h3>
        <p id="carebridgeVoiceStatus" class="mt-2 text-xs text-slate-300">Say: Dashboard, Today, Doses, Doctors, Records...</p>

        <!-- Quick command pills -->
        <div id="carebridgeVoicePills" class="mt-4 flex flex-wrap justify-center gap-1.5 text-xs">
          <button type="button" onclick="window.location.href='/patient/dashboard/'" class="rounded-full bg-white/10 px-3 py-1 text-slate-200 hover:bg-teal-600 hover:text-white">ড্যাশবোর্ড / Dashboard</button>
          <button type="button" onclick="window.location.href='/patient/doses/today/'" class="rounded-full bg-white/10 px-3 py-1 text-slate-200 hover:bg-teal-600 hover:text-white">ওষুধ / Today</button>
          <button type="button" onclick="window.location.href='/patient/health-record/'" class="rounded-full bg-white/10 px-3 py-1 text-slate-200 hover:bg-teal-600 hover:text-white">রেকর্ড / Records</button>
          <button type="button" onclick="window.location.href='/patient/doctors/'" class="rounded-full bg-white/10 px-3 py-1 text-slate-200 hover:bg-teal-600 hover:text-white">ডাক্তার / Doctors</button>
          <button type="button" onclick="window.location.href='/patient/chat/'" class="rounded-full bg-white/10 px-3 py-1 text-slate-200 hover:bg-teal-600 hover:text-white">চ্যাট / Chat</button>
        </div>

        <div class="mt-5 flex justify-center">
          <button id="carebridgeVoiceCloseBtn" type="button" class="rounded-full bg-white/10 px-5 py-2 text-xs font-semibold text-white transition hover:bg-white/20">
            Cancel
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }
  return modal;
}

async function runVoiceNavigation(button) {
  const lang = button?.dataset.lang || "en";
  const config = getVoiceConfig();
  const isBn = lang.startsWith("bn");

  showVoiceModal(
    isBn ? "শুনছি..." : "Listening...",
    isBn ? "বলুন: ড্যাশবোর্ড, ওষুধ, রেকর্ড, ফলো আপ, ডাক্তার, চ্যাট..." : "Say: Dashboard, Today, Doses, Doctors, Records, Chat..."
  );

  const closeBtn = document.getElementById("carebridgeVoiceCloseBtn");
  let canceled = false;
  if (closeBtn) {
    closeBtn.onclick = () => {
      canceled = true;
      hideVoiceModal();
    };
  }

  try {
    // Try primary language
    let res = await startSpeechRecognition({
      lang: isBn ? "bn-BD" : "en-US",
    }).catch(() => null);

    // Dual-language fallback if primary produced no match
    let matched = res && res.primary ? matchVoiceTarget(res.primary, res.alternatives, config) : null;
    let spoken = res ? res.primary : "";

    if (!matched && !canceled) {
      // Try secondary language
      const secondaryRes = await startSpeechRecognition({
        lang: isBn ? "en-US" : "bn-BD",
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
      showVoiceModal(
        isBn ? "বুঝেছি!" : "Command Recognized!",
        isBn ? `পাওয়া গেছে: "${spoken}". নিয়ে যাচ্ছি...` : `Heard: "${spoken}". Navigating...`
      );
      
      const confirmSpeech = isBn ? "নেভিগেট করা হচ্ছে।" : "Navigating now.";
      speakText(confirmSpeech, lang);

      setTimeout(() => {
        hideVoiceModal();
        window.location.href = matched.url;
      }, 900);
      return;
    }

    if (spoken) {
      showVoiceModal(
        isBn ? "কমান্ড মেলেনি" : "Command Not Recognized",
        isBn ? `শোনা গেছে: "${spoken}"\nনিচের অপশনে ক্লিক করুন:` : `Heard: "${spoken}"\nOr tap a quick command below:`
      );
      speakText(isBn ? "দুঃখিত, কমান্ডটি বোঝা যায়নি।" : "Sorry, command not recognized.", lang);
    } else {
      showVoiceModal(
        isBn ? "কিছু শোনা যায়নি" : "No Speech Detected",
        isBn ? "নিচের অপশনে ক্লিক করতে পারেন:" : "You can tap a command below:"
      );
    }

    setTimeout(() => {
      if (!canceled) hideVoiceModal();
    }, 4000);
  } catch (error) {
    if (!canceled) {
      showVoiceModal(
        isBn ? "ভয়েস কমান্ড" : "Voice Commands",
        isBn ? "নিচের অপশনে ক্লিক করে নেভিগেট করুন:" : "Tap a target to navigate:"
      );
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
    const res = await startSpeechRecognition({
      lang: button.dataset.lang === "bn" ? "bn-BD" : "en-US",
    });
    if (res && res.primary) {
      input.value = res.primary;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
  } catch (error) {
    alert("Could not capture voice input. Please try again.");
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
  if (menuBtn) {
    menuBtn.addEventListener("click", () => {
      const mobileMenu = document.getElementById("mobileMenu");
      if (!mobileMenu) return;
      const isOpen = !mobileMenu.classList.contains("hidden");
      setMenuState(!isOpen);
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
      speakText(button.dataset.speakText || "", button.dataset.lang || "en");
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
