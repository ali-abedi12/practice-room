# Negotiation Practice

A practice tool for business students. The student plays a café owner negotiating a coffee supply contract. An AI plays Yousef, the supplier, who has a hidden minimum price and a reason to give a better deal that the student has to discover. When the student ends the negotiation, a second AI call reviews the conversation as an instructor would and gives a score, specific feedback, and what was left on the table.

- **Talk or type.** Press the microphone in the message box to speak. The recording is transcribed (English or Arabic) and sent like a typed message.
- **Yousef talks back.** His replies are read aloud, and an animated avatar shows his mood (neutral, pleased, considering, firm) and moves its mouth in time with the audio.
- **English and Arabic** throughout, including right-to-left layout.

## Run it

You need Python 3.10 or newer and a free Gemini API key from https://aistudio.google.com/apikey.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then paste your key into .env
streamlit run app.py
```

It opens at http://localhost:8501. The **Insights** page is in the sidebar.

Use **Chrome or Edge** for the demo. The microphone needs permission the first time; allow it when the browser asks. Voice works on `localhost` without HTTPS, but a deployed version must be served over HTTPS for the microphone to work.

To try it without a key, set `LLM_PROVIDER=fake` in `.env`. You'll get canned replies, which is only useful for checking the screens work.

## How it's put together

| File | What it does |
|---|---|
| `app.py` | Entry point: sets up the two pages |
| `practice.py` | The negotiation screen: avatar, conversation, voice input, feedback |
| `insights.py` | Usage and results: sessions, deal rate, average score, AI cost |
| `avatar.py` | Yousef's face: four moods, blinking, a thinking state, and lip-sync driven by the audio volume |
| `llm.py` | Every AI call goes through here: chat, grading, transcription and speech. Handles retries, timeouts and fallbacks, and logs tokens, cost and response time per call |
| `config.py` | Which model does which job, prices, and limits |
| `scenario.py` | The case: numbers, the supplier's hidden instructions, the grading rubric. A new case is a new copy of this file |
| `strings/en.json`, `strings/ar.json` | All interface text. A new language is one more file; no code changes |
| `tracking.py` | Logs session events for the Insights page |

## Design decisions

- **One place for AI calls.** Changing model or provider touches `llm.py` and `config.py` only.
- **Two models.** The chat runs on a cheaper, faster model because it's called on every message. Grading runs once per session on a stronger model.
- **Cost is visible.** Each call's estimated cost is logged, and each session shows its running total. Estimates use paid-tier rates so the numbers can be used to budget for a full class.
- **The maths isn't done by the AI.** The AI reads the agreed terms out of the conversation. Contract value, savings and money left on the table are calculated in Python.
- **Guardrails.** The supplier stays in character and won't reveal its instructions. Each session is capped at 20 messages of 1,000 characters to keep costs predictable.
- **Voice has a fallback chain.** Speech is tried with Gemini's TTS model first, then Microsoft Edge's free voices (which include a Qatari Arabic voice). If both fail, Yousef replies in text and the student sees a short notice. The negotiation never stops because of voice.
- **Mood drives the face and the voice.** Yousef tags each reply with a mood. The tag is stripped from the text, changes the avatar's expression, and sets the speaking style.
- **Graceful failure.** If the model is slow or unavailable, the app retries twice, then shows a plain message and gives the student their unsent text back.
- **Privacy.** Logs store counts, scores, timings and costs, never what students typed. Sessions use random IDs, not names. The API key lives in `.env` (or Streamlit secrets), which is excluded from git.
- **Accessibility.** Everything Yousef says is also shown as text, so audio is never the only channel. Voice can be switched off. The avatar has a text description for screen readers, his latest line is announced as it arrives, the Play button works from the keyboard, and animations stop for users who have reduced motion turned on. Mood is shown as a word as well as a colour.

## Known limits

- This is a prototype built in one evening. The screens, voice recording, lip-sync and fallbacks were tested in a browser with offline stand-in replies; the live Gemini and Edge voice calls have not been tested yet.
- Edge voices use an unofficial interface to Microsoft's read-aloud service. Fine for a demo, not for production.
- If a browser blocks autoplay, Yousef's line shows a Play button instead.
- Logs are CSV files on the server. For real use they'd move to a database.
- The free Gemini tier may use inputs to improve Google's products. A real deployment with student data should use the paid tier, or a provider covered by the university's data agreement.
- Accessibility hasn't been formally audited against WCAG 2.1 AA yet.
- No login. A real deployment would sit behind university single sign-on.
