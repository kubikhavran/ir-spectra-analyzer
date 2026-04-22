"""Tests for background reference-library workers."""

from __future__ import annotations

from pathlib import Path

import pytest

from file_io.format_registry import FormatRegistry
from storage.database import Database
from ui.workers.reference_library_worker import (
    ReferenceLibrarySearchWorker,
    ReferenceLibrarySyncWorker,
)


@pytest.fixture
def file_db(tmp_path):
    """Provide a file-backed database to exercise worker-local connections."""
    db_path = tmp_path / "worker-test.db"
    database = Database(db_path)
    database.initialize()
    yield database
    database.close()


def test_reference_library_sync_worker_imports_fixture_folder(file_db):
    fixture_root = Path(__file__).resolve().parent / "fixtures"
    folder = fixture_root / "reference library_1"
    worker = ReferenceLibrarySyncWorker(
        db_path=file_db.db_path,
        project_root=fixture_root,
        selected_library_folder=folder,
    )

    completed = []
    failures = []
    worker.completed.connect(completed.append)
    worker.failed.connect(failures.append)

    worker.run()

    assert failures == []
    assert len(completed) == 1
    assert completed[0] is not None
    assert completed[0].imported == len(list(folder.glob("*.SPA")))


def test_reference_library_search_worker_finds_exact_fixture_match(file_db):
    fixture_root = Path(__file__).resolve().parent / "fixtures"
    folder = fixture_root / "reference library_1"
    query = FormatRegistry().read(folder / "FER58-SE.SPA")
    worker = ReferenceLibrarySearchWorker(
        db_path=file_db.db_path,
        project_root=fixture_root,
        selected_library_folder=folder,
        spectrum=query,
        top_n=3,
        auto_import_project_library=True,
    )

    completed = []
    failures = []
    worker.completed.connect(completed.append)
    worker.failed.connect(failures.append)

    worker.run()

    assert failures == []
    assert len(completed) == 1
    outcome = completed[0]
    assert outcome.results
    assert outcome.results[0].name == "FER58-SE"
