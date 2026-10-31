"""
All settings in one place. Change a model or a price here, never inside the app code.
"""

# --- Model routing -----------------------------------------------------------
# Two jobs, two models. The supplier chat runs many times per session, so it
# uses the cheaper, faster model. Grading happens once per session and needs
# better judgement, so it gets the stronger model.
# This is "model selection and routing" from the job description.
MODELS = {
    "chat": "gemini-3.5-flash-lite",
    "grade": "gemini-3.6-flash",
}

# --- Prices (USD per 1 million tokens) ----------------------------------------
# Paid-tier rates from ai.google.dev/pricing (checked Oct 2026).
# On the free tier you pay nothing; we still log "what this would cost"
# so we can plan a budget before 200 students use it.
# Note: gemini-3.6-flash rates double on 1 Jan 2027 (to 1.50 / 7.50).
PRICES = {
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
    "gemini-3.6-flash": {"input": 0.75, "output": 3.75},
    # TTS output is billed as audio tokens (about 25 per second of speech).
    # Rate taken from the TTS table on the pricing page; check it before budgeting.
    "gemini-3.8-flash-lite-tts": {"input": 0.50, "output": 10.00},
    "edge-tts": {"input": 0.0, "output": 0.0},
}

# --- Guardrails ----------------------------------------------------------------
MAX_STUDENT_TURNS = 20        # stops one student burning through the budget
MAX_MESSAGE_CHARS = 1000      # long pastes cost money and are rarely real negotiation
REQUEST_TIMEOUT_SECONDS = 30  # if the model is slower than this, give up and say so
RETRIES = 2                   # retry on temporary errors (rate limit, server busy)

# --- Logging -------------------------------------------------------------------
LOG_DIR = "logs"

# --- Voice -----------------------------------------------------------------------
# Speech-to-text: the student's recording is sent to the cheap chat model,
# which transcribes English or Arabic. Same model-access layer, same logging.
TRANSCRIBE_TASK = "chat"

# Text-to-speech: tried in order until one works.
#   "gemini" - Google's TTS model. Best quality, may need billing enabled.
#   "edge"   - Microsoft Edge's free read-aloud voices (edge-tts package).
#              No key needed. Has a Qatari Arabic voice.
# If every option fails, Yousef just replies in text. The app never breaks.
TTS_PROVIDERS = ["gemini", "edge"]
GEMINI_TTS_MODEL = "gemini-3.8-flash-lite-tts"
GEMINI_VOICE = "Charon"                       # a calm male voice
EDGE_VOICES = {"en": "en-GB-RyanNeural", "ar": "ar-QA-MoazNeural"}

# Speaking style per mood, sent to Gemini TTS so the voice matches the face.
VOICE_STYLES = {
    "neutral": "calm, professional business tone",
    "pleased": "warm and friendly, slightly upbeat",
    "thinking": "thoughtful and measured, a little hesitant",
    "firm": "firm and serious, polite but not budging",
}
MAX_RECORDING_BYTES = 5_000_000   # about 2.5 minutes of 16 kHz audio
