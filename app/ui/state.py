"""Cross-page state: the subsidiary scope (sidebar) and the counterparty being viewed."""

import streamlit as st

from ui import format as fmt

SCOPE_KEY = "scope"
ENTITY_KEY = "entity"
HOLDING = ""  # scope option for the whole holding (None would render as a clearable box)

# Page files, as registered in app/main.py; used for st.switch_page.
OVERVIEW = "views/overview.py"
COUNTERPARTIES = "views/counterparties.py"
REVIEW = "views/review.py"
PIPELINE = "views/pipeline.py"
ASK = "views/ask.py"


def scope_selector(tenants: list[str]) -> None:
    st.selectbox(
        "Viewing as",
        [HOLDING, *tenants],
        format_func=lambda t: "Whole holding" if t == HOLDING else f"{fmt.tenant_label(t)} only",
        key=SCOPE_KEY,
        help="Narrow every page to one subsidiary: the mock's stand-in for row-level security.",
    )


def scope() -> str | None:
    """The selected tenant id, or None for the holding-wide view."""
    return st.session_state.get(SCOPE_KEY) or None


def scope_name() -> str:
    tenant = scope()
    return "the whole holding" if tenant is None else fmt.tenant_label(tenant)


def open_counterparty(entity_id: str) -> None:
    st.session_state[ENTITY_KEY] = entity_id
    st.switch_page(COUNTERPARTIES)


def counterparty() -> str | None:
    return st.session_state.get(ENTITY_KEY)
