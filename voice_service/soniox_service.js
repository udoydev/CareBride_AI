import { SonioxNodeClient } from "@soniox/node";
import dotenv from "dotenv";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, "../.env") });

/**
 * Carebridge AI - Soniox Bengali & English Voice Service Wrapper
 * Optimized for High-Accuracy Bangladeshi Bangla (bn) Speech-to-Text (STT),
 * Speaker Diarization, and Two-Way Bangla <-> English Translation.
 */
export class CarebridgeSonioxVoiceService {
  constructor(apiKey = process.env.SONIOX_API_KEY) {
    this.apiKey = apiKey;
    if (!this.apiKey) {
      console.warn("⚠️ SONIOX_API_KEY is not set. Please add SONIOX_API_KEY to your .env file.");
    }
    this.client = new SonioxNodeClient({ apiKey: this.apiKey });
  }

  /**
   * Creates a Soniox real-time STT session specifically optimized for Bengali speech.
   * @param {Object} options Configuration overrides
   * @returns {Object} Soniox real-time STT session
   */
  createRealtimeSession(options = {}) {
    const sessionConfig = {
      model: options.model || "stt-rt-v5",
      // Use PCM 16kHz S16LE for optimal low-latency Bengali STT streaming from browser microphone
      audio_format: options.audio_format || "pcm_s16le",
      sample_rate_hertz: options.sample_rate_hertz || 16000,
      num_channels: options.num_channels || 1,
      language_hints: options.language_hints || ["bn", "en"],
      enable_speaker_diarization: options.enable_speaker_diarization ?? true,
      // Endpoint detection can force early token finalization which reduces Bengali STT accuracy during pauses
      enable_endpoint_detection: options.enable_endpoint_detection ?? false,
      enable_language_identification: options.enable_language_identification ?? true,
      translation: options.translation || {
        type: "two_way",
        language_a: "bn",
        language_b: "en",
      },
    };

    return this.client.realtime.stt(sessionConfig);
  }

  /**
   * Process an audio stream using Soniox real-time STT.
   */
  async processAudioStream(audioStream, onTranscript, onError, sessionOptions = {}) {
    const session = this.createRealtimeSession({
      audio_format: "auto",
      ...sessionOptions,
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

      if (onTranscript && text) {
        onTranscript({
          full_text: text,
          original: originalText,
          translation: translatedText,
          tokens: result.tokens,
          speaker: result.tokens[0]?.speaker || 0,
          detected_language: result.tokens[0]?.language || "bn",
        });
      }
    });

    session.on("error", (err) => {
      console.error("❌ Soniox Session Error:", err);
      if (onError) onError(err);
    });

    await session.connect();

    await session.sendStream(audioStream, {
      pace_ms: sessionOptions.pace_ms || 60,
      finish: true,
    });
  }
}
