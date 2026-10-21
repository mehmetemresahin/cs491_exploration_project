"""IDP stage: bronze files -> validated Extraction records in silver."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from mock491 import db
from mock491.extract import contracts, invoices
from mock491.extract.common import ExtractionError
from mock491.schemas import Extraction, ReviewStatus

Extractor = Callable[[Path, str, str], list[Extraction]]

EXTRACTORS: dict[str, Extractor] = {
    ".pdf": contracts.extract,
    ".xlsx": invoices.extract,
}


@dataclass
class RunStats:
    files: int = 0
    records: int = 0
    pending_review: int = 0
    skipped: list[str] = field(default_factory=list)  # no extractor for this file type
    failed: list[tuple[str, str]] = field(default_factory=list)


def run(con: duckdb.DuckDBPyConnection, redo: bool = False) -> RunStats:
    """Extract every bronze file not yet extracted (all of them with redo=True).

    redo replaces earlier rows, which also discards any review decisions on them.
    """
    query = "SELECT sha256, tenant_id, original_name, uri FROM bronze_files"
    if not redo:
        query += " WHERE sha256 NOT IN (SELECT sha256 FROM extractions)"
    stats = RunStats()
    for sha, tenant, name, uri in con.execute(query + " ORDER BY uri").fetchall():
        path = Path(uri)
        extractor = EXTRACTORS.get(path.suffix.lower())
        if extractor is None:
            stats.skipped.append(name)
            continue
        try:
            records = extractor(path, sha, tenant)
        except ExtractionError as e:
            stats.failed.append((name, str(e)))
            continue
        if redo:
            con.execute("DELETE FROM extractions WHERE sha256 = ?", [sha])
        for ext in records:
            db.save_extraction(con, ext)
        stats.files += 1
        stats.records += len(records)
        stats.pending_review += sum(r.initial_status is ReviewStatus.PENDING_REVIEW
                                    for r in records)  # fmt: skip
    return stats
