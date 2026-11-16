"""CSV and Excel export options: contents, decimal comma, formats, structure, chart."""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import openpyxl
import pytest

from core.peak import Peak
from core.peak_assignments import intensity_unit_label
from core.project import Project
from core.spectrum import BASELINE_CORRECTED_FLAG, SpectralUnit, Spectrum
from file_io.csv_exporter import CSVExporter
from file_io.xlsx_exporter import XLSXExporter
from ui import i18n

_WN = np.linspace(4000.0, 400.0, 361)


def _absorbance() -> Spectrum:
    y = 0.8 * np.exp(-((_WN - 1715.0) ** 2) / (2 * 15.0**2)) + 0.02
    return Spectrum(_WN.copy(), y, y_unit=SpectralUnit.ABSORBANCE, title="Sample A")


def _transmittance() -> Spectrum:
    return Spectrum(
        _WN.copy(),
        100.0 - 40.0 * np.exp(-((_WN - 1715.0) ** 2) / (2 * 15.0**2)),
        y_unit=SpectralUnit.TRANSMITTANCE,
        title="Sample T",
    )


def _peaks() -> list[Peak]:
    return [
        Peak(position=1715.0, intensity=0.82, vibration_labels=["ν(C=O)"], vibration_ids=[None]),
        Peak(position=2950.4, intensity=0.1234),
    ]


def _rows(path: Path, delimiter: str = ";") -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle, delimiter=delimiter))


# ── Unit label ───────────────────────────────────────────────────────────────


def test_unit_label_follows_the_curve_and_the_correction() -> None:
    assert intensity_unit_label(None) == "Intensity"
    assert intensity_unit_label(_absorbance()) == "Absorbance"
    # %T numbers under an "Absorbance" header are exported as what they are.
    mislabeled = Spectrum(_WN.copy(), _transmittance().intensities, y_unit=SpectralUnit.ABSORBANCE)
    assert intensity_unit_label(mislabeled) == "Transmittance"
    corrected = Spectrum(
        _WN.copy(),
        _transmittance().intensities,
        y_unit=SpectralUnit.TRANSMITTANCE,
        extra_metadata={BASELINE_CORRECTED_FLAG: True},
    )
    assert intensity_unit_label(corrected) == "Transmittance, baseline corrected"


# ── CSV ──────────────────────────────────────────────────────────────────────


def test_default_csv_is_the_combined_layout(tmp_path: Path) -> None:
    out = tmp_path / "a.csv"
    CSVExporter().export(_peaks(), out, _absorbance(), include_unassigned=True)
    header = _rows(out)[0]
    assert header[:2] == ["Field", "Value"]
    assert "Position (cm⁻¹)" in header
    assert "Wavenumber (cm⁻¹)" in header


def test_peaks_only_csv_is_one_plain_table(tmp_path: Path) -> None:
    out = tmp_path / "p.csv"
    CSVExporter().export(_peaks(), out, _absorbance(), include_unassigned=True, mode="peaks_only")
    rows = _rows(out)
    assert rows[0] == [
        "Position (cm⁻¹)",
        "Intensity (Absorbance)",
        "Rel. intensity",
        "Assignment",
    ]
    assert rows[1] == ["2950", "0.1234", "w", ""]
    assert rows[2][0] == "1715"
    assert rows[2][3] == "ν(C=O)"
    assert len(rows) == 3


def test_spectrum_only_csv_with_decimal_comma(tmp_path: Path) -> None:
    out = tmp_path / "s.csv"
    CSVExporter().export([], out, _transmittance(), mode="spectrum_only", decimal_separator=",")
    rows = _rows(out)
    assert rows[0] == ["Wavenumber (cm⁻¹)", "Intensity (Transmittance)"]
    assert len(rows) == 1 + len(_WN)
    assert rows[1][0] == "4000,00"
    assert "," in rows[1][1]
    assert "." not in rows[1][1]


def test_invalid_csv_options_are_refused(tmp_path: Path) -> None:
    out = tmp_path / "x.csv"
    with pytest.raises(ValueError, match="mode"):
        CSVExporter().export([], out, _absorbance(), mode="everything")
    with pytest.raises(ValueError, match="separator"):
        CSVExporter().export([], out, _absorbance(), decimal_separator=";")
    with pytest.raises(ValueError, match="differ"):
        CSVExporter().export([], out, _absorbance(), delimiter=",", decimal_separator=",")
    with pytest.raises(ValueError, match="spectrum"):
        CSVExporter().export([], out, None, mode="spectrum_only")
    assert not out.exists()


# ── Excel ────────────────────────────────────────────────────────────────────


