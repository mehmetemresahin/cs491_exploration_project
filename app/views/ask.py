"""Ask: plain-language questions over the gold layer (Text-to-SQL), with the SQL always shown."""

import pandas as pd
import streamlit as st

from mock491 import config, genbi
from mock491.genbi import catalog, examples, llm
from ui import charts, data, state
from ui import components as ui

HISTORY_KEY = "ask-history"
AUTHORS = {"example": "a curated example", "you": "you"}  # otherwise the model's name
MAX_HISTORY = 12


@st.cache_resource(ttl=30, show_spinner=False)
def model_status() -> llm.Status:
    return llm.configured()


def chart_for(rows: pd.DataFrame) -> None:
    """A ranked bar chart when the result is 'label + number' with a handful of rows."""
    if not 2 <= len(rows) <= 25:
        return
    numeric = [c for c in rows.columns if pd.api.types.is_numeric_dtype(rows[c])]
    labels = [c for c in rows.columns if c not in numeric]
    if not numeric or not labels:
        return
    value = next((c for c in numeric if c.endswith("_try")), numeric[-1])
    charts.ranked_bar(rows, labels[0], value, money=value.endswith("_try"))


def show_answer(answer: genbi.Answer) -> None:
    with st.chat_message("user"):
        st.markdown(answer.question or "*(your SQL)*")
    with st.chat_message("assistant", avatar=":material/database:"):
        if answer.explanation:
            st.markdown(answer.explanation)
        if answer.error and answer.source == "none":  # expected without a model, not a failure
            st.info(answer.error, icon=":material/info:")
        elif answer.error:
            st.error(answer.error, icon=":material/error:")
        elif answer.rows is not None:
            if answer.rows.empty:
                st.caption("The query ran and returned no rows.")
            else:
                chart_for(answer.rows)
                ui.table(answer.rows, list(answer.rows.columns))
                if answer.truncated:
                    st.caption(f"Showing the first {len(answer.rows)} rows.")
        if answer.sql:
            retries = len(answer.attempts) - 1
            author = AUTHORS.get(answer.source, answer.source)
            label = f"SQL · written by {author}" + (
                f" · fixed after {retries} failed attempt" if retries > 0 else ""
            )
            with st.expander(label, icon=":material/code:"):
                st.code(answer.sql, language="sql")


def remember(answer: genbi.Answer) -> None:
    history = st.session_state.setdefault(HISTORY_KEY, [])
    history.append(answer)
    del history[:-MAX_HISTORY]


def run_question(question: str, model: llm.SqlModel | None) -> None:
    with st.spinner("Writing SQL…" if model else "Running…"), data.connection() as con:
        remember(genbi.ask(con, question, state.scope(), model))


def run_sql(sql: str) -> None:
    with data.connection() as con:
        remember(genbi.run_sql(con, sql, state.scope()))


status = model_status()
ui.page_header(
    "Ask the data",
    f"Questions are answered from the approved (gold) data for {state.scope_name()}. A model "
    "writes the SQL; you always see the SQL and the rows it returned.",
)

with st.container(border=True):
    if status.model:
        st.markdown(f":green-badge[:material/check_circle: Model ready] {status.detail}")
    else:
        st.markdown(
            ":gray-badge[:material/power_off: No model] Example questions and your own SQL "
            f"still work. {status.detail}"
        )
        with st.expander("Connect a model"):
            st.markdown(
                "**Local (recommended, nothing leaves this machine):** install "
                "[Ollama](https://ollama.com), then `ollama pull "
                f"{config.OLLAMA_MODEL}`. It is picked up automatically. Another model: set "
                "`MOCK491_OLLAMA_MODEL`.\n\n"
                '**Anthropic API:** `pip install -e ".[llm]"`, set `ANTHROPIC_API_KEY` (or run '
                "`ant auth login`) and `MOCK491_LLM=anthropic`, then restart the app. The "
                "question and the table descriptions are sent to the API; the data is not.\n\n"
                "Either way, the SQL runs in a locked sandbox that only holds the four tables "
                "below, already filtered to the subsidiary in the sidebar."
            )

history: list[genbi.Answer] = st.session_state.get(HISTORY_KEY, [])
for answer in history:
    show_answer(answer)

if not history:
    ui.empty_state(
        "Ask about exposure, counterparties, invoices or the review queue",
        "Pick an example to see how it works, or type your own question below. Questions can be "
        "in English or Turkish.",
        icon=":material/forum:",
    )
picked = st.pills(
    "Examples",
    [e.question for e in examples.EXAMPLES],
    key=f"ask-example-{len(history)}",  # a fresh widget per turn, so it starts unselected
    label_visibility="collapsed" if history else "visible",
)

left, right = st.columns([3, 1], vertical_alignment="center")
with left, st.expander("Write SQL yourself", icon=":material/terminal:"):
    tables = ", ".join(f"`{t.name}`" for t in catalog.TABLES)
    st.caption(f"One SELECT over {tables}. DuckDB dialect.")
    last_sql = next((a.sql for a in reversed(history) if a.sql), examples.EXAMPLES[0].sql)
    sql = st.text_area("SQL", last_sql, height=140, label_visibility="collapsed")
    manual = st.button("Run SQL", icon=":material/play_arrow:")
with right:
    if history and st.button("Clear conversation", icon=":material/delete_sweep:", width="stretch"):
        st.session_state.pop(HISTORY_KEY, None)
        st.rerun()

with st.expander("What can be asked: the tables", icon=":material/table_chart:"):
    for table in catalog.TABLES:
        st.markdown(f"**`{table.name}`**: {table.description}")
        st.caption(" · ".join(f"`{c}`" for c in table.columns))

question = st.chat_input(
    "Ask a question…" if status.model else "Ask one of the example questions, or connect a model"
)
if question or picked:
    run_question(question or picked, status.model)
    st.rerun()
if manual and sql.strip():
    run_sql(sql)
    st.rerun()
