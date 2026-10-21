"""Overview: the consolidated answer: how much do we owe whom, across all subsidiaries."""

import streamlit as st

from mock491 import queries
from ui import charts, data, state
from ui import components as ui
from ui import format as fmt

TOP_N = 10

tenant = state.scope()
k = data.load(queries.kpis, tenant)
all_tenants = data.load(queries.tenants)

ui.page_header(
    "Overview",
    f"Approved counterparty exposure for {state.scope_name()}, consolidated across "
    "subsidiaries by golden record.",
)
ui.kpi_row([
    ui.Kpi("Approved exposure", fmt.money(k["exposure_try"]),
           f"{fmt.plural(k['documents'], 'document')}, converted to TRY at mock FX rates."),
    ui.Kpi("Counterparties", str(k["counterparties"]),
           "Golden records: one per real company, however its name was written."),
    ui.Kpi("Shared across subsidiaries", str(k["shared_counterparties"]),
           "Counterparties that more than one subsidiary deals with. Invisible without "
           "entity resolution."),
    ui.Kpi("Awaiting review", str(k["pending_reviews"]),
           f"{fmt.money(k['pending_exposure_try'])} is held out of the totals until a person "
           "approves it."),
])  # fmt: skip

if k["pending_reviews"]:
    with st.container(border=True):
        text, action = st.columns([5, 1], vertical_alignment="center")
        text.markdown(
            f":material/schedule: **{fmt.plural(k['pending_reviews'], 'record')}** "
            f"({fmt.money(k['pending_exposure_try'])}) scored below the confidence threshold and "
            "are not in these numbers yet."
        )
        if action.button("Review now", type="primary", width="stretch"):
            st.switch_page(state.REVIEW)

exposure = data.load(queries.exposure, tenant)
if exposure.empty:
    ui.empty_state("No approved exposure yet", "Run `extract` and `resolve`, or approve records "
                   "in the review queue.")  # fmt: skip
    st.stop()

left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader(f"Top {min(TOP_N, len(exposure))} counterparties")
    st.caption("Each bar is one company; the segments show which subsidiaries carry the exposure.")
    charts.exposure_by_counterparty(data.load(queries.exposure_split, tenant, TOP_N), all_tenants)
with right:
    st.subheader("By subsidiary")
    st.caption("Approved exposure each subsidiary carries.")
    charts.exposure_by_tenant(data.load(queries.exposure_by_tenant, tenant), all_tenants)

st.subheader("All counterparties")
st.caption("Click a row to open the counterparty's profile.")
event = ui.table(
    exposure,
    ["canonical_name", "vkn", "tenants", "document_count", "exposure_try",
     "max_penalty_rate_daily"],
    key="overview-table",
    select=True,
)  # fmt: skip
if (row := ui.selected_row(event, exposure)) is not None:
    st.session_state.pop("overview-table", None)  # don't reopen on return
    state.open_counterparty(row["master_entity_id"])
