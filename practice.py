"""
Negotiation Practice: students negotiate with an AI supplier by voice or text,
then get feedback.

Run locally:  streamlit run app.py   (this page is loaded by app.py)

How Streamlit works (the one idea to understand):
the whole script re-runs from top to bottom on every click or message.
Anything that must survive between runs lives in st.session_state.
"""

import json
import re
import uuid

import streamlit as st

import config
from avatar import render_card
from i18n import LANGUAGES, RTL_LANGUAGES, t
from llm import ModelUnavailable, ask_model, speak, transcribe
from scenario import CASE, GRADER_SYSTEM, SUPPLIER_SYSTEM, money_summary, split_mood
from tracking import log_event



# ---------------------------------------------------------------------------
# Session state: set up once per browser session
# ---------------------------------------------------------------------------
def new_session():
    S.session_id = uuid.uuid4().hex[:12]   # random, not tied to a person
    # Each message: {"role": "user"/"assistant", "content": str,
    #                "mood": str (assistant), "voice": bool (user)}
    S.messages = []
    S.tokens = 0
    S.cost = 0.0
    S.started_logged = False
    S.feedback = None
    S.error = None
    S.notice = None
    S.audio = None          # (bytes, mime, message_id) of Yousef's latest line
    S.autoplay_id = None    # set for one run right after a new reply, so it plays once


S = st.session_state
if "session_id" not in S:
    new_session()
S.setdefault("lang", "en")
S.setdefault("voice_on", True)


def tr(key, **values):
    """Shortcut: interface text in the current language."""
    return t(key, S.lang, **values)


def student_turns():
    return sum(1 for m in S.messages if m["role"] == "user")


def add_usage(reply):
    S.tokens += reply.input_tokens + reply.output_tokens
    S.cost += reply.cost_usd


def text_language(text):
    """Yousef answers in whatever language the student used, so detect it from the text."""
    return "ar" if re.search(r"[؀-ۿ]", text) else "en"


# ---------------------------------------------------------------------------
# Opening line audio: same for everyone, so make it once per language and cache it.
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def opening_audio(lang, voice_providers_key):
    speech = speak(t("opening_line", lang), lang, "neutral", session_id="cache")
    return (speech.audio, speech.mime_type) if speech else None


