"""DuckDB warehouse: one file standing in for MinIO-metadata + PostgreSQL + dbt."""

from importlib.resources import files
from pathlib import Path

import duckdb

from mock491 import config
from mock491.schemas import Extraction

SQL_FILES = ("silver.sql", "gold.sql")


def connect(path: Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = path or config.WAREHOUSE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def init_db(con: duckdb.DuckDBPyConnection) -> None:
    for name in SQL_FILES:
        con.execute(files("mock491.sql").joinpath(name).read_text(encoding="utf-8"))


def save_extraction(con: duckdb.DuckDBPyConnection, ext: Extraction) -> None:
    con.execute(
        """
        INSERT OR REPLACE INTO extractions (
            extraction_id, sha256, tenant_id, doc_type, document_ref, document_date,
            counterparty_name, counterparty_vkn, amount, currency, penalty_rate_daily, paid,
            page_number, bounding_box, row_number, confidence, issues, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ext.extraction_id,
            ext.lineage.sha256,
            ext.tenant_id,
            ext.doc_type.value,
            ext.document_ref,
            ext.document_date,
            ext.counterparty_name,
            ext.counterparty_vkn,
            ext.financials.amount,
            ext.financials.currency,
            ext.financials.penalty_rate_daily,
            ext.paid,
            ext.lineage.page_number,
            list(ext.lineage.bounding_box) if ext.lineage.bounding_box else None,
            ext.lineage.row_number,
            ext.lineage.confidence,
            ext.lineage.issues,
            ext.initial_status.value,
        ],
    )


def table_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    tables = ("bronze_files", "extractions", "entities", "gold_review_queue")
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
