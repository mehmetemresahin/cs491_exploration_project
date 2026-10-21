"""Bronze layer: immutable, content-addressed copies of every incoming file."""

import hashlib
import shutil
import unicodedata
from pathlib import Path

import duckdb

from mock491 import config


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def ingest_file(
    con: duckdb.DuckDBPyConnection,
    src: Path,
    tenant_id: str,
    bronze_dir: Path | None = None,
) -> tuple[str, bool]:
    """Copy `src` into bronze and record it. Returns (sha256, newly_ingested)."""
    bronze_dir = bronze_dir or config.BRONZE_DIR
    digest = sha256_of(src)
    if con.execute("SELECT 1 FROM bronze_files WHERE sha256 = ?", [digest]).fetchone():
        return digest, False

    dest = bronze_dir / tenant_id / f"{digest}{src.suffix.lower()}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    dest.chmod(0o444)

    con.execute(
        "INSERT INTO bronze_files (sha256, tenant_id, original_name, uri, size_bytes) "
        "VALUES (?, ?, ?, ?, ?)",
        # NFC so "ş" typed in a query matches filenames stored decomposed (s + U+0327).
        [
            digest,
            tenant_id,
            unicodedata.normalize("NFC", src.name),
            dest.as_posix(),
            src.stat().st_size,
        ],
    )
    return digest, True
