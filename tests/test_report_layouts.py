"""PDF report options: the single-page protocol and peaks without assignment."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from app.report_presets import ReportPresetManager
from core.peak import Peak
from core.project import Project
from core.spectrum import SpectralUnit, Spectrum
from reporting.pdf_generator import (
    LAYOUT_CHOICES,
    LAYOUT_FULL_BLEED,
    LAYOUT_SINGLE_PAGE,
    PDFGenerator,
    ReportOptions,
)

_WN = np.linspace(4000.0, 400.0, 1801)


def _project(n_peaks: int = 4, assigned: int = 2) -> Project:
    y = np.full_like(_WN, 99.0)
    positions = np.linspace(3300.0, 600.0, n_peaks)
    for position in positions:
        y -= 30.0 * np.exp(-((_WN - position) ** 2) / (2 * 8.0**2))
    spectrum = Spectrum(_WN.copy(), y, y_unit=SpectralUnit.TRANSMITTANCE, title="Sample")
    peaks = []
    for index, position in enumerate(positions):
        peak = Peak(position=float(position), intensity=69.0)
        if index < assigned:
            peak.vibration_labels = [f"band {index}"]
            peak.vibration_ids = [None]
        peaks.append(peak)
    return Project(name="P1", spectrum=spectrum, peaks=peaks)


def _page_sizes(path: Path) -> list[tuple[float, float]]:
    """(width, height) of every page, read from the PDF's MediaBox entries."""
    data = path.read_bytes()
    # ReportLab writes one MediaBox per page object and none on the page tree.
    pages = re.findall(rb"/MediaBox\s*\[\s*([\d.\s]+)\]", data)
    sizes = []
    for box in pages:
        x0, y0, x1, y1 = (float(v) for v in box.split())
        sizes.append((x1 - x0, y1 - y0))
    return sizes


def _table_peaks(monkeypatch) -> list[list]:
    """Record the peaks each generated report puts in its peak table."""
    recorded: list[list] = []
    original = PDFGenerator._append_peak_table_section

    def _spy(self, story, sorted_peaks, *args, **kwargs):
        recorded.append(list(sorted_peaks))
        return original(self, story, sorted_peaks, *args, **kwargs)

    monkeypatch.setattr(PDFGenerator, "_append_peak_table_section", _spy)
    return recorded


def test_defaults_are_unchanged() -> None:
    options = ReportOptions()
    assert options.layout == LAYOUT_FULL_BLEED
    assert options.include_unassigned_peaks is False
    assert LAYOUT_SINGLE_PAGE in LAYOUT_CHOICES


def test_single_page_protocol_fits_on_one_portrait_page(tmp_path: Path, qtbot) -> None:
    out = tmp_path / "one.pdf"
    PDFGenerator().generate(_project(), out, options=ReportOptions(layout=LAYOUT_SINGLE_PAGE))
    sizes = _page_sizes(out)
    assert len(sizes) == 1
    width, height = sizes[0]
    assert width < height  # portrait A4
    assert height == pytest.approx(841.89, abs=1.0)

    standard = tmp_path / "standard.pdf"
    PDFGenerator().generate(_project(), standard, options=ReportOptions())
    standard_sizes = _page_sizes(standard)
    assert len(standard_sizes) == 2  # the default report is unchanged
    assert standard_sizes[0][0] > standard_sizes[0][1]  # landscape spectrum page


def test_a_long_peak_table_continues_on_page_two(tmp_path: Path, qtbot) -> None:
    out = tmp_path / "long.pdf"
    PDFGenerator().generate(
        _project(n_peaks=90, assigned=90),
        out,
        options=ReportOptions(layout=LAYOUT_SINGLE_PAGE),
    )
    sizes = _page_sizes(out)
    assert len(sizes) == 2
    assert all(width < height for width, height in sizes)


@pytest.mark.parametrize("layout", LAYOUT_CHOICES)
def test_unassigned_peaks_are_listed_only_when_asked(
    tmp_path: Path, qtbot, monkeypatch, layout
) -> None:
    project = _project(n_peaks=4, assigned=2)
    recorded = _table_peaks(monkeypatch)

    PDFGenerator().generate(project, tmp_path / "plain.pdf", options=ReportOptions(layout=layout))
    PDFGenerator().generate(
        project,
        tmp_path / "all.pdf",
        options=ReportOptions(layout=layout, include_unassigned_peaks=True),
    )
    assert [len(peaks) for peaks in recorded] == [2, 4]
    assert all(peak.vibration_labels for peak in recorded[0])


def test_presets_keep_the_new_options(tmp_path: Path) -> None:
    from storage.settings import Settings

    settings = Settings(tmp_path / "s.json")
    settings.load()
    manager = ReportPresetManager(settings)
    manager.save_preset(
        "protocol", ReportOptions(layout=LAYOUT_SINGLE_PAGE, include_unassigned_peaks=True)
    )
    restored = ReportPresetManager(settings).get_preset("protocol").options
    assert restored.layout == LAYOUT_SINGLE_PAGE
    assert restored.include_unassigned_peaks is True


def test_export_dialog_offers_unassigned_peaks_for_pdf_too(qtbot) -> None:
    from ui.dialogs.export_dialog import ExportDialog

    dialog = ExportDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.selected_format == "pdf"
    assert dialog._include_unassigned_checkbox.isVisible()
    # The report widget's own box stays hidden: one checkbox, all formats.
    assert not dialog._report_options_widget._include_unassigned_checkbox.isVisible()

    dialog._include_unassigned_checkbox.setChecked(True)
    assert dialog.report_options.include_unassigned_peaks is True
    assert dialog.include_unassigned is True

    combo = dialog._report_options_widget._layout_combo
    combo.setCurrentIndex(combo.findData(LAYOUT_SINGLE_PAGE))
    assert dialog.report_options.layout == LAYOUT_SINGLE_PAGE


def test_batch_report_options_carry_the_checkbox(qtbot) -> None:
    from ui.report_options_widget import ReportOptionsWidget

    widget = ReportOptionsWidget()
    qtbot.addWidget(widget)
    widget._include_unassigned_checkbox.setChecked(True)
    assert widget.report_options().include_unassigned_peaks is True
