"""Human-in-the-loop: a reviewer approves or rejects an extraction held in the review queue.

Approved rows enter the gold views (and so the exposure totals); rejected rows stay out.
`extract --redo` re-extracts from bronze and therefore resets these decisions.
"""

import duckdb

from mock491.schemas import ReviewStatus


def _move(con: duckdb.DuckDBPyConnection, extraction_id: str, to: ReviewStatus,
          allowed_from: tuple[ReviewStatus, ...]) -> bool:  # fmt: skip
    changed = con.execute(
        "UPDATE extractions SET status = ? WHERE extraction_id = ? AND list_contains(?, status) "
        "RETURNING extraction_id",
        [to.value, extraction_id, [s.value for s in allowed_from]],
    ).fetchall()
    return bool(changed)


def decide(con: duckdb.DuckDBPyConnection, extraction_id: str, approve: bool) -> bool:
    """Returns False if the extraction is not (or no longer) waiting for review."""
    status = ReviewStatus.APPROVED if approve else ReviewStatus.REJECTED
    return _move(con, extraction_id, status, (ReviewStatus.PENDING_REVIEW,))


def reopen(con: duckdb.DuckDBPyConnection, extraction_id: str) -> bool:
    """Undo a decision: put an approved or rejected extraction back in the queue."""
    return _move(con, extraction_id, ReviewStatus.PENDING_REVIEW,
                 (ReviewStatus.APPROVED, ReviewStatus.REJECTED))  # fmt: skip
