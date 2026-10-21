"""Score silver extractions against the mock ground truth (report section 7, rows 1-2)."""

from dataclasses import dataclass

import duckdb

from mock491.mockgen import GroundTruth

# truth field -> extractions column, per doc type
FIELDS = {
    "name_as_written": "counterparty_name",
    "vkn_as_written": "counterparty_vkn",
    "amount": "amount",
    "currency": "currency",
    "document_date": "document_date",
}
CONTRACT_FIELDS = {"penalty_rate_daily": "penalty_rate_daily", "page_number": "page_number"}
INVOICE_FIELDS = {"paid": "paid", "row_number": "row_number"}
BBOX_MIN_IOU = 0.5


@dataclass
class FieldScore:
    doc_type: str
    field: str
    correct: int
    total: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


@dataclass
class Report:
    truth_records: int
    extracted_records: int
    matched: int
    fields: list[FieldScore]
    review_by_issue: dict[str, int]

    @property
    def recall(self) -> float:
        return self.matched / self.truth_records if self.truth_records else 0.0

    @property
    def precision(self) -> float:
        return self.matched / self.extracted_records if self.extracted_records else 0.0


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def _same(expected, actual) -> bool:
    if isinstance(expected, float) and actual is not None:
        return abs(expected - actual) < 0.005
    return expected == actual


def evaluate(con: duckdb.DuckDBPyConnection, truth: GroundTruth) -> Report:
    cur = con.execute("SELECT * FROM extractions")
    cols = [d[0] for d in cur.description]
    rows = (dict(zip(cols, row, strict=True)) for row in cur.fetchall())
    extracted = {(r["tenant_id"], r["document_ref"]): r for r in rows}

    counts: dict[tuple[str, str], list[int]] = {}
    matched = 0
    for t in truth.records:
        got = extracted.get((t.tenant_id, t.record_id))
        if got is None:
            continue
        matched += 1
        fields = FIELDS | (CONTRACT_FIELDS if t.doc_type == "contract" else INVOICE_FIELDS)
        checks = {f: _same(getattr(t, f), got[col]) for f, col in fields.items()}
        if t.bounding_box:
            checks["bounding_box"] = bool(got["bounding_box"]) and (
                iou(t.bounding_box, got["bounding_box"]) >= BBOX_MIN_IOU
            )
        for f, ok in checks.items():
            c = counts.setdefault((t.doc_type.value, f), [0, 0])
            c[0] += ok
            c[1] += 1

    review = con.execute(
        "SELECT issue, count(*) FROM (SELECT unnest(issues) AS issue FROM extractions "
        "WHERE status = 'pending_review') GROUP BY issue ORDER BY 2 DESC"
    ).fetchall()
    return Report(
        truth_records=len(truth.records),
        extracted_records=len(extracted),
        matched=matched,
        fields=[FieldScore(d, f, c, n) for (d, f), (c, n) in counts.items()],
        review_by_issue=dict(review),
    )


@dataclass
class EntityReport:
    """Pairwise clustering scores: every pair of records is either linked or not."""

    true_entities: int
    predicted_entities: int
    tp: int
    fp: int  # pairs linked that belong to different companies (wrong merges)
    fn: int  # pairs of the same company left apart (missed merges)
    wrong_merges: list[list[str]]  # names in predicted entities that mix companies
    split_entities: list[list[str]]  # names of true companies spread over several entities

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def evaluate_entities(con: duckdb.DuckDBPyConnection, truth: GroundTruth) -> EntityReport:
    predicted = dict(
        ((t, ref), (ent, name))
        for t, ref, ent, name in con.execute(
            "SELECT tenant_id, document_ref, master_entity_id, counterparty_name FROM extractions"
        ).fetchall()
    )
    pairs = [(t.entity_id, *predicted[(t.tenant_id, t.record_id)])
             for t in truth.records if (t.tenant_id, t.record_id) in predicted]  # fmt: skip

    tp = fp = fn = 0
    for i, (true_a, pred_a, _) in enumerate(pairs):
        for true_b, pred_b, _ in pairs[i + 1 :]:
            same_true, same_pred = true_a == true_b, pred_a == pred_b
            tp += same_true and same_pred
            fp += same_pred and not same_true
            fn += same_true and not same_pred

    def names_by(key: int, members: int) -> dict[str, dict[str, list[str]]]:
        out: dict[str, dict[str, list[str]]] = {}
        for p in pairs:
            out.setdefault(p[key], {}).setdefault(p[members], []).append(p[2])
        return out

    by_pred, by_true = names_by(1, 0), names_by(0, 1)
    return EntityReport(
        true_entities=len(by_true),
        predicted_entities=len(by_pred),
        tp=tp,
        fp=fp,
        fn=fn,
        wrong_merges=[sorted({n for ns in g.values() for n in ns})
                      for g in by_pred.values() if len(g) > 1],
        split_entities=[[ns[0] for ns in g.values()] for g in by_true.values() if len(g) > 1],
    )  # fmt: skip


def format_entity_report(r: EntityReport) -> str:
    lines = [
        f"entities  true {r.true_entities}  predicted {r.predicted_entities}",
        f"pairwise  precision {r.precision:.1%}  recall {r.recall:.1%}  F1 {r.f1:.3f}  "
        f"(wrong-merge pairs {r.fp}, missed pairs {r.fn})",
    ]
    for names in r.wrong_merges:
        lines.append(f"  WRONG MERGE: {' | '.join(names)}")
    for names in r.split_entities:
        lines.append(f"  split:       {' | '.join(names)}")
    return "\n".join(lines)


def format_report(r: Report) -> str:
    lines = [
        f"records   truth {r.truth_records}  extracted {r.extracted_records}  "
        f"matched {r.matched}  recall {r.recall:.1%}  precision {r.precision:.1%}",
        "",
        f"{'doc type':<10}{'field':<20}{'accuracy':>10}{'correct':>10}",
    ]
    for s in sorted(r.fields, key=lambda s: (s.doc_type, s.field)):
        lines.append(f"{s.doc_type:<10}{s.field:<20}{s.accuracy:>10.1%}{s.correct:>6}/{s.total}")
    lines += ["", "routed to human review, by reason:"]
    lines += [f"  {issue:<20}{n:>4}" for issue, n in r.review_by_issue.items()] or ["  (none)"]
    return "\n".join(lines)
