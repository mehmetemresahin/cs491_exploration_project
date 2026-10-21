import pytest

from mock491 import db, mockgen


@pytest.fixture
def con(tmp_path):
    connection = db.connect(tmp_path / "test.duckdb")
    db.init_db(connection)
    yield connection
    connection.close()


@pytest.fixture(scope="session")
def dataset(tmp_path_factory):
    """A small generated holding: (mock dir, ground truth)."""
    out = tmp_path_factory.mktemp("mock")
    return out, mockgen.generate(out, seed=7, n_suppliers=10, contracts_per_tenant=3,
                                 invoices_per_tenant=8)  # fmt: skip
