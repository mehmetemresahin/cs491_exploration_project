"""Counterparties: one golden record, every source record behind it."""

import streamlit as st

from mock491 import queries
from mock491.extract.common import fold
from ui import components as ui
from ui import data, state
from ui import format as fmt

tenant = state.scope()
companies = data.load(queries.entities, tenant)
totals = data.load(queries.exposure, tenant).set_index("master_entity_id")["exposure_try"]
companies = companies.assign(exposure_try=companies["master_entity_id"].map(totals).fillna(0.0))
companies = companies.sort_values("exposure_try", ascending=False, ignore_index=True)

ui.page_header("Counterparties", f"Golden records for {state.scope_name()}: each one gathers "
               "every record of the same company, however it was written.")  # fmt: skip
if companies.empty:
    ui.empty_state("No counterparties yet", "Run `extract` and `resolve` first.")
    st.stop()

left, right = st.columns([5, 7], gap="large")
with left:
    query = st.text_input("Search", placeholder="Name or VKN", label_visibility="collapsed",
                          icon=":material/search:")  # fmt: skip
    listing = companies
    if query:
        needle = fold(query)
        listing = companies[
            companies["canonical_name"].map(fold).str.contains(needle, regex=False)
            | companies["vkn"].fillna("").str.contains(query.strip(), regex=False)
        ]
        listing = listing.reset_index(drop=True)  # fmt: skip
    event = ui.table(
        listing,
        ["canonical_name", "exposure_try"],
        key=f"cp-list-{query}",
        select=True,
        height=560,
        overrides={"canonical_name": st.column_config.TextColumn("Counterparty")},
    )
    found = fmt.plural(len(listing), "counterparty", "counterparties")
    st.caption(f"{found}. Matching ignores case and Turkish letters.")

if (row := ui.selected_row(event, listing)) is not None:
    st.session_state[state.ENTITY_KEY] = row["master_entity_id"]
entity_id = state.counterparty()
if entity_id not in set(companies["master_entity_id"]):
    entity_id = companies["master_entity_id"].iloc[0]

with right:
    profile = data.load(queries.entity, entity_id)
    records = data.load(queries.entity_records, entity_id, tenant)
    approved = records[records["status"].isin(["auto_approved", "approved"])]

    st.subheader(profile["canonical_name"])
    st.caption(f"VKN {profile['vkn']}" if profile["vkn"] else "No valid VKN on any record: "
               "grouped by name only")  # fmt: skip
    ui.tenant_badges(sorted(records["tenant_id"].unique()))
    ui.kpi_row([
        ui.Kpi("Exposure", fmt.money(approved["amount_try"].sum()), "Approved records only."),
        ui.Kpi("Records", str(len(records)), f"{len(approved)} counted, "
               f"{len(records) - len(approved)} pending or rejected"),
        ui.Kpi("Subsidiaries", str(records["tenant_id"].nunique())),
        ui.Kpi("Spellings", str(records["name_as_written"].nunique()),
               "Different ways the name was written in the source documents."),
    ])  # fmt: skip

    tab_records, tab_names = st.tabs(["Source records", "Written as"])
    with tab_names:
        spellings = (records.groupby("name_as_written").size().rename("n")
                     .sort_values(ascending=False).reset_index())  # fmt: skip
        ui.table(spellings, ["name_as_written", "n"])
        st.caption("Entity resolution linked all of these to one company: by VKN where it was "
                   "valid, otherwise by a careful name match.")  # fmt: skip
    with tab_records:
        st.caption("Click a record to see where it was read from.")
        rec_event = ui.table(
            records,
            ["tenant_id", "doc_type", "document_ref", "name_as_written", "amount", "currency",
             "status"],
            key=f"records-{entity_id}",
            select=True,
            height=280,
        )  # fmt: skip
        if (rec := ui.selected_row(rec_event, records)) is not None:
            src = data.load(queries.source, rec["extraction_id"])
            with st.container(border=True):
                st.markdown(
                    f"**{rec['document_ref']}** · {fmt.amount(rec['amount'], rec['currency'])} "
                    f"{ui.status_badge(rec['status'])}"
                )
                ui.source_viewer(src)