# ---------------------------------------------------------------------------
# Page styling: right-to-left for Arabic, and keep the avatar in view while scrolling
# ---------------------------------------------------------------------------
st.markdown(
    """<style>
    .st-key-avatar_panel { position: sticky; top: 5rem; z-index: 2; }
    </style>""",
    unsafe_allow_html=True,
)
if S.lang in RTL_LANGUAGES:
    st.markdown(
        """<style>
        [data-testid="stMain"], [data-testid="stSidebar"], [data-testid="stChatInput"] textarea
        { direction: rtl; text-align: right; }
        </style>""",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sidebar: language, voice, brief, counters
# ---------------------------------------------------------------------------
with st.sidebar:
    chosen = st.selectbox(tr("language_label"), options=list(LANGUAGES),
                          format_func=LANGUAGES.get, index=list(LANGUAGES).index(S.lang))
    if chosen != S.lang:
        S.lang = chosen
        st.rerun()

    S.voice_on = st.toggle(tr("voice_toggle"), value=S.voice_on, help=tr("voice_help"))

    st.subheader(tr("brief_heading"))
    st.markdown(tr("brief", monthly_kg=CASE["monthly_kg"], months=CASE["months"],
                   budget=CASE["budget_per_kg"]))
    st.subheader(tr("tips_heading"))
    st.markdown(tr("tips"))
    st.caption("🎙️ " + tr("voice_tip"))

    st.divider()
    if S.feedback is None:
        st.caption(tr("turns_left", n=config.MAX_STUDENT_TURNS - student_turns()))
    st.caption(tr("session_cost", tokens=S.tokens, cost=S.cost), help=tr("session_cost_help"))

    if st.button(tr("restart_button"), width="stretch"):
        new_session()
        st.rerun()


# ---------------------------------------------------------------------------
# Avatar card
# ---------------------------------------------------------------------------
def avatar_html(waiting=False, waiting_text=""):
    last = next((m for m in reversed(S.messages) if m["role"] == "assistant"), None)
    if last:
        text, mood, msg_id = last["content"], last.get("mood", "neutral"), last["id"]
        audio = S.audio if (S.audio and S.audio[2] == msg_id) else None
    else:
        text, mood, msg_id = tr("opening_line"), "neutral", f"opening-{S.lang}"
        audio = None
        if S.voice_on:
            cached = opening_audio(S.lang, tuple(config.TTS_PROVIDERS))
            audio = (*cached, msg_id) if cached else None

    mood_label = tr(f"mood_{mood}")
    return render_card(
        uid=uuid.uuid4().hex[:8],
        msg_id=msg_id,
        name="Yousef" if S.lang == "en" else "يوسف",
        role=tr("supplier_role"),
        mood=mood,
        mood_label=mood_label,
        text=text,
        waiting=waiting,
        waiting_text=waiting_text,
        audio=audio[0] if (audio and S.voice_on) else None,
        audio_mime=audio[1] if audio else "audio/wav",
        autoplay=bool(audio and S.voice_on and S.autoplay_id == msg_id),
        play_label=tr("replay") if last else tr("play"),
        aria_label=tr("avatar_aria", mood=mood_label),
    )


# ---------------------------------------------------------------------------
# The two AI steps
# ---------------------------------------------------------------------------
def supplier_reply():
    """Send the conversation so far to the model and store Yousef's answer (and voice)."""
    system = SUPPLIER_SYSTEM + f'\nYou have already greeted the café owner with: "{tr("opening_line")}"'
    # Put the mood tags back on his earlier replies so the model keeps using them.
    history = [
        {"role": m["role"],
         "content": m["content"] + (f"\n[mood: {m['mood']}]" if m["role"] == "assistant" else "")}
        for m in S.messages
    ]
    reply = ask_model("chat", system, history, S.session_id, temperature=0.8)
    add_usage(reply)
    text, mood = split_mood(reply.text)
    msg_id = uuid.uuid4().hex[:10]
    S.messages.append({"role": "assistant", "content": text, "mood": mood, "id": msg_id})

    if S.voice_on and text:
        speech = speak(text, text_language(text), mood, S.session_id)
        if speech:
            S.cost += speech.cost_usd
            S.audio = (speech.audio, speech.mime_type, msg_id)
            S.autoplay_id = msg_id
        else:
            S.notice = tr("voice_unavailable")


def grade():
    """Second, separate AI call: an instructor reviews the whole transcript."""
    lines = [f"Supplier: {tr('opening_line')}"]
    for m in S.messages:
        speaker = "Student" if m["role"] == "user" else "Supplier"
        lines.append(f"{speaker}: {m['content']}")
    transcript = "\n".join(lines)

    system = GRADER_SYSTEM.replace("{language}", "Arabic" if S.lang == "ar" else "English")
    reply = ask_model("grade", system, [{"role": "user", "content": transcript}],
                      S.session_id, json_output=True, temperature=0.2)
    add_usage(reply)

    # Models sometimes wrap JSON in ```json fences even when asked not to.
    raw = re.sub(r"^```(?:json)?|```$", "", reply.text.strip()).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"deal_reached": False, "score": None, "summary": reply.text,
                "strengths": [], "improvements": [], "missed_opportunity": ""}


# ---------------------------------------------------------------------------
# Feedback (shown at the top of the page once the negotiation ends)
# ---------------------------------------------------------------------------
def show_feedback():
    fb = S.feedback
    money = money_summary(fb)

    st.header(tr("feedback_heading"))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(tr("score"), f"{fb['score']} / 10" if fb.get("score") else "-")
    if money:
        c2.metric(tr("deal_price"), tr("per_kg", p=money["price"]))
        under = money["vs_budget"] >= 0
        c3.metric(tr("vs_budget"), tr("qar_amount", v=abs(money["vs_budget"])),
                  delta=tr("under_label" if under else "over_label"),
                  delta_color="green" if under else "red", delta_arrow="down" if under else "up")
        c4.metric(tr("left_on_table"), tr("qar_amount", v=money["left_on_table"]),
                  help=tr("left_on_table_help"))
    else:
        c2.metric(tr("deal_price"), "-")
        st.info(tr("no_deal"))

    if fb.get("summary"):
        st.write(fb["summary"])
    a, b = st.columns(2)
    if fb.get("strengths"):
        a.subheader(tr("strengths"))
        a.markdown("\n".join(f"- {s}" for s in fb["strengths"]))
    if fb.get("improvements"):
        b.subheader(tr("improvements"))
        b.markdown("\n".join(f"- {s}" for s in fb["improvements"]))
    if fb.get("missed_opportunity"):
        st.subheader(tr("missed"))
        st.write(fb["missed_opportunity"])

    with st.expander(tr("hidden_reveal_heading")):
        st.write(tr("hidden_reveal", list=CASE["list_price"], floor_std=CASE["floor_standard"],
                    floor_best=CASE["floor_best"]))


