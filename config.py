"""
All settings in one place. Change a model, price or limit here, never inside the app code.
"""

# --- Model routing -----------------------------------------------------------
# The conversation runs on every turn, so it uses the fastest, cheapest model.
# Grading and drafting scenarios happen once, so they get the stronger model.
MODELS = {
    "chat": "gemini-3.5-flash-lite",    # thinking defaults to "minimal": fastest
    "grade": "gemini-3.6-flash",
    "draft": "gemini-3.6-flash",
}
THINKING = {"chat": "MINIMAL", "grade": "LOW", "draft": "LOW"}

# --- Prices (USD per 1 million tokens), paid-tier rates from ai.google.dev/pricing
# On the free tier you pay nothing; costs are still logged so a class can be budgeted.
# gemini-3.6-flash rates double on 1 Jan 2027 (to 1.50 / 7.50).
PRICES = {
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
    "gemini-3.6-flash": {"input": 0.75, "output": 3.75},
    # TTS rate from the TTS table on the pricing page; check before budgeting.
    "gemini-3.8-flash-lite-tts": {"input": 0.50, "output": 10.00},
    "edge-tts": {"input": 0.0, "output": 0.0},
}

# --- Voice output ------------------------------------------------------------------
# Tried in order, per sentence. "edge" is first because it is the fastest:
# Microsoft Edge's free read-aloud voices (edge-tts package, no key).
# "gemini" is Google's TTS model: official API, may need billing enabled.
# If every option fails the character replies in text only. The app never breaks.
TTS_PROVIDERS = ["edge", "gemini"]
GEMINI_TTS_MODEL = "gemini-3.8-flash-lite-tts"
VOICES = {
    # gender -> language -> voice
    "edge": {
        "male": {"en": "en-GB-RyanNeural", "ar": "ar-QA-MoazNeural"},
        "female": {"en": "en-GB-SoniaNeural", "ar": "ar-QA-AmalNeural"},
    },
    "gemini": {"male": "Charon", "female": "Kore"},
}
VOICE_STYLES = {
    "neutral": "calm, professional tone",
    "pleased": "warm and friendly, slightly upbeat",
    "thinking": "thoughtful and measured",
    "firm": "firm and serious, polite but not budging",
    "upset": "frustrated and impatient, but not shouting",
}

# --- Guardrails ----------------------------------------------------------------
MAX_STUDENT_TURNS = 30
MAX_MESSAGE_CHARS = 1000
MAX_AUDIO_BYTES = 4_000_000        # ~2 minutes of 16 kHz mono WAV
REQUEST_TIMEOUT_SECONDS = 30
RETRIES = 1                         # one retry on temporary errors before giving up
SESSION_IDLE_MINUTES = 90           # in-memory sessions are dropped after this
MAX_CUSTOM_SCENARIOS = 200

# --- Storage ---------------------------------------------------------------------
LOG_DIR = "logs"
CUSTOM_DIR = "data/custom"
PRESET_DIR = "scenarios/presets"
