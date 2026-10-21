"""Smoke tests: every page renders against a real (small) warehouse, and review works end to end."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from mock491 import bronze, config, db, extract, resolve

MAIN = str(Path(__file__).parents[1] / "app" / "main.py")
PAGES = [
    "views/overview.py",
    "views/counterparties.py",
    "views/review.py",
    "views/pipeline.py",
    "views/ask.py",
]


@pytest.fixture
def warehouse(dataset, tmp_path, monkeypatch):
    out, truth = dataset
    path = tmp_path / "warehouse.duckdb"
    con = db.connect(path)
    db.init_db(con)
    for tenant in truth.tenants:
        for f in sorted((out / tenant).rglob("*.*")):
            bronze.ingest_file(con, f, tenant, tmp_path / "bronze")
    extract.run(con)
    resolve.resolve(con)
    con.close()
    monkeypatch.setattr(config, "WAREHOUSE_PATH", path)
    monkeypatch.setattr(config, "MOCK_DIR", out)
    return path


def app() -> AppTest:
    return AppTest.from_file(MAIN, default_timeout=60)


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(warehouse, page):
    at = app().run()
    at.switch_page(page).run()
    assert not at.exception, at.exception
    assert at.title


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_scoped_to_one_subsidiary(warehouse, page):
    at = app()
    at.session_state["scope"] = "HOLDING_ENERJI_AS"  # AppTest can't drive a format_func selectbox
    at.run()
    at.switch_page(page).run()
    assert not at.exception, at.exception


def test_review_approve_then_reopen(warehouse):
    at = app().run()
    at.switch_page("views/review.py").run()
    pending = len(at.dataframe[0].value)
    next(b for b in at.button if b.label == "Approve").click().run()
    assert not at.exception, at.exception
    assert len(at.dataframe[0].value) == pending - 1  # the queue moved on

    at.session_state["decided"] = {"selection": {"rows": [0], "columns": [], "cells": []}}
    at.run()
    next(b for b in at.button if b.label.startswith("Reopen")).click().run()
    assert not at.exception, at.exception
    assert len(at.dataframe[0].value) == pending


def test_missing_warehouse_shows_setup_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WAREHOUSE_PATH", tmp_path / "none.duckdb")
    at = app().run()
    assert not at.exception
    assert "Build the mock warehouse first" in at.markdown[-1].value or any(
        "Build the mock warehouse" in m.value for m in at.markdown
    )


def test_ask_answers_an_example_without_a_model(warehouse, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "none")
    at = app().run()
    at.switch_page("views/ask.py").run()
    at.chat_input[0].set_value("How much exposure does each subsidiary carry?").run()
    assert not at.exception, at.exception
    assert not at.error
    assert any(len(df.value) == 4 for df in at.dataframe)  # one row per subsidiary
