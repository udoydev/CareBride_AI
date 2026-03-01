import express from "express";
import http from "http";
import { WebSocketServer } from "ws";
import cors from "cors";
import dotenv from "dotenv";
import path from "path";
import { fileURLToPath } from "url";
import { CarebridgeSonioxVoiceService } from "./soniox_service.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, "../.env") });

const app = express();
const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: "/ws/voice" });

app.use(cors());
app.use(express.json({ limit: "50mb" }));
app.use(express.urlencoded({ extended: true, limit: "50mb" }));

const sonioxService = new CarebridgeSonioxVoiceService();

// Health Check
app.get("/health", (req, res) => {
  res.json({
    status: "ok",
    service: "Carebridge Soniox Voice API",
    stt_model: "stt-rt-v5",
    languages: ["bn", "en"],
  });
});

// Demo MP3 Fetch Helper Stream
async function createDemoAudioStream(url = "https://soniox.com/media/examples/coffee_shop.mp3") {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Fetch failed: ${res.status} ${res.statusText}`);
  if (!res.body) throw new Error("No response body in audio request");
  return res.body;
}

// REST Endpoint: Demo Stream & Transcribe Audio
app.post("/api/voice/demo-transcribe", async (req, res) => {
  try {
    const audioUrl = req.body.audio_url || "https://soniox.com/media/examples/coffee_shop.mp3";
    const audioStream = await createDemoAudioStream(audioUrl);

    const transcripts = [];
    await sonioxService.processAudioStream(
      audioStream,
      (result) => {
        transcripts.push(result);
      },
      (err) => {
        console.error("Soniox Stream Error:", err);
      }
    );

    res.json({
      success: true,
      service: "Carebridge Voice STT",
      total_segments: transcripts.length,
      transcripts: transcripts,
    });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// REST Endpoint: Carebridge Voice Explainer (Speech + AI Explanation)
app.post("/api/voice/explainer", async (req, res) => {
  try {
    const { text_query, target_language = "bn" } = req.body;

    const explanation = {
      title: "Carebridge Medical Explainer (কেয়ারব্রীজ ভয়েস ব্যাখ্যা)",
      topic: text_query || "General Health Advice",
      language: target_language,
      explanation_audio_text: target_language === "bn"
        ? `আপনার চিকিৎসা সংক্রান্ত প্রশ্ন: "${text_query}"। কেয়ারব্রীজ এআই চিকিৎসা নির্দেশিকা থেকে উত্তর প্রস্তুত করা হয়েছে।`
        : `Medical explanation for: "${text_query}". Summary prepared by Carebridge AI.`,
    };

    res.json({ success: true, explainer: explanation });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// WebSocket Server for Real-Time Microphone Streaming (16kHz PCM S16LE)
wss.on("connection", (ws) => {
  console.log("🎙️ Client connected to Carebridge Voice Stream WebSocket");

  let session = null;

  try {
    session = sonioxService.createRealtimeSession({
      model: "stt-rt-v5",
      audio_format: "pcm_s16le",
      sample_rate_hertz: 16000,
      num_channels: 1,
      language_hints: ["bn", "en"],
      enable_speaker_diarization: true,
      enable_endpoint_detection: false,
      enable_language_identification: true,
      translation: {
        type: "two_way",
        language_a: "bn",
        language_b: "en",
      },
    });

    session.on("result", (result) => {
      const text = result.tokens.map((t) => t.text).join("");
      const originalText = result.tokens
        .filter((t) => t.translation_status !== "translation")
        .map((t) => t.text)
        .join("");
      const translatedText = result.tokens
        .filter((t) => t.translation_status === "translation")
        .map((t) => t.text)
        .join("");

      if (ws.readyState === ws.OPEN && text) {
        ws.send(
          JSON.stringify({
            type: "transcription",
            text,
            original: originalText || text,
            translation: translatedText,
            tokens: result.tokens,
            speaker: result.tokens[0]?.speaker || 0,
            language: result.tokens[0]?.language || "bn",
          })
        );
      }
    });

    session.on("error", (err) => {
      console.error("Soniox WebSocket Error:", err);
      if (ws.readyState === ws.OPEN) {
        ws.send(JSON.stringify({ type: "error", error: err.message }));
      }
    });

    session.connect().catch((err) => {
      console.error("Failed to connect Soniox session:", err);
    });

  } catch (err) {
    console.error("Failed to initialize Soniox real-time session:", err);
  }

  ws.on("message", async (data) => {
    try {
      if (typeof data === "string") {
        const msg = JSON.parse(data);
        if (msg.type === "finish" && session) {
          // Session finish signal
        }
      } else if (session) {
        // Binary 16kHz PCM audio chunk received from browser microphone
        await session.sendAudio(data);
      }
    } catch (err) {
      console.error("Error processing audio message:", err);
    }
  });

  ws.on("close", () => {
    console.log("🔌 Voice WebSocket Connection Closed");
  });
});

const PORT = process.env.SONIOX_VOICE_PORT || 5000;
server.listen(PORT, () => {
  console.log(`🚀 Carebridge Soniox Voice API Server running on port ${PORT}`);
  console.log(`🔊 Real-time Voice WebSocket: ws://localhost:${PORT}/ws/voice`);
});
