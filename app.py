"""
Entry point. Run with:  streamlit run app.py

Sets up the two pages and their names in the sidebar.
"""

import streamlit as st

from i18n import t

st.set_page_config(page_title="Negotiation Practice", page_icon="🤝", layout="wide")

lang = st.session_state.get("lang", "en")
page = st.navigation([
    st.Page("practice.py", title=t("nav_practice", lang), icon="🤝", default=True, url_path="practice"),
    st.Page("insights.py", title=t("nav_insights", lang), icon="📊", url_path="insights"),
])
page.run()
