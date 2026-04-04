"""Tests for batch PDF export from saved project files and overwrite handling."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.batch_project_pdf_export import (  # noqa: E402
    BatchProjectPDFExporter,
    BatchProjectPDFResult,
    BatchProjectPDFStatus,
    BatchProjectPDFSummary,
)
from app.output_path_policy import resolve_output_path  # noqa: E402
from core.peak import Peak  # noqa: E402
from core.project import Project  # noqa: E402
from core.spectrum import SpectralUnit, Spectrum  # noqa: E402
from reporting.pdf_generator import ReportOptions  # noqa: E402
from storage.project_serializer import ProjectSerializer  # noqa: E402
from ui.dialogs.batch_project_pdf_export_dialog import BatchProjectPDFExportDialog  # noqa: E402


def _make_project(path: Path, *, with_peak: bool = True) -> Project:
    """Create a synthetic Project for saved-project export tests."""
    wavenumbers = np.linspace(400.0, 4000.0, 64)
    intensities = np.linspace(0.1, 0.9, 64)
    spectrum = Spectrum(
        wavenumbers=wavenumbers,
        intensities=intensities,
        title=path.stem,
        source_path=path.with_suffix(".spa"),
        y_unit=SpectralUnit.ABSORBANCE,
    )
    project = Project(name=path.stem, spectrum=spectrum)
    if with_peak:
        project.peaks.append(
            Peak(position=1715.0, intensity=0.7, label="Edited Peak", vibration_id=42)
        )
    return project


def _write_project(path: Path, *, with_peak: bool = True) -> None:
    """Persist a synthetic project using the normal serializer."""
    ProjectSerializer().save(_make_project(path, with_peak=with_peak), path)


def test_resolve_output_path_modes(tmp_path):
    """Output-path helper should handle skip, overwrite, and rename explicitly."""
    target = tmp_path / "sample.pdf"
    target.write_bytes(b"old")
    (tmp_path / "sample (1).pdf").write_bytes(b"old-1")

    assert resolve_output_path(target, "skip") == ("skip", None)
    assert resolve_output_path(target, "overwrite") == ("write", target)
    assert resolve_output_path(target, "rename") == ("write", tmp_path / "sample (2).pdf")


def test_batch_project_pdf_exporter_empty_folder(tmp_path):
    """An empty input folder should produce an empty summary without failure."""
    exporter = BatchProjectPDFExporter()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()

    summary = exporter.export_folder(input_folder, output_folder)

    assert summary.total_found == 0
    assert summary.exported == 0
    assert summary.skipped == 0
    assert summary.failed == 0
    assert output_folder.exists()


def test_batch_project_pdf_exporter_exports_one_project(tmp_path, monkeypatch):
    """A valid `.irproj` file should generate one exported PDF result."""
    exporter = BatchProjectPDFExporter()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    project_file = input_folder / "edited.irproj"
    _write_project(project_file, with_peak=True)

    captured: dict[str, object] = {}

    def _fake_export(
        project: Project,
        output_path: Path,
        *,
        report_options: ReportOptions | None = None,
    ) -> None:
        captured["peak_labels"] = [peak.label for peak in project.peaks]
        output_path.write_bytes(b"%PDF-FAKE")

    monkeypatch.setattr(exporter, "_export_project", _fake_export)

    summary = exporter.export_folder(input_folder, output_folder)

    assert summary.total_found == 1
    assert summary.exported == 1
    assert summary.failed == 0
    result = summary.results[0]
    assert result.status == BatchProjectPDFStatus.EXPORTED
    assert result.output_path == output_folder / "edited.pdf"
    assert result.output_path.exists()
    assert captured["peak_labels"] == ["Edited Peak"]


def test_batch_project_pdf_exporter_continues_after_one_failure(tmp_path, monkeypatch):
    """A failed project file should not stop later files from exporting."""
    exporter = BatchProjectPDFExporter()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    good_file = input_folder / "good.irproj"
    bad_file = input_folder / "bad.irproj"
    _write_project(good_file, with_peak=False)
    bad_file.write_text("{not json", encoding="utf-8")

    def _fake_export(
        project: Project,
        output_path: Path,
        *,
        report_options: ReportOptions | None = None,
    ) -> None:
        output_path.write_bytes(b"%PDF-FAKE")

    monkeypatch.setattr(exporter, "_export_project", _fake_export)

    summary = exporter.export_folder(input_folder, output_folder)

    assert summary.total_found == 2
    assert summary.exported == 1
    assert summary.failed == 1
    assert any(
        result.path.name == "good.irproj"
        and result.status == BatchProjectPDFStatus.EXPORTED
        and result.output_path == output_folder / "good.pdf"
        for result in summary.results
    )
    assert any(
        result.path.name == "bad.irproj" and result.status == BatchProjectPDFStatus.FAILED
        for result in summary.results
    )


def test_batch_project_pdf_exporter_skip_mode_skips_existing_output(tmp_path, monkeypatch):
    """overwrite_mode='skip' should skip an existing target file."""
    exporter = BatchProjectPDFExporter()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    output_folder.mkdir()
    project_file = input_folder / "edited.irproj"
    _write_project(project_file)
    existing_pdf = output_folder / "edited.pdf"
    existing_pdf.write_bytes(b"old")

    def _should_not_export(
        project: Project,
        output_path: Path,
        *,
        report_options: ReportOptions | None = None,
    ) -> None:
        raise AssertionError("Export should be skipped when output already exists")

    monkeypatch.setattr(exporter, "_export_project", _should_not_export)

    summary = exporter.export_folder(input_folder, output_folder, overwrite_mode="skip")

    assert summary.exported == 0
    assert summary.skipped == 1
    assert summary.failed == 0
    assert summary.results[0].status == BatchProjectPDFStatus.SKIPPED
    assert summary.results[0].output_path == existing_pdf
    assert summary.results[0].reason == "output file already exists"


def test_batch_project_pdf_exporter_overwrite_mode_replaces_existing_output(tmp_path, monkeypatch):
    """overwrite_mode='overwrite' should replace an existing target file."""
    exporter = BatchProjectPDFExporter()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    output_folder.mkdir()
    project_file = input_folder / "edited.irproj"
    _write_project(project_file)
    existing_pdf = output_folder / "edited.pdf"
    existing_pdf.write_bytes(b"old")

    def _fake_export(
        project: Project,
        output_path: Path,
        *,
        report_options: ReportOptions | None = None,
    ) -> None:
        output_path.write_bytes(b"new")

    monkeypatch.setattr(exporter, "_export_project", _fake_export)

    summary = exporter.export_folder(input_folder, output_folder, overwrite_mode="overwrite")

    assert summary.exported == 1
    assert summary.results[0].output_path == existing_pdf
    assert existing_pdf.read_bytes() == b"new"


def test_batch_project_pdf_exporter_rename_mode_generates_unique_output(tmp_path, monkeypatch):
    """overwrite_mode='rename' should write to the next available numbered filename."""
    exporter = BatchProjectPDFExporter()
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    output_folder.mkdir()
    project_file = input_folder / "edited.irproj"
    _write_project(project_file)
    (output_folder / "edited.pdf").write_bytes(b"old")
    (output_folder / "edited (1).pdf").write_bytes(b"old-1")

    def _fake_export(
        project: Project,
        output_path: Path,
        *,
        report_options: ReportOptions | None = None,
    ) -> None:
        output_path.write_bytes(b"%PDF-FAKE")

    monkeypatch.setattr(exporter, "_export_project", _fake_export)

    summary = exporter.export_folder(input_folder, output_folder, overwrite_mode="rename")

    assert summary.exported == 1
    assert summary.results[0].output_path == output_folder / "edited (2).pdf"
    assert summary.results[0].output_path.exists()


def test_batch_project_pdf_exporter_passes_report_options(tmp_path):
    """Exporter should forward report options into the existing report-builder path."""

    class _FakeReportBuilder:
        def __init__(self) -> None:
            self.received_options: ReportOptions | None = None

        def build(self, project: Project, output_path: Path) -> None:
            raise AssertionError("build() should not be used when report options are provided")

        def build_with_options(
            self, project: Project, output_path: Path, options: ReportOptions
        ) -> None:
            self.received_options = options
            output_path.write_bytes(b"%PDF-FAKE")

    report_builder = _FakeReportBuilder()
    exporter = BatchProjectPDFExporter(report_builder=report_builder)
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    project_file = input_folder / "edited.irproj"
    _write_project(project_file)
    options = ReportOptions(
        include_structures=False,
        include_peak_table=False,
        include_metadata=False,
    )

    summary = exporter.export_folder(input_folder, output_folder, report_options=options)

    assert summary.exported == 1
    assert report_builder.received_options == options


def test_batch_project_pdf_export_dialog_handles_missing_folders_safely(qtbot):
    """The dialog should show friendly messages when required folders are missing."""
    dlg = BatchProjectPDFExportDialog()
    qtbot.addWidget(dlg)

    dlg._on_export()
    assert dlg._summary_label.text() == "No input folder selected."

    dlg._input_folder_edit.setText("/tmp/input")
    dlg._on_export()
    assert dlg._summary_label.text() == "No output folder selected."


def test_batch_project_pdf_export_dialog_renders_summary_results(qtbot, tmp_path):
    """The dialog should render batch export counts and per-file result rows."""
    summary = BatchProjectPDFSummary(
        input_folder=tmp_path / "input",
        output_folder=tmp_path / "output",
        results=(
            BatchProjectPDFResult(
                path=tmp_path / "ok.irproj",
                status=BatchProjectPDFStatus.EXPORTED,
                output_path=tmp_path / "output" / "ok.pdf",
            ),
            BatchProjectPDFResult(
                path=tmp_path / "skip.irproj",
                status=BatchProjectPDFStatus.SKIPPED,
                reason="output file already exists",
                output_path=tmp_path / "output" / "skip.pdf",
            ),
            BatchProjectPDFResult(
                path=tmp_path / "bad.irproj",
                status=BatchProjectPDFStatus.FAILED,
                reason="Parse failure",
            ),
        ),
    )

    class _FakeExporter:
        def export_folder(
            self, input_folder, output_folder, *, report_options, overwrite_mode
        ) -> BatchProjectPDFSummary:
            return summary

        def scan_folder(self, folder: Path) -> list[Path]:
            return []

    dlg = BatchProjectPDFExportDialog(exporter=_FakeExporter())
    qtbot.addWidget(dlg)
    dlg._input_folder_edit.setText(str(tmp_path / "input"))
    dlg._output_folder_edit.setText(str(tmp_path / "output"))

    dlg._on_export()

    assert dlg._results_table.rowCount() == 3
    assert dlg._results_table.item(0, 0).text() == "ok.irproj"
    assert dlg._results_table.item(1, 1).text() == "skipped"
    assert dlg._results_table.item(2, 2).text() == "Parse failure"
    assert dlg._results_table.item(0, 3).text().endswith("ok.pdf")
    assert "Total .irproj files found: 3" in dlg._summary_label.text()
    assert "Exported: 1 | Skipped: 1 | Failed: 1" in dlg._summary_label.text()


def test_batch_project_pdf_export_dialog_passes_overwrite_option(qtbot, tmp_path):
    """The dialog should pass overwrite mode and report options into the exporter."""

    class _FakeExporter:
        def __init__(self) -> None:
            self.received: tuple[str, str, ReportOptions, str] | None = None

        def export_folder(
            self, input_folder, output_folder, *, report_options, overwrite_mode
        ) -> BatchProjectPDFSummary:
            self.received = (input_folder, output_folder, report_options, overwrite_mode)
            return BatchProjectPDFSummary(
                input_folder=Path(input_folder),
                output_folder=Path(output_folder),
                results=(),
            )

        def scan_folder(self, folder: Path) -> list[Path]:
            return []

    exporter = _FakeExporter()
    dlg = BatchProjectPDFExportDialog(exporter=exporter)
    qtbot.addWidget(dlg)
    dlg._input_folder_edit.setText(str(tmp_path / "input"))
    dlg._output_folder_edit.setText(str(tmp_path / "output"))
    dlg._include_metadata_checkbox.setChecked(False)
    dlg._include_peak_table_checkbox.setChecked(False)
    dlg._include_structures_checkbox.setChecked(True)
    dlg._overwrite_mode_combo.setCurrentIndex(2)

    dlg._on_export()

    assert exporter.received is not None
    input_folder, output_folder, report_options, overwrite_mode = exporter.received
    assert input_folder == str(tmp_path / "input")
    assert output_folder == str(tmp_path / "output")
    assert report_options == ReportOptions(
        include_structures=True,
        include_peak_table=False,
        include_metadata=False,
    )
    assert overwrite_mode == "rename"
