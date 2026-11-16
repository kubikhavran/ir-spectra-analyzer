"""Publication IR text, copying the spectrum image, and PNG / SVG export."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from PySide6.QtWidgets import QApplication

from core.peak import Peak
from core.peak_assignments import format_publication_ir_string
from core.project import Project
from core.spectrum import SpectralUnit, Spectrum
from reporting.spectrum_renderer import SpectrumRenderer
from ui.peak_table_widget import PeakTableWidget

_WN = np.linspace(4000.0, 400.0, 1801)


def _assigned(position: float, intensity: float, label: str) -> Peak:
    return Peak(
        position=position, intensity=intensity, vibration_labels=[label], vibration_ids=[None]
    )


def _spectrum() -> Spectrum:
    y = np.full_like(_WN, 0.02)
    for centre, height in ((3340.0, 0.5), (2972.0, 0.3), (1715.0, 0.9)):
        y += height * np.exp(-((_WN - centre) ** 2) / (2 * 12.0**2))
    return Spectrum(_WN.copy(), y, y_unit=SpectralUnit.ABSORBANCE, title="Sample")


# ── IR text ──────────────────────────────────────────────────────────────────


def test_publication_string_lists_bands_high_to_low_with_strength() -> None:
    peaks = [
        _assigned(1715.3, 0.9, "ν(C=O)"),
        _assigned(3340.0, 0.5, "ν(OH)"),
        Peak(position=2972.0, intensity=0.3),
    ]
    assert format_publication_ir_string(peaks) == "IR (cm⁻¹): 3340 (m, ν(OH)), 1715 (vs, ν(C=O))."
    assert (
        format_publication_ir_string(peaks, include_unassigned=True)
        == "IR (cm⁻¹): 3340 (m, ν(OH)), 2972 (w), 1715 (vs, ν(C=O))."
    )
    assert format_publication_ir_string([]) == ""


def test_publication_string_reads_transmittance_dips() -> None:
    spectrum = Spectrum(_WN.copy(), np.full_like(_WN, 95.0), y_unit=SpectralUnit.TRANSMITTANCE)
    peaks = [_assigned(1715.0, 20.0, "ν(C=O)"), _assigned(2950.0, 90.0, "ν(CH)")]
    text = format_publication_ir_string(peaks, spectrum)
    assert text == "IR (cm⁻¹): 2950 (w, ν(CH)), 1715 (vs, ν(C=O))."


def test_copy_ir_text_button_puts_the_text_on_the_clipboard(qtbot) -> None:
    table = PeakTableWidget()
    qtbot.addWidget(table)
    table.set_peaks(
        [_assigned(1715.0, 0.9, "ν(C=O)"), Peak(position=1200.0, intensity=0.1)],
        is_dip_spectrum=False,
    )
    with qtbot.waitSignal(table.ir_text_copied, timeout=1000) as signal:
        table._copy_ir_btn.click()
    assert signal.args == ["IR (cm⁻¹): 1715 (vs, ν(C=O))."]
    assert QApplication.clipboard().text() == "IR (cm⁻¹): 1715 (vs, ν(C=O))."

    # Nothing assigned yet: every peak, so the button is never a dead end.
    table.set_peaks([Peak(position=1500.0, intensity=0.4)], is_dip_spectrum=False)
    assert table.copy_ir_text() == "IR (cm⁻¹): 1500 (vs)."


# ── Images ───────────────────────────────────────────────────────────────────


def test_renderer_writes_png_and_svg(qtbot) -> None:
    spectrum = _spectrum()
    renderer = SpectrumRenderer()
    png = renderer.render_to_bytes(spectrum.wavenumbers, spectrum.intensities, [], dpi=72)
    svg = renderer.render_to_bytes(
        spectrum.wavenumbers, spectrum.intensities, [], image_format="svg"
    )
    assert png.startswith(b"\x89PNG")
    assert b"<svg" in svg[:500]


def _window(qtbot):
    from ui.main_window import MainWindow

    db = MagicMock()
    db.get_vibration_presets.return_value = []
    settings = MagicMock()
    settings.get.return_value = None
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)
    return window


def test_copy_spectrum_image_puts_a_picture_on_the_clipboard(qtbot) -> None:
    window = _window(qtbot)
    assert not window._on_copy_spectrum_image()  # nothing loaded yet
    window._apply_project_to_ui(
        Project(name="p", spectrum=_spectrum(), peaks=[_assigned(1715.0, 0.92, "ν(C=O)")])
    )
    assert window._on_copy_spectrum_image()
    image = QApplication.clipboard().image()
    assert not image.isNull()
    assert image.width() > image.height()
    shortcuts = {
        action.shortcut().toString() for action in window.menuBar().actions()[1].menu().actions()
    }
    assert "Ctrl+Shift+C" in shortcuts


def test_export_spectrum_image_as_png_and_svg(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot)
    window._apply_project_to_ui(Project(name="p", spectrum=_spectrum()))

    png = tmp_path / "spectrum.png"
    with patch("ui.main_window.QFileDialog.getSaveFileName", return_value=(str(png), "")):
        assert window._export_spectrum_image()
    assert png.read_bytes().startswith(b"\x89PNG")

    svg_filter = "SVG vector image (*.svg)"
    bare = tmp_path / "vector"  # no extension typed: the chosen filter decides
    with patch("ui.main_window.QFileDialog.getSaveFileName", return_value=(str(bare), svg_filter)):
        assert window._export_spectrum_image()
    assert b"<svg" in (tmp_path / "vector.svg").read_bytes()[:500]


def test_export_dialog_offers_the_image(qtbot) -> None:
    from ui.dialogs.export_dialog import ExportDialog

    dialog = ExportDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._image_radio.setChecked(True)
    assert dialog.selected_format == "image"
    assert not dialog._include_unassigned_checkbox.isVisible()
    assert not dialog._csv_options.isVisible()
