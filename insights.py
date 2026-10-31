"""
Insights page: what an instructor or the Center would look at.
Reads the two CSV logs and turns them into a few numbers.
"""

import os

import pandas as pd
import streamlit as st

from i18n import RTL_LANGUAGES, t
from llm import CALLS_LOG
from tracking import EVENTS_LOG

lang = st.session_state.get("lang", "en")


def tr(key, **v):
    return t(key, lang, **v)


if lang in RTL_LANGUAGES:
    st.markdown('<style>[data-testid="stMain"]{direction:rtl;text-align:right;}</style>',
                unsafe_allow_html=True)

st.title(tr("insights_title"))
st.caption(tr("insights_intro"))

if not os.path.exists(EVENTS_LOG) or not os.path.exists(CALLS_LOG):
    st.info(tr("no_data"))
    st.stop()

events = pd.read_csv(EVENTS_LOG)
calls = pd.read_csv(CALLS_LOG)

started = events[events.event == "started"].session_id.nunique()
done = events[events.event == "completed"]
completed = len(done)

deals = done[done.deal_reached.astype(str).str.lower() == "true"]
deal_rate = f"{len(deals) / completed:.0%}" if completed else "-"
scores = pd.to_numeric(done.score, errors="coerce").dropna()
prices = pd.to_numeric(deals.price_per_kg, errors="coerce").dropna()

ok_calls = calls[calls.status == "ok"]
total_cost = calls.cost_usd.sum()

c1, c2, c3 = st.columns(3)
c1.metric(tr("sessions_started"), started)
c2.metric(tr("sessions_completed"), completed)
c3.metric(tr("deal_rate"), deal_rate)

c4, c5, c6 = st.columns(3)
c4.metric(tr("avg_score"), f"{scores.mean():.1f}" if len(scores) else "-")
c5.metric(tr("avg_price"), f"{prices.mean():.1f}" if len(prices) else "-")
c6.metric(tr("avg_response_time"), f"{ok_calls.seconds.mean():.1f}s" if len(ok_calls) else "-")

c7, c8 = st.columns(2)
c7.metric(tr("total_cost"), f"${total_cost:.4f}")
c8.metric(tr("cost_per_session"), f"${total_cost / completed:.4f}" if completed else "-")

if len(scores):
    st.subheader(tr("score_distribution"))
    dist = scores.astype(int).value_counts().reindex(range(1, 11), fill_value=0)
    st.bar_chart(dist)

st.subheader(tr("recent_calls"))
st.dataframe(calls.tail(20).iloc[::-1], hide_index=True, width="stretch")