# ---------------------------------------------------------------------------
# Layout: avatar on the left, conversation on the right
# ---------------------------------------------------------------------------
st.title(tr("title"))
if S.feedback is not None:
    show_feedback()
    st.divider()
left, right = st.columns([5, 7], gap="large")

with left:
    with st.container(key="avatar_panel"):
        avatar_slot = st.empty()
        avatar_slot.html(avatar_html(), unsafe_allow_javascript=True)
        end_slot = st.empty()

S.autoplay_id = None   # it has been rendered once; don't autoplay again on the next rerun

with right:
    st.subheader(tr("conversation"))
    with st.chat_message("assistant", avatar="🧑‍💼"):
        st.markdown(f"**{tr('supplier_name')}**  \n{tr('opening_line')}")
    for m in S.messages:
        if m["role"] == "user":
            with st.chat_message("user", avatar="🙂"):
                tag = f"  ·  🎙️ _{tr('said_by_voice')}_" if m.get("voice") else ""
                st.markdown(f"**{tr('you_name')}**{tag}  \n{m['content']}")
        else:
            with st.chat_message("assistant", avatar="🧑‍💼"):
                st.markdown(f"**{tr('supplier_name')}**  \n{m['content']}")

    if S.error:
        st.error(S.error)
        S.error = None
    if S.notice:
        st.info(S.notice)
        S.notice = None


# ---------------------------------------------------------------------------
# Input (text or voice), or feedback once finished
# ---------------------------------------------------------------------------
def handle_input(value):
    text = (value.text or "").strip() if hasattr(value, "text") else str(value).strip()
    via_voice = False

    if getattr(value, "audio", None) is not None:
        audio_bytes = value.audio.getvalue()
        if len(audio_bytes) > config.MAX_RECORDING_BYTES:
            S.error = tr("recording_too_long")
            return
        avatar_slot.html(avatar_html(waiting=True, waiting_text=tr("listening")),
                         unsafe_allow_javascript=True)
        heard = transcribe(audio_bytes, value.audio.type or "audio/wav", S.session_id)
        add_usage(heard)
        if not heard.text:
            S.error = tr("couldnt_hear")
            return
        text = (text + " " + heard.text).strip()
        via_voice = True

    if not text:
        return
    if len(text) > config.MAX_MESSAGE_CHARS:
        S.error = tr("message_too_long", n=config.MAX_MESSAGE_CHARS)
        return

    if not S.started_logged:   # count a session only once the student engages
        log_event(S.session_id, "started", S.lang)
        S.started_logged = True

    S.messages.append({"role": "user", "content": text, "voice": via_voice})
    avatar_slot.html(avatar_html(waiting=True, waiting_text=tr("thinking")),
                     unsafe_allow_javascript=True)
    try:
        supplier_reply()
    except ModelUnavailable:
        # Take the message back out so the conversation stays consistent,
        # and show it so the student can resend it.
        lost = S.messages.pop()["content"]
        S.error = f"{tr('model_error')}\n\n> {lost}"


if S.feedback is None:
    if student_turns() >= config.MAX_STUDENT_TURNS:
        st.info(tr("turn_limit_reached"))
    else:
        value = st.chat_input(tr("input_placeholder"), max_chars=config.MAX_MESSAGE_CHARS,
                              accept_audio=True)
        if value:
            try:
                handle_input(value)
            except ModelUnavailable:
                S.error = tr("model_error")
            st.rerun()

    if student_turns() > 0:
        if end_slot.button(tr("end_button"), help=tr("end_help"), type="primary", width="stretch"):
            try:
                with st.spinner(tr("grading")):
                    S.feedback = grade()
                fb = S.feedback
                log_event(S.session_id, "completed", S.lang, student_turns(),
                          deal_reached=fb.get("deal_reached", ""),
                          price_per_kg=fb.get("price_per_kg") or "",
                          score=fb.get("score") or "")
            except ModelUnavailable:
                S.error = tr("model_error")
            st.rerun()
