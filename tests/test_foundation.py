import pytest
from pydantic import ValidationError

from mock491 import bronze, db
from mock491.schemas import DocType, Extraction, Financials, Lineage, ReviewStatus


def make_extraction(sha: str, **overrides) -> Extraction:
    fields = dict(
        extraction_id="EXT-1",
        tenant_id="HOLDING_ENERJI_AS",
        doc_type=DocType.CONTRACT,
        counterparty_name="Arçelik Pazarlama A.Ş.",
        counterparty_vkn="1234567890",
        financials=Financials(amount=250_000, currency="USD", penalty_rate_daily=0.005),
        lineage=Lineage(
            sha256=sha, page_number=4, bounding_box=(120.5, 450.2, 510, 495.8), confidence=0.94
        ),
    )
    return Extraction(**(fields | overrides))


def test_bronze_ingest_is_idempotent(con, tmp_path):
    src = tmp_path / "sozlesme.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    bronze_dir = tmp_path / "bronze"

    digest, new = bronze.ingest_file(con, src, "HOLDING_ENERJI_AS", bronze_dir)
    again, new_again = bronze.ingest_file(con, src, "HOLDING_ENERJI_AS", bronze_dir)

    assert new and not new_again and digest == again
    assert (bronze_dir / "HOLDING_ENERJI_AS" / f"{digest}.pdf").exists()


def test_vkn_must_be_ten_digits():
    with pytest.raises(ValidationError):
        make_extraction("0" * 64, counterparty_vkn="12345")


def test_low_confidence_goes_to_review():
    low = make_extraction("0" * 64)
    low.lineage.confidence = 0.6
    assert low.initial_status is ReviewStatus.PENDING_REVIEW


def test_report_walkthrough_totals_17_05m_try(con, tmp_path):
    """Section 5 of the report: one entity, two subsidiaries, 8.5M + 8.55M TRY."""
    shas = []
    for name in ("sozlesme.pdf", "faturalar.xlsx"):
        f = tmp_path / name
        f.write_bytes(name.encode())
        shas.append(bronze.ingest_file(con, f, "x", tmp_path / "bronze")[0])

    con.execute("INSERT INTO entities VALUES ('GLD_ENT_0042', 'Arçelik A.Ş.', '1234567890')")
    db.save_extraction(con, make_extraction(shas[0]))
    db.save_extraction(
        con,
        make_extraction(
            shas[1],
            extraction_id="EXT-2",
            tenant_id="HOLDING_LOJISTIK_AS",
            doc_type=DocType.INVOICE,
            counterparty_name="ARÇELİK AŞ",
            financials=Financials(amount=8_500_000, currency="TRY"),
        ),
    )
    con.execute("UPDATE extractions SET master_entity_id = 'GLD_ENT_0042'")

    row = con.execute(
        "SELECT tenant_count, total_exposure_try FROM gold_entity_exposure"
    ).fetchone()
    assert row == (2, pytest.approx(17_050_000))
