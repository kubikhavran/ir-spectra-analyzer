"""Tests for batch PDF export helpers and dialog."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.batch_pdf_export import (  # noqa: E402
    BatchPDFExporter,
    BatchPDFResult,
    BatchPDFStatus,
    BatchPDFSummary,
)
from core.peak import Peak  # noqa: E402
from core.spectrum import SpectralUnit, Spectrum  # noqa: E402
from reporting.pdf_generator import ReportOptions  # noqa: E402
from ui.dialogs.batch_pdf_export_dialog import BatchPDFExportDialog  # noqa: E402


def _make_spectrum(path: Path, title: str | None = None) -> Spectrum:
    """Create a synthetic Spectrum for export tests."""
    wavenumbers = np.linspace(400.0, 4000.0, 64)
    intensities = np.linspace(0.1, 0.9, 64)
    return Spectrum(
        wavenumbers=wavenumbers,
        intensities=intensities,
        title=title or path.stem,
        source_path=path,
        y_unit=SpectralUnit.ABSORBANCE,
    )


def test_batch_pdf_exporter_empty_folder(tmp_path):
    """An empty input folder should produce an empty summary without failure."""
    exporter = BatchPDFExporter()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()

    summary = exporter.export_folder(input_folder, output_folder)

    assert summary.total_found == 0
    assert summary.exported == 0
    assert summary.skipped == 0
    assert summary.failed == 0
    assert output_folder.exists()


def test_batch_pdf_exporter_exports_one_successful_file(tmp_path, monkeypatch):
    """A valid `.spa` file should generate one exported PDF result."""
    exporter = BatchPDFExporter()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    spa_file = input_folder / "sample.spa"
    spa_file.write_bytes(b"spa")

    monkeypatch.setattr(exporter, "_read_spectrum", lambda path: _make_spectrum(path))

    def _fake_export(
        project,
        output_path: Path,
        *,
        report_options: ReportOptions | None = None,
    ) -> None:
        output_path.write_bytes(b"%PDF-FAKE")

    monkeypatch.setattr(exporter, "_export_project", _fake_export)

    summary = exporter.export_folder(input_folder, output_folder)

    assert summary.total_found == 1
    assert summary.exported == 1
    assert summary.failed == 0
    result = summary.results[0]
    assert result.status == BatchPDFStatus.EXPORTED
    assert result.output_path == output_folder / "sample.pdf"
    assert result.output_path.exists()
    assert result.detected_peaks == ()


def test_batch_pdf_exporter_continues_after_one_failure(tmp_path, monkeypatch):
    """A failed file should not stop later files from exporting."""
    exporter = BatchPDFExporter()
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

    def _fake_export(
        project,
        output_path: Path,
        *,
        report_options: ReportOptions | None = None,
    ) -> None:
        output_path.write_bytes(b"%PDF-FAKE")

    monkeypatch.setattr(exporter, "_read_spectrum", _fake_read)
    monkeypatch.setattr(exporter, "_export_project", _fake_export)

    summary = exporter.export_folder(input_folder, output_folder)

    assert summary.total_found == 2
    assert summary.exported == 1
    assert summary.failed == 1
    assert any(
        result.path.name == "bad.spa"
        and result.status == BatchPDFStatus.FAILED
        and result.reason == "Broken SPA"
        for result in summary.results
    )
    assert any(
        result.path.name == "ok.spa"
        and result.status == BatchPDFStatus.EXPORTED
        and result.output_path == output_folder / "ok.pdf"
        for result in summary.results
    )


def test_batch_pdf_exporter_detects_peaks_when_enabled(tmp_path, monkeypatch):
    """With auto-detect enabled, detected peaks should be attached to the exported project."""
    exporter = BatchPDFExporter()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    spa_file = input_folder / "sample.spa"
    spa_file.write_bytes(b"spa")

    monkeypatch.setattr(exporter, "_read_spectrum", lambda path: _make_spectrum(path))
    detected = (Peak(position=1715.0, intensity=0.7), Peak(position=2918.0, intensity=0.4))
    monkeypatch.setattr("app.batch_pdf_export.detect_peaks_for_spectrum", lambda spectrum: detected)

    captured: dict[str, object] = {}

    def _fake_export(
        project,
        output_path: Path,
        *,
        report_options: ReportOptions | None = None,
    ) -> None:
        captured["peaks"] = tuple(project.peaks)
        output_path.write_bytes(b"%PDF-FAKE")

    monkeypatch.setattr(exporter, "_export_project", _fake_export)

    summary = exporter.export_folder(input_folder, output_folder, detect_peaks=True)

    assert captured["peaks"] == detected
    assert summary.results[0].detected_peaks == detected


def test_batch_pdf_exporter_skip_mode_skips_existing_output(tmp_path, monkeypatch):
    """overwrite_mode='skip' should skip an existing PDF target."""
    exporter = BatchPDFExporter()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    output_folder.mkdir()
    spa_file = input_folder / "sample.spa"
    spa_file.write_bytes(b"spa")
    existing_pdf = output_folder / "sample.pdf"
    existing_pdf.write_bytes(b"old")

    monkeypatch.setattr(exporter, "_read_spectrum", lambda path: _make_spectrum(path))

    def _should_not_export(
        project,
        output_path: Path,
        *,
        report_options: ReportOptions | None = None,
    ) -> None:
        raise AssertionError("Export should be skipped when output already exists")

    monkeypatch.setattr(exporter, "_export_project", _should_not_export)

    summary = exporter.export_folder(input_folder, output_folder, overwrite_mode="skip")

    assert summary.exported == 0
    assert summary.skipped == 1
    assert summary.results[0].status == BatchPDFStatus.SKIPPED
    assert summary.results[0].output_path == existing_pdf
    assert summary.results[0].reason == "output file already exists"


def test_batch_pdf_export_dialog_handles_missing_folders_safely(qtbot):
    """The dialog should show friendly messages when required folders are missing."""
    dlg = BatchPDFExportDialog()
    qtbot.addWidget(dlg)

    dlg._on_export()
    assert dlg._summary_label.text() == "No input folder selected."

    dlg._input_folder_edit.setText("/tmp/input")
    dlg._on_export()
    assert dlg._summary_label.text() == "No output folder selected."


def test_batch_pdf_export_dialog_renders_summary_results(qtbot, tmp_path):
    """The dialog should render batch export counts and per-file result rows."""
    summary = BatchPDFSummary(
        input_folder=tmp_path / "input",
        output_folder=tmp_path / "output",
        results=(
            BatchPDFResult(
                path=tmp_path / "ok.spa",
                status=BatchPDFStatus.EXPORTED,
                output_path=tmp_path / "output" / "ok.pdf",
            ),
            BatchPDFResult(
                path=tmp_path / "skip.spa",
                status=BatchPDFStatus.SKIPPED,
                reason="already exported",
            ),
            BatchPDFResult(
                path=tmp_path / "bad.spa",
                status=BatchPDFStatus.FAILED,
                reason="Parse failure",
            ),
        ),
    )

    class _FakeExporter:
        def export_folder(
            self, input_folder, output_folder, *, detect_peaks, report_options, overwrite_mode
        ) -> BatchPDFSummary:
            return summary

        def scan_folder(self, folder: Path) -> list[Path]:
            return []

    dlg = BatchPDFExportDialog(exporter=_FakeExporter())
    qtbot.addWidget(dlg)
    dlg._input_folder_edit.setText(str(tmp_path / "input"))
    dlg._output_folder_edit.setText(str(tmp_path / "output"))

    dlg._on_export()

    assert dlg._results_table.rowCount() == 3
    assert dlg._results_table.item(0, 0).text() == "ok.spa"
    assert dlg._results_table.item(1, 1).text() == "skipped"
    assert dlg._results_table.item(2, 2).text() == "Parse failure"
    assert dlg._results_table.item(0, 3).text().endswith("ok.pdf")
    assert "Total .spa files found: 3" in dlg._summary_label.text()
    assert "Exported: 1 | Skipped: 1 | Failed: 1" in dlg._summary_label.text()


def test_batch_pdf_exporter_passes_report_options(tmp_path, monkeypatch):
    """Batch `.spa` exporter should forward report options to the shared report pipeline."""

    class _FakeReportBuilder:
        def __init__(self) -> None:
            self.received_options: ReportOptions | None = None

        def build(self, project, output_path: Path) -> None:
            raise AssertionError("build() should not be used when report options are provided")

        def build_with_options(self, project, output_path: Path, options: ReportOptions) -> None:
            self.received_options = options
            output_path.write_bytes(b"%PDF-FAKE")

    report_builder = _FakeReportBuilder()
    exporter = BatchPDFExporter(report_builder=report_builder)
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    spa_file = input_folder / "sample.spa"
    spa_file.write_bytes(b"spa")
    monkeypatch.setattr(exporter, "_read_spectrum", lambda path: _make_spectrum(path))
    options = ReportOptions(
        include_structures=False,
        include_peak_table=False,
        include_metadata=False,
    )

    summary = exporter.export_folder(input_folder, output_folder, report_options=options)

    assert summary.exported == 1
    assert report_builder.received_options == options


def test_batch_pdf_export_dialog_passes_detect_peaks_option(qtbot, tmp_path):
    """The dialog should pass report options, auto-detect, and overwrite mode into the exporter."""

    class _FakeExporter:
        def __init__(self) -> None:
            self.received: tuple[str, str, bool, ReportOptions, str] | None = None

        def export_folder(
            self, input_folder, output_folder, *, detect_peaks, report_options, overwrite_mode
        ) -> BatchPDFSummary:
            self.received = (
                input_folder,
                output_folder,
                detect_peaks,
                report_options,
                overwrite_mode,
            )
            return BatchPDFSummary(
                input_folder=Path(input_folder),
                output_folder=Path(output_folder),
                results=(),
            )

        def scan_folder(self, folder: Path) -> list[Path]:
            return []

    exporter = _FakeExporter()
    dlg = BatchPDFExportDialog(exporter=exporter)
    qtbot.addWidget(dlg)
    dlg._input_folder_edit.setText(str(tmp_path / "input"))
    dlg._output_folder_edit.setText(str(tmp_path / "output"))
    dlg._detect_peaks_checkbox.setChecked(True)
    dlg._include_metadata_checkbox.setChecked(False)
    dlg._include_peak_table_checkbox.setChecked(False)
    dlg._include_structures_checkbox.setChecked(True)
    dlg._overwrite_mode_combo.setCurrentIndex(2)

    dlg._on_export()

    assert exporter.received == (
        str(tmp_path / "input"),
        str(tmp_path / "output"),
        True,
        ReportOptions(
            include_structures=True,
            include_peak_table=False,
            include_metadata=False,
        ),
        "rename",
    )
