"""Streamlit glue around mock491.queries: cached reads that refresh when the warehouse changes.

Pages call `load(queries.fn, *args)` instead of opening connections. The cache key includes the
warehouse files' modification time, so a CLI run (extract, resolve) or a review decision shows up
on the next rerun without a manual refresh.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

from mock491 import config, db, queries, sources


def ready() -> bool:
    return config.WAREHOUSE_PATH.exists()


def _version() -> int:
    path = config.WAREHOUSE_PATH
    files = (path, path.with_name(path.name + ".wal"))
    return max((f.stat().st_mtime_ns for f in files if f.exists()), default=0)


@contextmanager
def connection() -> Iterator[duckdb.DuckDBPyConnection]:
    """Short-lived connection, so the CLI can still write between clicks."""
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


@st.cache_data(show_spinner=False, max_entries=512)
def _run(name: str, version: int, args: tuple):
    with connection() as con:
        return getattr(queries, name)(con, *args)


def load(query: Callable, *args):
    """Run a function from mock491.queries (cached until the warehouse changes)."""
    return _run(query.__name__, _version(), args)


def write(action: Callable, *args):
    """Run a write such as review.decide(con, ...), then drop cached reads."""
    with connection() as con:
        result = action(con, *args)
    _run.clear()
    return result


# Bronze files are content-addressed and immutable, so renders are cached by uri forever.
@st.cache_data(show_spinner=False, max_entries=64)
def pdf_image(uri: str, page: int, bbox: tuple | None, crop_margin: float | None = None):
    return sources.pdf_page(Path(uri), page, bbox, crop_margin=crop_margin)


@st.cache_data(show_spinner=False, max_entries=32)
def sheet(uri: str) -> pd.DataFrame:
    return sources.sheet_rows(Path(uri))