def test_excel_cells_carry_number_formats_filter_and_shading(tmp_path: Path) -> None:
    out = tmp_path / "a.xlsx"
    XLSXExporter().export(_peaks(), out, _absorbance(), include_unassigned=True)
    wb = openpyxl.load_workbook(out)
    peaks = wb["Peaks"]
    assert peaks["A2"].number_format == "0"
    assert peaks["B2"].number_format == "0.0000"  # absorbance
    assert peaks.auto_filter.ref == "A1:D3"
    assert peaks.freeze_panes == "A2"
    assert peaks["A3"].fill.fgColor.rgb.endswith("F2F5F8")
    assert peaks["A2"].fill.fill_type is None
    spectrum = wb["Spectrum"]
    assert spectrum["A2"].number_format == "0.00"
    assert spectrum["B2"].number_format == "0.0000"
    assert len(spectrum._charts) == 0  # off unless asked for

    out_t = tmp_path / "t.xlsx"
    XLSXExporter().export(_peaks(), out_t, _transmittance(), include_unassigned=True)
    wb_t = openpyxl.load_workbook(out_t)
    assert wb_t["Peaks"]["B2"].number_format == "0.00"  # %T
    assert wb_t["Spectrum"]["B2"].number_format == "0.00"


def test_excel_chart_runs_from_high_to_low_wavenumber(tmp_path: Path) -> None:
    out = tmp_path / "c.xlsx"
    XLSXExporter().export(_peaks(), out, _transmittance(), include_chart=True)
    wb = openpyxl.load_workbook(out)
    # openpyxl does not read charts back; check the written chart XML.
    import zipfile

    with zipfile.ZipFile(out) as archive:
        charts = [name for name in archive.namelist() if name.startswith("xl/charts/chart")]
        assert len(charts) == 1
        xml = archive.read(charts[0]).decode()
    assert 'orientation val="maxMin"' in xml
    assert "Wavenumber" in xml
    assert "Spectrum" in wb.sheetnames


def test_blanked_points_are_empty_cells(tmp_path: Path) -> None:
    spectrum = _absorbance()
    spectrum.intensities[10:20] = np.nan
    out = tmp_path / "n.xlsx"
    XLSXExporter().export([], out, spectrum)
    ws = openpyxl.load_workbook(out)["Spectrum"]
    assert ws.cell(row=12, column=2).value is None
    assert ws.cell(row=2, column=2).value is not None

    csv_out = tmp_path / "n.csv"
    CSVExporter().export([], csv_out, spectrum, mode="spectrum_only")
    csv_rows = _rows(csv_out)
    assert csv_rows[11][1] == ""
    assert csv_rows[1][1] != ""


def test_structure_is_placed_beside_the_metadata(tmp_path: Path, qtbot) -> None:
    project = Project(name="p", spectrum=_absorbance(), smiles="CC(=O)O")
    out = tmp_path / "s.xlsx"
    XLSXExporter().export([], out, project.spectrum, project=project)
    images = openpyxl.load_workbook(out)["Metadata"]._images
    assert len(images) == 1
    assert max(images[0].width, images[0].height) <= 320

    plain = tmp_path / "plain.xlsx"
    XLSXExporter().export([], plain, project.spectrum, project=Project(name="q"))
    assert openpyxl.load_workbook(plain)["Metadata"]._images == []


# ── Dialog and window ────────────────────────────────────────────────────────


def test_dialog_shows_each_option_for_its_format(qtbot) -> None:
    from ui.dialogs.export_dialog import ExportDialog

    dialog = ExportDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    assert not dialog._csv_options.isVisible()
    assert not dialog._include_chart_checkbox.isVisible()

    dialog._csv_radio.setChecked(True)
    assert dialog._csv_options.isVisible()
    assert dialog.csv_mode == "combined"
    assert dialog.decimal_separator == "."  # English UI
    dialog._csv_mode_combo.setCurrentIndex(dialog._csv_mode_combo.findData("spectrum_only"))
    assert dialog.csv_mode == "spectrum_only"
    assert not dialog._include_unassigned_checkbox.isVisible()  # no peaks in that file

    dialog._xlsx_radio.setChecked(True)
    assert dialog._include_chart_checkbox.isVisible()
    assert dialog.include_chart  # on by default in the dialog
    assert not dialog._csv_options.isVisible()


def test_dialog_offers_the_decimal_comma_in_czech(qtbot) -> None:
    from ui.dialogs.export_dialog import ExportDialog

    i18n.set_language(i18n.CZECH)
    try:
        dialog = ExportDialog()
        qtbot.addWidget(dialog)
        assert dialog.decimal_separator == ","
    finally:
        i18n.set_language(i18n.ENGLISH)


def test_csv_from_a_converted_view_exports_the_shown_unit(qtbot, tmp_path: Path) -> None:
    from ui.main_window import MainWindow

    db = MagicMock()
    db.get_vibration_presets.return_value = []
    settings = MagicMock()
    settings.get.return_value = None
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)
    window._apply_project_to_ui(Project(name="p", spectrum=_absorbance()))
    window._spectrum_widget.set_display_unit(SpectralUnit.TRANSMITTANCE)

    out = tmp_path / "shown.csv"
    with patch("ui.main_window.QFileDialog.getSaveFileName", return_value=(str(out), "")):
        window._export_csv(mode="spectrum_only")
    rows = _rows(out)
    assert rows[0][1] == "Intensity (Transmittance)"
    assert 0.0 < float(rows[1][1]) <= 100.0
    # The project itself is still absorbance.
    assert window._project.spectrum.y_unit == SpectralUnit.ABSORBANCE
