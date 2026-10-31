"""
Run with:  pytest -q
These run offline: the AI is replaced with scripted replies.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["LLM_PROVIDER"] = "fake"

import pytest

import engine
import llm
import scenarios as sc


def run(coro):
    return asyncio.run(coro)


async def collect(gen):
    return [ev async for ev in gen]


def scripted(*replies):
    """Replace the chat model with replies given in order, streamed in small chunks."""
    calls = {"n": 0, "systems": []}

    async def fake_stream(system, history, session_id, audio=None, usage=None, temperature=0.7):
        calls["systems"].append(system)
        text = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        for i in range(0, len(text), 5):
            yield text[i:i + 5]

    return fake_stream, calls


@pytest.fixture
def supplier():
    return engine.new_session(sc.get("supplier-negotiation"), "en")


# --- parsing --------------------------------------------------------------------
def test_parse_tags():
    assert sc.parse_tags("[mood: Firm] [offer: QAR 52.5]") == ("firm", 52.5)
    assert sc.parse_tags("[offer: 14,500] [mood: pleased]") == ("pleased", 14500.0)
    assert sc.parse_tags("no tags") == ("neutral", None)
    assert sc.parse_tags("[mood: furious]") == ("neutral", None)     # unknown mood -> neutral


def test_header_split_across_chunks(supplier, monkeypatch):
    fake, _ = scripted("[mood: thinking] [offer: 52]\nThat price reflects our quality.")
    monkeypatch.setattr(llm, "chat_stream", fake)
    events = run(collect(engine.run_turn(supplier, text="Hello", voice_on=False)))
    done = events[-1]
    assert done["mood"] == "thinking"
    assert done["text"] == "That price reflects our quality."
    assert supplier.position == 52


def test_tags_on_same_line_as_text(supplier, monkeypatch):
    fake, _ = scripted("[mood: firm] [offer: 52] I can't do that.")
    monkeypatch.setattr(llm, "chat_stream", fake)
    done = run(collect(engine.run_turn(supplier, text="Hi", voice_on=False)))[-1]
    assert done["text"] == "I can't do that." and done["mood"] == "firm"


# --- the offer rules are enforced in code ----------------------------------------------
def test_no_concession_on_first_message(supplier, monkeypatch):
    fake, calls = scripted("[mood: pleased] [offer: 48]\nSure, 48.",
                           "[mood: firm] [offer: 52]\nMy price is 52.")
    monkeypatch.setattr(llm, "chat_stream", fake)
    done = run(collect(engine.run_turn(supplier, text="Lower please", voice_on=False)))[-1]
    assert calls["n"] == 2                          # first reply rejected, regenerated
    assert "CORRECTION" in calls["systems"][1]
    assert supplier.position == 52 and "52" in done["text"]


def test_step_too_big_is_rejected(supplier, monkeypatch):
    supplier.messages = [{"role": "user", "content": "x"},
                         {"role": "assistant", "content": "52.", "mood": "firm", "offer": 52}]
    supplier.position = 52
    fake, calls = scripted("[mood: pleased] [offer: 45]\nOk 45.", "[mood: thinking] [offer: 51]\n51, if you pay fast.")
    monkeypatch.setattr(llm, "chat_stream", fake)
    run(collect(engine.run_turn(supplier, text="I'll pay in 7 days", voice_on=False)))
    assert supplier.position == 51


def test_never_past_limit_even_if_model_keeps_trying(supplier, monkeypatch):
    supplier.messages = [{"role": "user", "content": "x"},
                         {"role": "assistant", "content": "39.", "mood": "firm", "offer": 39}]
    supplier.position = 39
    fake, calls = scripted("[mood: pleased] [offer: 37]\nFine, 37.")   # always breaks the rule
    monkeypatch.setattr(llm, "chat_stream", fake)
    done = run(collect(engine.run_turn(supplier, text="37?", voice_on=False)))[-1]
    assert calls["n"] == 2                          # two tries, then a fixed holding line
    assert "39" in done["text"] and supplier.position == 39


def test_salary_direction_up():
    o = sc.get("salary-negotiation").offer
    assert sc.check_offer(o, 14000, 14000, 1) is None
    assert sc.check_offer(o, 14500, 14000, 2) is None
    assert sc.check_offer(o, 15500, 14000, 2) is not None     # step too big
    assert sc.check_offer(o, 16500, 16000, 3) is not None     # past the ceiling


# --- voice turns -----------------------------------------------------------------------
def test_voice_turn_reads_heard_line(supplier, monkeypatch):
    fake, _ = scripted("Heard: I can pay within a week.\n[mood: thinking] [offer: 52]\nInteresting. Tell me more.")
    monkeypatch.setattr(llm, "chat_stream", fake)
    events = run(collect(engine.run_turn(supplier, audio=(b"RIFF", "audio/wav"), voice_on=False)))
    heard = [e for e in events if e["type"] == "heard"]
    assert heard and heard[0]["text"] == "I can pay within a week."
    assert supplier.messages[-2]["content"] == "I can pay within a week."
    assert supplier.messages[-2]["voice"] is True


def test_sentences_are_voiced_in_order(supplier, monkeypatch):
    fake, _ = scripted("[mood: firm] [offer: 52]\nFirst sentence here. Second one! And a third?")
    monkeypatch.setattr(llm, "chat_stream", fake)
    spoken = []

    async def fake_speak(text, lang, gender, mood, sid):
        spoken.append(text)
        return b"x", "audio/wav", 0.0

    monkeypatch.setattr(llm, "speak", fake_speak)
    events = run(collect(engine.run_turn(supplier, text="Hi", voice_on=True)))
    seqs = [e["seq"] for e in events if e["type"] == "audio"]
    assert spoken == ["First sentence here.", "Second one!", "And a third?"]
    assert seqs == [0, 1, 2]


# --- arithmetic ---------------------------------------------------------------------------
def test_outcome_numbers():
    o = sc.get("supplier-negotiation").offer
    n = sc.outcome_numbers(o, 41)
    assert n["total"] == 41 * 1200
    assert n["vs_target"] == (45 - 41) * 1200          # better than target
    assert n["left_on_table"] == (41 - 38) * 1200
    s = sc.get("salary-negotiation").offer
    n = sc.outcome_numbers(s, 15500)
    assert n["vs_target"] == -(16500 - 15500) * 12     # short of target
    assert n["left_on_table"] == (16000 - 15500) * 12


def test_hidden_fields_not_public():
    for s in sc.load_all():
        view = sc.public_view(s, "en")
        assert not {"persona", "private_info", "rubric", "offer", "goal", "reveal"} & set(view)
