import pytest

from mock491 import bronze, evaluate, extract, resolve
from mock491.resolve import name_similarity, parse_name


@pytest.mark.parametrize(
    "name, core, legal",
    [
        ("DURDU ELEKTRİK SAN. VE TİC. A.Ş.", "durdu elektrik", "AS"),
        ("Durdu Elektrik Sanayi ve Ticaret Anonim Şirketi", "durdu elektrik", "AS"),
        ("Durdu Elektrik San. ve Tic. A.S.", "durdu elektrik", "AS"),
        ("Durdu Elektrik AŞ", "durdu elektrik", "AS"),
        ("Şensoy Makine San. ve Tic. Ltd. Şti.", "sensoy makine", "LTD"),
        ("Şensoy Makine LTD", "sensoy makine", "LTD"),
        ("Yıldız Gıda", "yildiz gida", None),
    ],
)
def test_parse_name(name, core, legal):
    assert parse_name(name) == (core, legal)


def test_name_similarity_tolerates_typos_but_not_other_companies():
    assert name_similarity("drudu elektrik", "durdu elektrik") >= resolve.NAME_THRESHOLD
    assert name_similarity("akca yapi malzemeleri", "safak yapi malzemeleri") == 0
    assert name_similarity("aslan yazilim", "eraslan yazilim") == 0


@pytest.fixture
def resolved(con, dataset, tmp_path):
    out, truth = dataset
    for tenant in truth.tenants:
        for f in sorted((out / tenant).rglob("*.*")):
            bronze.ingest_file(con, f, tenant, tmp_path / "bronze")
    extract.run(con)
    stats = resolve.resolve(con)
    return con, truth, stats


def test_resolution_matches_ground_truth(resolved):
    con, truth, stats = resolved
    report = evaluate.evaluate_entities(con, truth)
    assert report.wrong_merges == [] and report.split_entities == []
    assert stats.entities == len(truth.entities)


def test_every_extraction_is_linked_and_rerun_is_stable(resolved):
    con, _, _ = resolved
    unlinked = "SELECT count(*) FROM extractions WHERE master_entity_id IS NULL"
    assert con.execute(unlinked).fetchone()[0] == 0
    before = con.execute("SELECT * FROM entities ORDER BY 1").fetchall()
    resolve.resolve(con)
    assert con.execute("SELECT * FROM entities ORDER BY 1").fetchall() == before


def test_lookalikes_never_share_an_entity(resolved):
    con, truth, _ = resolved
    by_id = {e.entity_id: e for e in truth.entities}
    true_entity = {(r.tenant_id, r.record_id): r.entity_id for r in truth.records}
    clusters: dict[str, set[str]] = {}
    for tenant, ref, master in con.execute(
        "SELECT tenant_id, document_ref, master_entity_id FROM extractions"
    ).fetchall():
        clusters.setdefault(master, set()).add(true_entity[(tenant, ref)])
    for members in clusters.values():
        assert not any(by_id[m].sibling_of in members for m in members)
