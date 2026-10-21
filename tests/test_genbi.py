import pytest

from mock491 import bronze, extract, genbi, resolve
from mock491.genbi import catalog, examples, guard
from mock491.genbi.llm import Draft, ModelError


@pytest.fixture
def warehouse(con, dataset, tmp_path):
    out, truth = dataset
    for tenant in truth.tenants:
        for f in sorted((out / tenant).rglob("*.*")):
            bronze.ingest_file(con, f, tenant, tmp_path / "bronze")
    extract.run(con)
    resolve.resolve(con)
    return con


class FakeModel:
    """Returns scripted drafts in order and records what it was shown."""

    name = "fake"

    def __init__(self, *drafts: Draft | Exception):
        self.drafts, self.calls = list(drafts), []

    def draft(self, system, turns):
        self.calls.append((system, list(turns)))
        item = self.drafts.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.parametrize("example", examples.EXAMPLES, ids=lambda e: e.question[:40])
def test_every_example_runs(warehouse, example):
    answer = genbi.ask(warehouse, example.question)  # no model: answered from the example
    assert answer.error is None and answer.source == "example"
    assert answer.rows is not None


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM extractions",  # not in the catalog
        "SELECT * FROM read_csv('pyproject.toml')",  # table function
        "SELECT count(*) FROM records WHERE 0 < (SELECT count(*) FROM read_text('x'))",
        "DROP TABLE records",
        "SELECT 1; SELECT 2",
        "SELECT * FROM main.records",
        "COPY records TO 'out.csv'",
        "ATTACH 'warehouse.duckdb' AS w",
    ],
)
def test_guard_rejects(sql):
    with pytest.raises(guard.UnsafeQuery):
        guard.check(sql, catalog.TABLE_NAMES)


def test_sandbox_is_scoped_and_locked(warehouse, tmp_path):
    box = catalog.sandbox(warehouse, "HOLDING_ENERJI_AS")
    tenants = {t for (t,) in box.execute("SELECT DISTINCT tenant_id FROM records").fetchall()}
    assert tenants == {"HOLDING_ENERJI_AS"}
    (path := tmp_path / "secret.txt").write_text("x")
    with pytest.raises(Exception, match="disabled"):
        box.execute(f"SELECT * FROM read_text('{path.as_posix()}')")


def test_scoped_totals_match_the_holding_view(warehouse):
    whole = genbi.run_sql(warehouse, "SELECT tenant_id, exposure_try FROM subsidiaries").rows
    one = genbi.run_sql(warehouse, "SELECT exposure_try FROM subsidiaries", "HOLDING_ENERJI_AS")
    expected = whole.set_index("tenant_id").at["HOLDING_ENERJI_AS", "exposure_try"]
    assert one.rows["exposure_try"].tolist() == pytest.approx([expected])


def test_failed_draft_is_retried_with_the_error(warehouse):
    model = FakeModel(
        Draft(sql="SELECT nope FROM records", explanation="first try"),
        Draft(sql="SELECT count(*) AS n FROM records", explanation="second try"),
    )
    answer = genbi.ask(warehouse, "how many records?", model=model)
    assert answer.error is None and answer.rows["n"][0] > 0
    assert len(answer.attempts) == 2
    feedback = model.calls[1][1][-1]["content"]
    assert "failed" in feedback and "nope" in feedback


def test_gives_up_after_max_attempts(warehouse):
    bad = Draft(sql="SELECT * FROM extractions", explanation="")
    answer = genbi.ask(warehouse, "q", model=FakeModel(bad, bad))
    assert "Unknown table" in answer.error and answer.rows is None


def test_unanswerable_question_and_model_errors(warehouse):
    answer = genbi.ask(warehouse, "weather?", model=FakeModel(Draft(sql="", explanation="no")))
    assert answer.error is None and answer.rows is None and answer.explanation == "no"
    answer = genbi.ask(warehouse, "q", model=FakeModel(ModelError("offline")))
    assert answer.error == "offline"


def test_without_a_model_free_questions_are_declined(warehouse):
    answer = genbi.ask(warehouse, "who is our riskiest supplier?")
    assert answer.error and "No language model" in answer.error


def test_prompt_lists_the_tables(warehouse):
    box = catalog.sandbox(warehouse, None)
    prompt = genbi.system_prompt(box)
    assert all(f"TABLE {t.name}" in prompt for t in catalog.TABLES)
    assert "amount_try" in prompt and examples.EXAMPLES[0].sql in prompt
