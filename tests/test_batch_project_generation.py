"""Tests for batch project generation helpers and dialog."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.batch_project_generation import (  # noqa: E402
    BatchProjectGenerator,
    BatchProjectResult,
    BatchProjectStatus,
    BatchProjectSummary,
)
from core.peak import Peak  # noqa: E402
from core.spectrum import SpectralUnit, Spectrum  # noqa: E402
from storage.project_serializer import ProjectSerializer  # noqa: E402
from ui.dialogs.batch_project_generation_dialog import BatchProjectGenerationDialog  # noqa: E402
from ui.workers.batch_project_generation_worker import BatchProjectGenerationWorker  # noqa: E402


def _make_spectrum(path: Path, title: str | None = None) -> Spectrum:
    """Create a synthetic Spectrum for project-generation tests."""
    wavenumbers = np.linspace(400.0, 4000.0, 64)
    intensities = np.linspace(0.1, 0.9, 64)
    return Spectrum(
        wavenumbers=wavenumbers,
        intensities=intensities,
        title=title or path.stem,
        source_path=path,
        y_unit=SpectralUnit.ABSORBANCE,
    )


def test_batch_project_generator_empty_folder(tmp_path):
    """An empty input folder should produce an empty summary without failure."""
    generator = BatchProjectGenerator()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()

    summary = generator.generate_folder(input_folder, output_folder)

    assert summary.total_found == 0
    assert summary.generated == 0
    assert summary.skipped == 0
    assert summary.failed == 0
    assert output_folder.exists()


def test_batch_project_generator_generates_one_project(tmp_path, monkeypatch):
    """A valid `.spa` file should generate one reopenable `.irproj` result."""
    generator = BatchProjectGenerator()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    spa_file = input_folder / "sample.spa"
    spa_file.write_bytes(b"spa")

    monkeypatch.setattr(generator, "_read_spectrum", lambda path: _make_spectrum(path))

    summary = generator.generate_folder(input_folder, output_folder)

    assert summary.total_found == 1
    assert summary.generated == 1
    assert summary.failed == 0
    result = summary.results[0]
    assert result.status == BatchProjectStatus.GENERATED
    assert result.output_path == output_folder / "sample.irproj"
    assert result.output_path.exists()
    assert result.peak_count == 0

    loaded = ProjectSerializer().load(result.output_path)
    assert loaded.name == "sample"
    assert loaded.spectrum is not None
    assert loaded.spectrum.source_path == spa_file
    assert loaded.peaks == []


def test_batch_project_generator_continues_after_one_failure(tmp_path, monkeypatch):
    """A failed file should not stop later project generation."""
    generator = BatchProjectGenerator()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    ok_file = input_folder / "ok.spa"
    bad_file = input_folder / "bad.spa"
    ok_file.write_bytes(b"spa")
    bad_file.write_bytes(b"spa")

    def _fake_read(path: Path) -> Spectrum:
        if path.name == "bad.spa":
            raise ValueError("Broken SPA")
        return _make_spectrum(path)

    monkeypatch.setattr(generator, "_read_spectrum", _fake_read)

    summary = generator.generate_folder(input_folder, output_folder)

    assert summary.total_found == 2
    assert summary.generated == 1
    assert summary.failed == 1
    assert any(
        result.path.name == "bad.spa"
        and result.status == BatchProjectStatus.FAILED
        and result.reason == "Broken SPA"
        for result in summary.results
    )
    assert any(
        result.path.name == "ok.spa"
        and result.status == BatchProjectStatus.GENERATED
        and result.output_path == output_folder / "ok.irproj"
        for result in summary.results
    )


def test_batch_project_generator_detect_peaks_disabled_leaves_project_without_peaks(
    tmp_path,
    monkeypatch,
):
    """When auto-detect is off, project generation should not add peaks."""
    generator = BatchProjectGenerator()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    spa_file = input_folder / "sample.spa"
    spa_file.write_bytes(b"spa")

    monkeypatch.setattr(generator, "_read_spectrum", lambda path: _make_spectrum(path))

    def _unexpected_call(spectrum):
        raise AssertionError("detect_peaks_for_spectrum should not be called")

    monkeypatch.setattr("app.batch_project_generation.detect_peaks_for_spectrum", _unexpected_call)

    summary = generator.generate_folder(input_folder, output_folder, detect_peaks=False)

    assert summary.results[0].peak_count == 0
    loaded = ProjectSerializer().load(summary.results[0].output_path)
    assert loaded.peaks == []


def test_batch_project_generator_detects_peaks_when_enabled(tmp_path, monkeypatch):
    """With auto-detect enabled, generated projects should persist the detected peaks."""
    generator = BatchProjectGenerator()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    spa_file = input_folder / "sample.spa"
    spa_file.write_bytes(b"spa")

    monkeypatch.setattr(generator, "_read_spectrum", lambda path: _make_spectrum(path))
    detected = (Peak(position=1715.0, intensity=0.7), Peak(position=2918.0, intensity=0.4))
    monkeypatch.setattr(
        "app.batch_project_generation.detect_peaks_for_spectrum", lambda spectrum: detected
    )

    summary = generator.generate_folder(input_folder, output_folder, detect_peaks=True)

    assert summary.results[0].peak_count == 2
    loaded = ProjectSerializer().load(summary.results[0].output_path)
    assert len(loaded.peaks) == 2
    assert loaded.peaks[0].position == 1715.0
    assert loaded.peaks[1].position == 2918.0


def test_batch_project_generator_skip_mode_skips_existing_output(tmp_path, monkeypatch):
    """overwrite_mode='skip' should skip an existing project target."""
    generator = BatchProjectGenerator()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    output_folder.mkdir()
    spa_file = input_folder / "sample.spa"
    spa_file.write_bytes(b"spa")
    existing_project = output_folder / "sample.irproj"
    existing_project.write_text("existing", encoding="utf-8")

    monkeypatch.setattr(generator, "_read_spectrum", lambda path: _make_spectrum(path))

    def _should_not_save(project, output_path: Path) -> None:
        raise AssertionError("Project generation should be skipped when output already exists")

    monkeypatch.setattr(generator, "_save_project", _should_not_save)

    summary = generator.generate_folder(input_folder, output_folder, overwrite_mode="skip")

    assert summary.generated == 0
    assert summary.skipped == 1
    assert summary.results[0].status == BatchProjectStatus.SKIPPED
    assert summary.results[0].output_path == existing_project
    assert summary.results[0].reason == "output file already exists"


def test_batch_project_generation_dialog_handles_missing_folders_safely(qtbot):
    """The dialog should show friendly messages when required folders are missing."""
    dlg = BatchProjectGenerationDialog()
    qtbot.addWidget(dlg)

    dlg._on_generate()
    assert dlg._summary_label.text() == "No input folder selected."

    dlg._input_folder_edit.setText("/tmp/input")
    dlg._on_generate()
    assert dlg._summary_label.text() == "No output folder selected."


def test_batch_project_generation_dialog_renders_summary_results(qtbot, tmp_path):
    """The dialog should render batch generation counts and per-file result rows."""
    summary = BatchProjectSummary(
        input_folder=tmp_path / "input",
        output_folder=tmp_path / "output",
        results=(
            BatchProjectResult(
                path=tmp_path / "ok.spa",
                status=BatchProjectStatus.GENERATED,
                output_path=tmp_path / "output" / "ok.irproj",
                peak_count=3,
            ),
            BatchProjectResult(
                path=tmp_path / "bad.spa",
                status=BatchProjectStatus.FAILED,
                reason="Parse failure",
            ),
        ),
    )

    class _FakeGenerator:
        def generate_folder(
            self, input_folder, output_folder, *, detect_peaks, overwrite_mode
        ) -> BatchProjectSummary:
            return summary

        def scan_folder(self, folder: Path) -> list[Path]:
            return []

    dlg = BatchProjectGenerationDialog(generator=_FakeGenerator())
    qtbot.addWidget(dlg)
    dlg._input_folder_edit.setText(str(tmp_path / "input"))
    dlg._output_folder_edit.setText(str(tmp_path / "output"))

    dlg._on_generate()

    assert dlg._results_table.rowCount() == 2
    assert dlg._results_table.item(0, 0).text() == "ok.spa"
    assert dlg._results_table.item(0, 2).text() == "3"
    assert dlg._results_table.item(1, 1).text() == "failed"
    assert dlg._results_table.item(1, 3).text() == "Parse failure"
    assert dlg._results_table.item(0, 4).text().endswith("ok.irproj")
    assert "Total .spa files found: 2" in dlg._summary_label.text()
    assert "Generated: 1 | Skipped: 0 | Failed: 1" in dlg._summary_label.text()


def test_batch_project_generation_dialog_passes_detect_peaks_option(qtbot, tmp_path):
    """The dialog should pass auto-detect and overwrite options into the generator."""

    class _FakeGenerator:
        def __init__(self) -> None:
            self.received: tuple[str, str, bool, str] | None = None

        def generate_folder(
            self, input_folder, output_folder, *, detect_peaks, overwrite_mode
        ) -> BatchProjectSummary:
            self.received = (input_folder, output_folder, detect_peaks, overwrite_mode)
            return BatchProjectSummary(
                input_folder=Path(input_folder),
                output_folder=Path(output_folder),
                results=(),
            )

        def scan_folder(self, folder: Path) -> list[Path]:
            return []

    generator = _FakeGenerator()
    dlg = BatchProjectGenerationDialog(generator=generator)
    qtbot.addWidget(dlg)
    dlg._input_folder_edit.setText(str(tmp_path / "input"))
    dlg._output_folder_edit.setText(str(tmp_path / "output"))
    dlg._detect_peaks_checkbox.setChecked(True)
    dlg._overwrite_mode_combo.setCurrentIndex(1)

    dlg._on_generate()

    assert generator.received == (
        str(tmp_path / "input"),
        str(tmp_path / "output"),
        True,
        "overwrite",
    )


def test_batch_project_generation_worker_emits_summary(monkeypatch, tmp_path):
    """Worker should emit the completed summary from the batch generator."""
    summary = BatchProjectSummary(
        input_folder=tmp_path / "input",
        output_folder=tmp_path / "output",
        results=(),
    )
    captured = {}

    def _fake_generate_folder(
        self,
        input_folder,
        output_folder,
        *,
        detect_peaks,
        overwrite_mode,
    ):
        captured["args"] = (
            input_folder,
            output_folder,
            detect_peaks,
            overwrite_mode,
        )
        return summary

    monkeypatch.setattr(BatchProjectGenerator, "generate_folder", _fake_generate_folder)
    worker = BatchProjectGenerationWorker(
        input_folder=tmp_path / "input",
        output_folder=tmp_path / "output",
        detect_peaks=True,
        overwrite_mode="rename",
    )

    completed = []
    failures = []
    worker.completed.connect(completed.append)
    worker.failed.connect(failures.append)

    worker.run()

    assert failures == []
    assert completed == [summary]
    assert captured["args"] == (
        tmp_path / "input",
        tmp_path / "output",
        True,
        "rename",
    )


def test_batch_project_generation_dialog_runs_background_generation_for_default_generator(
    qtbot,
    monkeypatch,
    tmp_path,
):
    """Default generator path should run on a worker thread and update the dialog."""
    summary = BatchProjectSummary(
        input_folder=tmp_path / "input",
        output_folder=tmp_path / "output",
        results=(
            BatchProjectResult(
                path=tmp_path / "input" / "sample.spa",
                status=BatchProjectStatus.GENERATED,
                output_path=tmp_path / "output" / "sample.irproj",
                peak_count=2,
            ),
        ),
    )

    def _fake_generate_folder(
        self,
        input_folder,
        output_folder,
        *,
        detect_peaks,
        overwrite_mode,
    ):
        return summary

    monkeypatch.setattr(BatchProjectGenerator, "generate_folder", _fake_generate_folder)

    dlg = BatchProjectGenerationDialog()
    qtbot.addWidget(dlg)
    dlg._input_folder_edit.setText(str(tmp_path / "input"))
    dlg._output_folder_edit.setText(str(tmp_path / "output"))
    dlg._update_generate_button_state()

    dlg._on_generate()

    qtbot.waitUntil(lambda: dlg._results_table.rowCount() == 1, timeout=10000)
    if dlg._generate_thread is not None:
        qtbot.waitUntil(lambda: not dlg._generate_thread.isRunning(), timeout=10000)

    assert dlg._results_table.item(0, 0).text() == "sample.spa"
    assert dlg._results_table.item(0, 2).text() == "2"
    assert "Generated: 1 | Skipped: 0 | Failed: 0" in dlg._summary_label.text()
