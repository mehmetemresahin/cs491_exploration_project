"""Review queue: a person checks low-confidence extractions against their source."""

import streamlit as st

from mock491 import config, queries, review
from ui import components as ui
from ui import data, state
from ui import format as fmt

QUEUE_KEY = "queue"

tenant = state.scope()
queue = data.load(queries.review_queue, tenant)
done = data.load(queries.decided, tenant)

ui.page_header(
    "Review queue",
    f"Extractions scoring below {config.HITL_CONFIDENCE_THRESHOLD} confidence wait here and stay "
    "out of the exposure until a person approves them.",
)

if note := st.session_state.pop("review-note", None):
    st.toast(note, icon=":material/check:")

total = len(queue) + len(done)
if total:
    st.progress(len(done) / total, text=f"{len(done)} of {fmt.plural(total, 'record')} reviewed")

if queue.empty:
    ui.empty_state("All clear", "Nothing is waiting for review in this scope.",
                   icon=":material/task_alt:")  # fmt: skip
else:
    left, right = st.columns([2, 3], gap="large")
    with left:
        st.caption("Least confident first. Pick a record, or work from the top.")
        event = ui.table(queue, ["counterparty_name", "issues"],
                         key=QUEUE_KEY, select=True)  # fmt: skip
    item = ui.selected_row(event, queue)
    item = queue.iloc[0] if item is None else item
    position = queue.index[queue["extraction_id"] == item["extraction_id"]][0] + 1

    with right, st.container(border=True):
        src = data.load(queries.source, item["extraction_id"])
        st.caption(f"Record {position} of {len(queue)}")
        st.subheader(item["counterparty_name"])
        st.markdown(
            f":gray-badge[{fmt.DOC_TYPES[item['doc_type']]} {item['document_ref']}] "
            f":gray-badge[{fmt.tenant_label(item['tenant_id'])}] "
            f":orange-badge[:material/speed: confidence {item['confidence']:.2f}]"
        )
        for code in item["issues"]:
            label, why = fmt.ISSUES.get(code, (code, ""))
            st.warning(f"**{label}.** {why}", icon=":material/report:")

        ui.field_grid({
            "Amount": fmt.amount(item["amount"], item["currency"]),
            "VKN as written": fmt.text(item["counterparty_vkn"]),
            "Matched to": fmt.text(item["matched_entity"]),
            "Document date": f"{src['document_date']:%d.%m.%Y}" if src["document_date"] else "",
            "Penalty / day": f"{src['penalty_rate_daily']:.2%}"
            if src["penalty_rate_daily"] is not None else "",
            "In TRY": fmt.money(item["amount_try"]),
        })  # fmt: skip

        approve, reject = st.columns(2)
        decision = None
        if approve.button(
            "Approve",
            type="primary",
            icon=":material/check:",
            width="stretch",
            help="Values match the source: count this record in the exposure.",
        ):
            decision = True
        if reject.button(
            "Reject",
            icon=":material/close:",
            width="stretch",
            help="Values are wrong or unusable: keep this record out.",
        ):
            decision = False  # fmt: skip
        if decision is not None:
            data.write(review.decide, item["extraction_id"], decision)
            verb = "Approved" if decision else "Rejected"
            st.session_state["review-note"] = f"{verb}: {item['counterparty_name']}"
            st.session_state.pop(QUEUE_KEY, None)  # move on to the next record
            st.rerun()

        st.divider()
        ui.source_viewer(src)

if not done.empty:
    with st.expander(f"Decided ({len(done)})"):
        st.caption("Select a decision to undo it.")
        event = ui.table(done, ["counterparty_name", "status", "amount_try", "tenant_id"],
                         key="decided", select=True)  # fmt: skip
        if (row := ui.selected_row(event, done)) is not None and st.button(
            f"Reopen {row['counterparty_name']}", icon=":material/undo:"
        ):
            data.write(review.reopen, row["extraction_id"])
            st.session_state["review-note"] = f"Back in the queue: {row['counterparty_name']}"
            st.session_state.pop("decided", None)
            st.rerun()
