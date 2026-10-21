"""Read-side queries behind the UI (and later an API or Text-to-SQL).

Plain functions over a DuckDB connection that return DataFrames or plain values, so any front end
can reuse them. `tenant=None` is the holding-wide view; a tenant id narrows every number to that
subsidiary (the mock's stand-in for row-level security).
"""

from pathlib import Path

import duckdb
import pandas as pd

from mock491 import evaluate, mockgen


def _scope(alias: str) -> str:
    return f"($tenant IS NULL OR {alias}.tenant_id = $tenant)"


def _df(con: duckdb.DuckDBPyConnection, sql: str, **params) -> pd.DataFrame:
    return con.execute(sql, params).df()


def tenants(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [t for (t,) in con.execute("SELECT DISTINCT tenant_id FROM bronze_files ORDER BY 1")
            .fetchall()]  # fmt: skip


def kpis(con: duckdb.DuckDBPyConnection, tenant: str | None = None) -> dict:
    exposure, counterparties, documents = con.execute(
        f"SELECT coalesce(sum(amount_try), 0), count(DISTINCT master_entity_id), count(*) "
        f"FROM gold_extractions g WHERE {_scope('g')}",
        {"tenant": tenant},
    ).fetchone()
    (shared,) = con.execute(
        f"""
        SELECT count(*) FROM (
            SELECT master_entity_id FROM gold_extractions
            GROUP BY 1 HAVING count(DISTINCT tenant_id) >= 2
        ) WHERE master_entity_id IN (
            SELECT master_entity_id FROM gold_extractions g WHERE {_scope("g")}
        )
        """,
        {"tenant": tenant},
    ).fetchone()
    pending, held = con.execute(
        f"SELECT count(*), coalesce(sum(e.amount * fx.rate_to_try), 0) "
        f"FROM extractions e JOIN fx_rates fx USING (currency) "
        f"WHERE e.status = 'pending_review' AND {_scope('e')}",
        {"tenant": tenant},
    ).fetchone()
    return {
        "exposure_try": exposure,
        "counterparties": counterparties,
        "documents": documents,
        "shared_counterparties": shared,  # also used by at least one other subsidiary
        "pending_reviews": pending,
        "pending_exposure_try": held,  # held out of the exposure until reviewed
    }


def exposure(con: duckdb.DuckDBPyConnection, tenant: str | None = None) -> pd.DataFrame:
    """One row per golden record with approved exposure in scope, largest first."""
    return _df(
        con,
        f"""
        SELECT ent.master_entity_id, ent.canonical_name, ent.vkn,
               count(DISTINCT g.tenant_id) AS tenant_count,
               list(DISTINCT g.tenant_id ORDER BY g.tenant_id) AS tenants,
               count(*) AS document_count,
               sum(g.amount_try) AS exposure_try,
               max(g.penalty_rate_daily) AS max_penalty_rate_daily
        FROM gold_extractions g JOIN entities ent USING (master_entity_id)
        WHERE {_scope("g")}
        GROUP BY ALL
        ORDER BY exposure_try DESC, ent.canonical_name
        """,
        tenant=tenant,
    )


def exposure_split(con: duckdb.DuckDBPyConnection, tenant: str | None = None,
                   top: int = 10) -> pd.DataFrame:  # fmt: skip
    """Long form (counterparty x subsidiary) for the `top` counterparties by exposure."""
    return _df(
        con,
        f"""
        WITH scoped AS (SELECT * FROM gold_extractions g WHERE {_scope("g")}),
        ranked AS (
            SELECT master_entity_id, sum(amount_try) AS total FROM scoped
            GROUP BY 1 ORDER BY total DESC LIMIT $top
        )
        SELECT ent.master_entity_id, ent.canonical_name, s.tenant_id,
               sum(s.amount_try) AS exposure_try, r.total AS entity_total
        FROM scoped s JOIN ranked r USING (master_entity_id)
        JOIN entities ent USING (master_entity_id)
        GROUP BY ALL
        ORDER BY entity_total DESC, s.tenant_id
        """,
        tenant=tenant,
        top=top,
    )


def exposure_by_tenant(con: duckdb.DuckDBPyConnection,
                       tenant: str | None = None) -> pd.DataFrame:  # fmt: skip
    return _df(
        con,
        f"""
        SELECT tenant_id, count(*) AS document_count, sum(amount_try) AS exposure_try
        FROM gold_extractions g WHERE {_scope("g")}
        GROUP BY 1 ORDER BY exposure_try DESC
        """,
        tenant=tenant,
    )


def entity(con: duckdb.DuckDBPyConnection, entity_id: str) -> dict | None:
    row = con.execute(
        "SELECT master_entity_id, canonical_name, vkn FROM entities WHERE master_entity_id = ?",
        [entity_id],
    ).fetchone()
    return (
        dict(zip(("master_entity_id", "canonical_name", "vkn"), row, strict=True)) if row else None
    )


def entity_records(con: duckdb.DuckDBPyConnection, entity_id: str,
                   tenant: str | None = None) -> pd.DataFrame:  # fmt: skip
    """Every extraction linked to a golden record, whatever its review status."""
    return _df(
        con,
        f"""
        SELECT e.extraction_id, e.tenant_id, e.doc_type, e.document_ref, e.document_date,
               e.counterparty_name AS name_as_written, e.counterparty_vkn AS vkn_as_written,
               e.amount, e.currency, e.amount * fx.rate_to_try AS amount_try,
               e.penalty_rate_daily, e.confidence, e.issues, e.status
        FROM extractions e JOIN fx_rates fx USING (currency)
        WHERE e.master_entity_id = $entity AND {_scope("e")}
        ORDER BY e.tenant_id, e.document_ref
        """,
        entity=entity_id,
        tenant=tenant,
    )


def review_queue(con: duckdb.DuckDBPyConnection, tenant: str | None = None) -> pd.DataFrame:
    """Pending extractions, least confident first."""
    return _df(con, _REVIEWABLE.format(scope=_scope("e")) + " AND e.status = 'pending_review' "
               "ORDER BY e.confidence, e.extraction_id", tenant=tenant)  # fmt: skip


def decided(con: duckdb.DuckDBPyConnection, tenant: str | None = None) -> pd.DataFrame:
    """Extractions a person has approved or rejected."""
    return _df(con, _REVIEWABLE.format(scope=_scope("e")) + " AND e.status IN "
               "('approved', 'rejected') ORDER BY e.status, e.counterparty_name",
               tenant=tenant)  # fmt: skip


_REVIEWABLE = """
    SELECT e.extraction_id, e.tenant_id, e.doc_type, e.document_ref, e.counterparty_name,
           e.counterparty_vkn, e.amount, e.currency, e.amount * fx.rate_to_try AS amount_try,
           e.confidence, e.issues, e.status, ent.canonical_name AS matched_entity
    FROM extractions e JOIN fx_rates fx USING (currency)
    LEFT JOIN entities ent USING (master_entity_id)
    WHERE {scope}
"""


def source(con: duckdb.DuckDBPyConnection, extraction_id: str) -> dict | None:
    """An extraction with its lineage: which bronze file, and where in it."""
    cur = con.execute(
        "SELECT e.*, b.uri, b.original_name FROM extractions e JOIN bronze_files b USING (sha256) "
        "WHERE e.extraction_id = ?",
        [extraction_id],
    )
    row = cur.fetchone()
    return dict(zip([d[0] for d in cur.description], row, strict=True)) if row else None


def layer_counts(con: duckdb.DuckDBPyConnection, tenant: str | None = None) -> dict[str, int]:
    sql = {
        "bronze_files": f"SELECT count(*) FROM bronze_files b WHERE {_scope('b')}",
        "extractions": f"SELECT count(*) FROM extractions e WHERE {_scope('e')}",
        "entities": f"SELECT count(DISTINCT master_entity_id) FROM extractions e "
        f"WHERE {_scope('e')}",
        "gold_rows": f"SELECT count(*) FROM gold_extractions g WHERE {_scope('g')}",
    }
    return {k: con.execute(q, {"tenant": tenant}).fetchone()[0] for k, q in sql.items()}


def status_counts(con: duckdb.DuckDBPyConnection, tenant: str | None = None) -> pd.DataFrame:
    return _df(con, f"SELECT status, count(*) AS n FROM extractions e WHERE {_scope('e')} "
               "GROUP BY 1 ORDER BY 2 DESC", tenant=tenant)  # fmt: skip


def extractions(con: duckdb.DuckDBPyConnection, tenant: str | None = None) -> pd.DataFrame:
    return _df(
        con,
        f"""
        SELECT e.extraction_id, e.tenant_id, e.doc_type, e.document_ref, e.document_date,
               e.counterparty_name, e.counterparty_vkn, e.amount, e.currency,
               e.penalty_rate_daily, e.paid, e.confidence, e.issues, e.status,
               e.master_entity_id, e.page_number, e.row_number
        FROM extractions e WHERE {_scope("e")}
        ORDER BY e.tenant_id, e.document_ref
        """,
        tenant=tenant,
    )


def entities(con: duckdb.DuckDBPyConnection, tenant: str | None = None) -> pd.DataFrame:
    return _df(
        con,
        f"""
        SELECT ent.master_entity_id, ent.canonical_name, ent.vkn,
               count(*) AS document_count,
               count(DISTINCT e.counterparty_name) AS spellings,
               count(DISTINCT e.tenant_id) AS tenant_count,
               list(DISTINCT e.tenant_id ORDER BY e.tenant_id) AS tenants
        FROM entities ent JOIN extractions e USING (master_entity_id)
        WHERE {_scope("e")}
        GROUP BY ALL ORDER BY ent.canonical_name
        """,
        tenant=tenant,
    )


def bronze_files(con: duckdb.DuckDBPyConnection, tenant: str | None = None) -> pd.DataFrame:
    return _df(con, f"SELECT * FROM bronze_files b WHERE {_scope('b')} "
               "ORDER BY tenant_id, original_name", tenant=tenant)  # fmt: skip


def evaluation(con: duckdb.DuckDBPyConnection, mock_dir: Path):
    """Scores against the generator's answer key, or None when there is no ground truth."""
    if not (mock_dir / "ground_truth.json").exists():
        return None
    truth = mockgen.load_truth(mock_dir)
    return evaluate.evaluate(con, truth), evaluate.evaluate_entities(con, truth)
