"""GenBI: ask the gold layer a question in plain language (report section 5, Text-to-SQL).

question -> model drafts SQL -> guard checks it -> runs in a scoped sandbox -> rows.
A failing draft is sent back to the model once with the error. Without a model, curated example
questions and hand-written SQL still work through the same guard and sandbox.
"""

from dataclasses import dataclass, field

import duckdb
import pandas as pd

from mock491.genbi import catalog, examples, guard
from mock491.genbi.llm import Draft, ModelError, SqlModel

MAX_ATTEMPTS = 2

RULES = """\
You translate questions about a holding company's counterparty risk into one DuckDB SQL query.

Rules:
- Return exactly one SELECT statement (CTEs allowed). Use only the tables and columns below.
- For money totals and comparisons use amount_try / exposure_try (Turkish lira), not amount.
- Match company names loosely: strip_accents(lower(counterparty)) LIKE '%...%' with a lowercase,
  accent-free search term, because names are written in many ways.
- Unless the user asks for everything, add ORDER BY and LIMIT 20.
- Give readable column names; keep tenant_id when showing subsidiaries.
- If the tables cannot answer the question, return sql as "" and say why in explanation.
- Write the explanation in the language of the question, in one or two sentences, describing what
  the query returns (not how SQL works).
"""


@dataclass
class Answer:
    question: str
    source: str  # who wrote the SQL: a model's name, "example" or "you"
    sql: str = ""
    explanation: str = ""
    rows: pd.DataFrame | None = None
    truncated: bool = False
    error: str | None = None
    attempts: list[str] = field(default_factory=list)  # every SQL tried, for transparency


def system_prompt(box: duckdb.DuckDBPyConnection) -> str:
    shots = "\n\n".join(f"Question: {e.question}\nSQL:\n{e.sql}" for e in examples.EXAMPLES)
    return f"{RULES}\n{catalog.schema_prompt(box)}\n\nExamples:\n\n{shots}"


def _execute(box: duckdb.DuckDBPyConnection, answer: Answer) -> Answer:
    answer.attempts.append(answer.sql)
    answer.sql = guard.check(answer.sql, catalog.TABLE_NAMES)
    answer.rows, answer.truncated = guard.run(box, answer.sql)
    answer.error = None  # an earlier attempt may have failed
    return answer


def run_sql(
    warehouse: duckdb.DuckDBPyConnection,
    sql: str,
    tenant: str | None = None,
    *,
    question: str = "",
    source: str = "you",
    explanation: str = "",
) -> Answer:
    """Run given SQL through the same guard and scoped sandbox the model's SQL uses."""
    answer = Answer(question, source, sql=sql, explanation=explanation)
    box = catalog.sandbox(warehouse, tenant)
    try:
        return _execute(box, answer)
    except (guard.UnsafeQuery, duckdb.Error) as e:
        answer.error = str(e)
        return answer
    finally:
        box.close()


def ask(
    warehouse: duckdb.DuckDBPyConnection,
    question: str,
    tenant: str | None = None,
    model: SqlModel | None = None,
) -> Answer:
    """Answer a question; without a model only the curated examples can be answered."""
    if model is None:
        if example := examples.find(question):
            return run_sql(warehouse, example.sql, tenant, question=question, source="example")
        return Answer(
            question,
            "none",
            error="No language model is configured, so only the "
            "example questions can be answered. You can also write SQL yourself.",
        )

    box = catalog.sandbox(warehouse, tenant)
    answer = Answer(question, model.name)
    turns = [{"role": "user", "content": question}]
    try:
        for _ in range(MAX_ATTEMPTS):
            try:
                draft: Draft = model.draft(system_prompt(box), turns)
            except ModelError as e:
                answer.error = str(e)
                return answer
            answer.sql, answer.explanation = draft.sql.strip(), draft.explanation
            if not answer.sql:
                return answer  # the model says the tables can't answer it
            try:
                return _execute(box, answer)
            except (guard.UnsafeQuery, duckdb.Error) as e:
                answer.error = str(e)
                turns += [
                    {"role": "assistant", "content": draft.model_dump_json()},
                    {
                        "role": "user",
                        "content": f"That query failed: {e}\nReturn a corrected "
                        "query for the same question.",
                    },
                ]
        return answer
    finally:
        box.close()
