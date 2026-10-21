"""What a question may see: a few gold-level tables, copied into a locked, in-memory sandbox.

Each question runs in its own throwaway DuckDB that holds only these tables, already filtered to
the caller's subsidiary scope. The sandbox has no path back to the warehouse and no file or
network access, so even a wrong or malicious query can only read what is listed here.
"""

from dataclasses import dataclass

import duckdb


@dataclass(frozen=True)
class Table:
    name: str
    description: str
    source: str  # SELECT over the warehouse; must expose tenant_id for scoping
    columns: dict[str, str]  # column -> meaning, for the model's prompt


TABLES = [
    Table(
        "records",
        "Approved documents (auto-approved or approved by a reviewer): one row per contract or "
        "invoice line. This is what every exposure figure is built from.",
        """
        SELECT g.tenant_id, g.doc_type, g.document_ref, g.document_date,
               ent.canonical_name AS counterparty, g.master_entity_id,
               g.counterparty_name AS name_as_written, g.counterparty_vkn AS vkn,
               g.amount, g.currency, g.amount_try, g.penalty_rate_daily, g.paid
        FROM gold_extractions g JOIN entities ent USING (master_entity_id)
        """,
        {
            "tenant_id": "subsidiary id, e.g. HOLDING_ENERJI_AS",
            "doc_type": "'contract' or 'invoice'",
            "document_ref": "contract or invoice number",
            "document_date": "DATE the document was issued (may be NULL)",
            "counterparty": "resolved company name (golden record); use this to group by company",
            "master_entity_id": "golden record id",
            "name_as_written": "the company name exactly as written in the document",
            "vkn": "tax number as written (may be NULL)",
            "amount": "amount in the document's own currency",
            "currency": "'TRY', 'USD' or 'EUR'",
            "amount_try": "amount converted to Turkish lira; use for any total or comparison",
            "penalty_rate_daily": "contracts only: daily late-payment penalty as a fraction "
            "(0.005 = 0.5%/day); NULL for invoices",
            "paid": "invoices only: TRUE if paid, FALSE if open; NULL for contracts",
        },
    ),
    Table(
        "counterparties",
        "One row per company (golden record) with its approved exposure across subsidiaries.",
        """
        SELECT ent.master_entity_id, ent.canonical_name AS counterparty, ent.vkn,
               count(DISTINCT g.tenant_id) AS subsidiary_count,
               count(*) AS document_count, sum(g.amount_try) AS exposure_try,
               max(g.penalty_rate_daily) AS max_penalty_rate_daily
        FROM gold_extractions g JOIN entities ent USING (master_entity_id)
        WHERE {scope}
        GROUP BY ALL
        """,
        {
            "master_entity_id": "golden record id",
            "counterparty": "resolved company name",
            "vkn": "tax number (NULL if no valid one was found)",
            "subsidiary_count": "how many subsidiaries deal with this company",
            "document_count": "approved documents",
            "exposure_try": "total approved amount in Turkish lira",
            "max_penalty_rate_daily": "highest daily penalty rate in its contracts (fraction)",
        },
    ),
    Table(
        "subsidiaries",
        "One row per subsidiary with its approved exposure.",
        """
        SELECT tenant_id, count(*) AS document_count, sum(amount_try) AS exposure_try,
               count(DISTINCT master_entity_id) AS counterparty_count
        FROM gold_extractions GROUP BY tenant_id
        """,
        {
            "tenant_id": "subsidiary id, e.g. HOLDING_ENERJI_AS",
            "document_count": "approved documents",
            "exposure_try": "total approved amount in Turkish lira",
            "counterparty_count": "distinct companies it deals with",
        },
    ),
    Table(
        "pending_review",
        "Documents that scored below the confidence threshold and wait for a person. They are "
        "NOT included in records, counterparties or subsidiaries.",
        """
        SELECT e.tenant_id, e.doc_type, e.document_ref, e.counterparty_name AS name_as_written,
               ent.canonical_name AS counterparty, e.counterparty_vkn AS vkn, e.amount,
               e.currency, e.amount * fx.rate_to_try AS amount_try, e.confidence,
               array_to_string(e.issues, ', ') AS reasons
        FROM extractions e JOIN fx_rates fx USING (currency)
        LEFT JOIN entities ent USING (master_entity_id)
        WHERE e.status = 'pending_review'
        """,
        {
            "tenant_id": "subsidiary id",
            "doc_type": "'contract' or 'invoice'",
            "document_ref": "contract or invoice number",
            "name_as_written": "company name as written",
            "counterparty": "company it was matched to",
            "vkn": "tax number as written (may be NULL)",
            "amount": "amount in its own currency",
            "currency": "'TRY', 'USD' or 'EUR'",
            "amount_try": "amount in Turkish lira",
            "confidence": "extraction confidence, 0-1",
            "reasons": "why it is held: vkn_missing, vkn_checksum, ...",
        },
    ),
]

TABLE_NAMES = frozenset(t.name for t in TABLES)


def _scoped(table: Table, tenant: str | None) -> str:
    """The table's SELECT, restricted to one subsidiary when a scope is set."""
    if "{scope}" in table.source:  # pre-aggregated: scope must apply before grouping
        cond = "TRUE" if tenant is None else "g.tenant_id = $tenant"
        return table.source.format(scope=cond)
    if tenant is None:
        return table.source
    return f"SELECT * FROM ({table.source}) WHERE tenant_id = $tenant"


def sandbox(warehouse: duckdb.DuckDBPyConnection, tenant: str | None) -> duckdb.DuckDBPyConnection:
    """A fresh in-memory database holding only TABLES (scoped), with external access locked."""
    box = duckdb.connect(":memory:")
    for table in TABLES:
        params = {"tenant": tenant} if "$tenant" in _scoped(table, tenant) else {}
        df = warehouse.execute(_scoped(table, tenant), params).df()
        box.register("_incoming", df)
        box.execute(f"CREATE TABLE {table.name} AS SELECT * FROM _incoming")
        box.unregister("_incoming")
    box.execute("SET enable_external_access = false")
    box.execute("SET lock_configuration = true")
    return box


def schema_prompt(box: duckdb.DuckDBPyConnection) -> str:
    """Table and column descriptions (with types from the sandbox) for the model."""
    parts = []
    for table in TABLES:
        types = dict(
            box.execute(
                f"SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_name = '{table.name}'"
            ).fetchall()
        )
        cols = "\n".join(
            f"  - {c} ({types.get(c, '?')}): {meaning}" for c, meaning in table.columns.items()
        )
        parts.append(f"TABLE {table.name}: {table.description}\n{cols}")
    tenants = [
        t for (t,) in box.execute("SELECT DISTINCT tenant_id FROM records ORDER BY 1").fetchall()
    ]
    parts.append("Subsidiary ids present: " + (", ".join(tenants) or "(none)"))
    return "\n\n".join(parts)
