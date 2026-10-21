"""Holding risk app: `streamlit run app/main.py` from the project root.

This file only wires navigation and the sidebar. Each page lives in views/, built from ui/.
To add a page: create views/<name>.py and register it in PAGES below.
"""

import streamlit as st

from mock491 import queries
from ui import components as ui
from ui import data, state

st.set_page_config(page_title="Holding Risk · CS491 Mock", page_icon=":material/account_balance:",
                   layout="wide")  # fmt: skip

PAGES = {
    "Monitor": [
        st.Page(state.OVERVIEW, title="Overview", icon=":material/space_dashboard:", default=True),
        st.Page(
            state.COUNTERPARTIES,
            title="Counterparties",
            icon=":material/domain:",
            url_path="counterparties",
        ),
    ],
    "Explore": [
        st.Page(state.ASK, title="Ask the data", icon=":material/forum:", url_path="ask"),
    ],
    "Act": [
        st.Page(state.REVIEW, title="Review queue", icon=":material/fact_check:", url_path="review")
    ],
    "Inspect": [
        st.Page(
            state.PIPELINE, title="Data & quality", icon=":material/account_tree:", url_path="data"
        )
    ],
}
page = st.navigation(PAGES)

with st.sidebar:
    st.markdown("### :material/account_balance: Örnek Holding")
    st.caption("Consolidated counterparty risk across subsidiaries")
    if data.ready():
        state.scope_selector(data.load(queries.tenants))
    st.divider()
    st.caption("Exploration mock for CS491. All companies and documents are synthetic.")

if not data.ready():
    ui.page_header("Holding Risk", "No warehouse yet.")
    ui.empty_state(
        "Build the mock warehouse first",
        "Run from the project root: `python -m mock491 init`, `generate`, "
        "`ingest data/mock --by-folder`, `extract`, `resolve`. Then reload this page.",
        icon=":material/construction:",
    )
    st.stop()

page.run()
