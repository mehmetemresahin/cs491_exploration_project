import pytest

from mock491 import bronze, extract, resolve, review, sources


@pytest.fixture
def loaded(con, dataset, tmp_path):
    out, truth = dataset
    for tenant in truth.tenants:
        for f in sorted((out / tenant).rglob("*.*")):
            bronze.ingest_file(con, f, tenant, tmp_path / "bronze")
    extract.run(con)
    resolve.resolve(con)
    return con


def exposure_total(con):
    return con.execute("SELECT coalesce(sum(total_exposure_try), 0) FROM gold_entity_exposure"
                       ).fetchone()[0]  # fmt: skip


def first_pending(con):
    return con.execute(
        "SELECT extraction_id, amount * rate_to_try FROM extractions JOIN fx_rates USING (currency)"
        " WHERE status = 'pending_review' ORDER BY extraction_id LIMIT 1"
    ).fetchone()


def test_approve_moves_record_into_exposure(loaded):
    con = loaded
    before = exposure_total(con)
    extraction_id, amount_try = first_pending(con)
    assert review.decide(con, extraction_id, approve=True)
    assert exposure_total(con) == pytest.approx(before + amount_try)
    assert not review.decide(con, extraction_id, approve=False)  # already decided


def test_reject_keeps_record_out(loaded):
    con = loaded
    before = exposure_total(con)
    extraction_id, _ = first_pending(con)
    assert review.decide(con, extraction_id, approve=False)
    assert exposure_total(con) == pytest.approx(before)
    queue = con.execute("SELECT extraction_id FROM gold_review_queue").fetchall()
    assert (extraction_id,) not in queue


def test_auto_approved_records_cannot_be_decided(loaded):
    con = loaded
    (extraction_id,) = con.execute(
        "SELECT extraction_id FROM extractions WHERE status = 'auto_approved' LIMIT 1"
    ).fetchone()
    assert not review.decide(con, extraction_id, approve=False)


def test_sources_open_at_lineage(loaded):
    con = loaded
    uri, page, bbox = con.execute(
        "SELECT b.uri, e.page_number, e.bounding_box FROM extractions e "
        "JOIN bronze_files b USING (sha256) WHERE e.doc_type = 'contract' LIMIT 1"
    ).fetchone()
    image = sources.pdf_page(uri, page, tuple(bbox))
    assert image.width > 500 and image.height > image.width  # a portrait A4 page

    uri, row, ref = con.execute(
        "SELECT b.uri, e.row_number, e.document_ref FROM extractions e "
        "JOIN bronze_files b USING (sha256) WHERE e.doc_type = 'invoice' LIMIT 1"
    ).fetchone()
    assert ref in sources.sheet_rows(uri).loc[row].astype(str).tolist()
