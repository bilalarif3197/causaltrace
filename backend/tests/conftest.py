"""Point every test at a throwaway database.

Set before any test module imports `main`, which calls `store.init_db()` at
import time. Without this the suite would write into the developer's real
case database.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="causaltrace-tests-"))
os.environ["CAUSALTRACE_DB"] = str(_TMP / "test.db")

import pytest  # noqa: E402

from services import store  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    """Each test starts from an empty database."""
    db = Path(os.environ["CAUSALTRACE_DB"])
    for path in (db, db.with_suffix(".db-wal"), db.with_suffix(".db-shm")):
        path.unlink(missing_ok=True)
    store.init_db()
    yield
