import pytest

from mock491 import bronze, evaluate, extract, vkn
from mock491.extract.common import ExtractionError, fold, parse_tr_number
from mock491.extract.invoices import map_headers


@pytest.fixture
def extracted(con, dataset, tmp_path):
    out, truth = dataset
    for tenant in truth.tenants:
        for f in sorted((out / tenant).rglob("*.*")):
            bronze.ingest_file(con, f, tenant, tmp_path / "bronze")
    stats = extract.run(con)
    assert not stats.failed and not stats.skipped
    return con, truth


def test_pipeline_reproduces_ground_truth(extracted):
    con, truth = extracted
    report = evaluate.evaluate(con, truth)
    assert report.recall == report.precision == 1.0
    wrong = [(s.doc_type, s.field) for s in report.fields if s.accuracy < 1.0]
    assert wrong == []


def test_review_queue_holds_exactly_the_bad_vkns(extracted):
    con, truth = extracted
    expected = {r.record_id for r in truth.records
                if not r.vkn_as_written or not vkn.is_valid(r.vkn_as_written)}  # fmt: skip
    rows = con.execute("SELECT document_ref FROM extractions WHERE status = 'pending_review'")
    queued = {ref for (ref,) in rows.fetchall()}
    assert queued == expected


def test_redo_does_not_duplicate(extracted):
    con, truth = extracted
    extract.run(con, redo=True)
    assert con.execute("SELECT count(*) FROM extractions").fetchone()[0] == len(truth.records)


@pytest.mark.parametrize(
    "text, value",
    [("2.829.919,03", 2829919.03), ("250.000,00", 250000.0), ("0,5", 0.5), ("1500", 1500.0)],
)
def test_parse_tr_number(text, value):
    assert parse_tr_number(text) == value


def test_parse_tr_number_rejects_english_format():
    with pytest.raises(ExtractionError):
        parse_tr_number("2,829,919.03")


def test_header_matching_ignores_case_and_turkish_letters():
    assert fold("TEDARIKCI_UNVANI") == fold("Tedarikçi Unvanı")
    assert map_headers(["FATURA_NO", "TEDARIKCI_UNVANI", "TUTAR"]) == {
        "invoice_no": 0, "name": 1, "amount": 2,
    }  # fmt: skip
    with pytest.raises(ExtractionError, match="name"):
        map_headers(["Fatura No", "Müşteri", "Tutar"])
