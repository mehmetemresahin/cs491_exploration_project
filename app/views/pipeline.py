"""Data & quality: what each layer holds, and how well the pipeline did against the answer key."""

import pandas as pd
import streamlit as st

from mock491 import config, queries
from ui import components as ui
from ui import data, state
from ui import format as fmt

tenant = state.scope()
counts = data.load(queries.layer_counts, tenant)

ui.page_header("Data & quality", f"The pipeline's layers for {state.scope_name()}, and how its "
               "output scores against the mock dataset's ground truth.")  # fmt: skip

ui.kpi_row([
    ui.Kpi("1 · Bronze files", str(counts["bronze_files"]),
           "Raw documents, stored read-only under their SHA-256."),
    ui.Kpi("2 · Silver extractions", str(counts["extractions"]),
           "Validated records read from the documents, each with lineage and a confidence."),
    ui.Kpi("3 · Golden records", str(counts["entities"]),
           "Companies after entity resolution."),
    ui.Kpi("4 · Gold rows", str(counts["gold_rows"]),
           "Extractions counted in the KPIs: auto-approved or approved by a person."),
])  # fmt: skip

statuses = data.load(queries.status_counts, tenant)
st.markdown(" ".join(
    ui.status_badge(s, n)
    for s, n in zip(statuses["status"], statuses["n"], strict=True) if s in fmt.STATUS
))  # fmt: skip

st.subheader("Quality against ground truth")
scores = data.load(queries.evaluation, config.MOCK_DIR) if tenant is None else None
if tenant is not None:
    st.caption("Shown for the whole holding only. Switch the scope in the sidebar.")
elif scores is None:
    st.caption(f"No `ground_truth.json` in `{config.MOCK_DIR}`. Run `python -m mock491 generate`.")
else:
    extraction, entities = scores
    checked = sum(f.total for f in extraction.fields)
    fields_correct = sum(f.correct for f in extraction.fields) / checked if checked else 0.0
    ui.kpi_row([
        ui.Kpi("Records found", f"{extraction.recall:.0%}",
               f"{extraction.matched} of {extraction.truth_records} records in the answer key."),
        ui.Kpi("Fields correct", f"{fields_correct:.0%}",
               "Across every field and document type."),
        ui.Kpi("Matching precision", f"{entities.precision:.0%}",
               "Of the record pairs linked to one company, how many truly are the same company."),
        ui.Kpi("Matching recall", f"{entities.recall:.0%}",
               "Of the record pairs that are the same company, how many were linked."),
    ])  # fmt: skip
    left, right = st.columns([3, 2], gap="large")
    with left:
        fields = pd.DataFrame(
            [(fmt.DOC_TYPES.get(f.doc_type, f.doc_type), f.field.replace("_", " "), f.accuracy,
              f"{f.correct}/{f.total}") for f in extraction.fields],
            columns=["doc_type", "field", "accuracy", "correct"],
        ).sort_values(["doc_type", "field"])  # fmt: skip
        ui.table(fields, ["doc_type", "field", "accuracy", "correct"], overrides={
            "field": st.column_config.TextColumn("Field"),
            "accuracy": st.column_config.ProgressColumn("Accuracy", min_value=0.0, max_value=1.0,
                                                        format="percent"),
            "correct": st.column_config.TextColumn("Correct"),
        })  # fmt: skip
    with right:
        problems = [("Wrong merge", " | ".join(n)) for n in entities.wrong_merges]
        problems += [("Split", " | ".join(n)) for n in entities.split_entities]
        if problems:
            for kind, names in problems:
                st.error(f"**{kind}:** {names}", icon=":material/call_split:")
        else:
            st.success("No wrong merges and no split companies.", icon=":material/verified:")
        st.caption("These scores are against our own generator's templates: they prove the "
                   "plumbing, not real-world accuracy. Make the generator messier or swap in an "
                   "LLM extractor and this page shows what breaks.")  # fmt: skip

st.subheader("Browse the layers")
silver, gold, bronze = st.tabs(["Silver: extractions", "Golden records", "Bronze: files"])
with silver:
    ui.table(data.load(queries.extractions, tenant),
             ["tenant_id", "doc_type", "document_ref", "document_date", "counterparty_name",
              "counterparty_vkn", "amount", "currency", "paid", "confidence", "issues", "status"],
             height=420)  # fmt: skip
with gold:
    ui.table(
        data.load(queries.entities, tenant),
        ["canonical_name", "vkn", "tenants", "document_count", "spellings"],
        height=420,
    )
with bronze:
    files = data.load(queries.bronze_files, tenant)
    ui.table(files, ["tenant_id", "original_name", "size_bytes", "sha256", "ingested_at"],
             height=420, overrides={
                 "original_name": st.column_config.TextColumn("File", width="medium"),
                 "size_bytes": st.column_config.NumberColumn("Bytes", format="localized"),
                 "sha256": st.column_config.TextColumn("SHA-256", width="small"),
                 "ingested_at": st.column_config.DatetimeColumn("Ingested",
                                                                format="DD.MM.YYYY HH:mm"),
             })  # fmt: skip
