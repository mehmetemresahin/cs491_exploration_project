"""Curated questions with known-good SQL.

They serve three purposes: few-shot examples in the model's prompt, one-click starters in the
UI, and answers that work with no model configured. tests/test_genbi.py runs every one.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Example:
    question: str
    sql: str


EXAMPLES = [
    Example(
        "Which 10 counterparties carry the most exposure?",
        "SELECT counterparty, subsidiary_count, exposure_try\n"
        "FROM counterparties\nORDER BY exposure_try DESC\nLIMIT 10",
    ),
    Example(
        "How much exposure does each subsidiary carry?",
        "SELECT tenant_id, exposure_try, counterparty_count\n"
        "FROM subsidiaries\nORDER BY exposure_try DESC",
    ),
    Example(
        "Which companies work with every subsidiary?",
        "SELECT counterparty, exposure_try\nFROM counterparties\n"
        "WHERE subsidiary_count = (SELECT count(*) FROM subsidiaries)\n"
        "ORDER BY exposure_try DESC",
    ),
    Example(
        "Which unpaid invoices are the largest?",
        "SELECT counterparty, tenant_id, document_ref, amount, currency, amount_try\n"
        "FROM records\nWHERE doc_type = 'invoice' AND NOT paid\n"
        "ORDER BY amount_try DESC\nLIMIT 10",
    ),
    Example(
        "Which contracts have the highest daily penalty?",
        "SELECT counterparty, tenant_id, document_ref, penalty_rate_daily, amount_try\n"
        "FROM records\nWHERE doc_type = 'contract'\n"
        "ORDER BY penalty_rate_daily DESC, amount_try DESC\nLIMIT 10",
    ),
    Example(
        "How is our exposure split by currency?",
        "SELECT currency, sum(amount) AS amount, sum(amount_try) AS exposure_try\n"
        "FROM records\nGROUP BY currency\nORDER BY exposure_try DESC",
    ),
    Example(
        "What is waiting for review, and why?",
        "SELECT counterparty, tenant_id, document_ref, amount_try, reasons\n"
        "FROM pending_review\nORDER BY amount_try DESC",
    ),
    Example(
        "Durdu Enerji ile toplam ne kadar iş yapıyoruz?",
        "SELECT counterparty, subsidiary_count, document_count, exposure_try\n"
        "FROM counterparties\n"
        "WHERE strip_accents(lower(counterparty)) LIKE '%durdu enerji%'",
    ),
]


def _key(text: str) -> str:
    return " ".join(text.lower().split()).rstrip("?")


def find(question: str) -> Example | None:
    """The curated example with this exact question (ignoring case, spacing and '?')."""
    return next((e for e in EXAMPLES if _key(e.question) == _key(question)), None)
