"""Tests for the split X-axis feature (viewer split view + PDF renderer)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.peak import Peak
from core.spectrum import SpectralUnit, Spectrum


def _make_spectrum(y_unit: SpectralUnit = SpectralUnit.TRANSMITTANCE) -> Spectrum:
    wn = np.linspace(650, 4000, 400)
    ints = np.random.default_rng(0).uniform(20, 90, 400)
    return Spectrum(wavenumbers=wn, intensities=ints, y_unit=y_unit)


def _make_peaks() -> list[Peak]:
    return [
        Peak(position=1000.0, intensity=35.0),
        Peak(position=1500.0, intensity=45.0),
        Peak(position=3000.0, intensity=60.0),
    ]


# ── Renderer ──────────────────────────────────────────────────────────────────


def test_renderer_split_axis_produces_valid_png() -> None:
    """Split-axis render must return valid PNG bytes distinct from single-axis."""
    from reporting.spectrum_renderer import SpectrumRenderer

    spectrum = _make_spectrum()
    renderer = SpectrumRenderer()
    common = {
        "dpi": 80,
        "y_unit": spectrum.y_unit,
        "is_dip_spectrum": True,
        "x_min": 400.0,
        "x_max": 3800.0,
    }
    split_png = renderer.render_to_bytes(
        spectrum.wavenumbers, spectrum.intensities, _make_peaks(), split_at=2000.0, **common
    )
    single_png = renderer.render_to_bytes(
        spectrum.wavenumbers, spectrum.intensities, _make_peaks(), split_at=None, **common
    )

    assert split_png.startswith(b"\x89PNG")
    assert single_png.startswith(b"\x89PNG")
    assert split_png != single_png


def test_renderer_split_skipped_when_boundary_outside_view() -> None:
    """When the visible range does not straddle the split, render single-axis."""
    from reporting.spectrum_renderer import SpectrumRenderer

    spectrum = _make_spectrum()
    renderer = SpectrumRenderer()
    common = {
        "dpi": 80,
        "y_unit": spectrum.y_unit,
        "is_dip_spectrum": True,
        "x_min": 2200.0,
        "x_max": 3800.0,
    }
    with_split = renderer.render_to_bytes(
        spectrum.wavenumbers, spectrum.intensities, [], split_at=2000.0, **common
    )
    without_split = renderer.render_to_bytes(
        spectrum.wavenumbers, spectrum.intensities, [], split_at=None, **common
    )

    assert with_split == without_split


def test_pdf_generates_with_and_without_split(tmp_path: Path) -> None:
    """PDF export must succeed for both split_xaxis states."""
    from core.project import Project
    from reporting.pdf_generator import PDFGenerator, ReportOptions

    project = Project(name="Split test", spectrum=_make_spectrum())
    project.peaks.extend(_make_peaks())

    for split, name in ((True, "split.pdf"), (False, "nosplit.pdf")):
        out = tmp_path / name
        PDFGenerator().generate(
            project, out, options=ReportOptions(split_xaxis=split, include_structures=False)
        )
        assert out.exists()
        assert out.read_bytes().startswith(b"%PDF")


def test_report_preset_roundtrips_split_xaxis(tmp_path: Path) -> None:
    """split_xaxis must survive a named-preset save/load cycle."""
    from app.report_presets import ReportPresetManager
    from reporting.pdf_generator import ReportOptions
    from storage.settings import Settings

    manager = ReportPresetManager(Settings(tmp_path / "settings.json"))
    manager.save_preset("NoSplit", ReportOptions(split_xaxis=False))

    preset = manager.get_preset("NoSplit")
    assert preset is not None
    assert preset.options.split_xaxis is False


# ── Viewer split mode ─────────────────────────────────────────────────────────


def test_split_toggle_distributes_peaks_between_panels(qtbot):
    from ui.spectrum_widget import SpectrumWidget, _DraggableLabel

    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_spectrum(_make_spectrum())
    widget.set_peaks(_make_peaks())

    widget._split_btn.setChecked(True)

    main_labels = [i for i in widget._peak_items if isinstance(i, _DraggableLabel)]
    fp_labels = [i for i in widget._peak_items_fp if isinstance(i, _DraggableLabel)]
    assert len(main_labels) == 1  # 3000 cm⁻¹
    assert len(fp_labels) == 2  # 1000 + 1500 cm⁻¹


def test_split_toggle_off_restores_all_peaks_to_main_plot(qtbot):
    """Regression: disabling split view must not lose fingerprint-region peaks."""
    from ui.spectrum_widget import SpectrumWidget, _DraggableLabel

    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_spectrum(_make_spectrum())
    widget.set_peaks(_make_peaks())

    widget._split_btn.setChecked(True)
    widget._split_btn.setChecked(False)

    main_labels = [i for i in widget._peak_items if isinstance(i, _DraggableLabel)]
    assert len(main_labels) == 3
    assert not widget._peak_items_fp


def test_set_peaks_in_split_mode_keeps_fp_overlays_and_regions(qtbot):
    """Regression: re-rendering peaks must not wipe fp overlays/diagnostic regions."""
    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_spectrum(_make_spectrum())
    widget._split_btn.setChecked(True)

    widget.set_overlay_spectra([_make_spectrum()])
    region = MagicMock()
    region.range_min = 1600.0
    region.range_max = 1700.0
    region.is_missing_required = False
    region.is_confirmed = True
    region.color = "#1ABC9C"
    widget.set_diagnostic_regions([region])
    assert widget._overlay_curves_fp
    assert widget._diagnostic_region_items_fp

    widget.set_peaks(_make_peaks())

    assert widget._overlay_curves_fp
    assert widget._diagnostic_region_items_fp


def test_fp_panel_mouse_click_maps_through_fp_viewbox(qtbot):
    """Clicks in the fingerprint panel must resolve fingerprint wavenumbers."""
    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    widget.resize(1200, 700)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    widget.set_spectrum(_make_spectrum())
    widget._split_btn.setChecked(True)
    widget.set_add_peak_mode(True)
    qtbot.wait(50)  # let the fp panel receive its final layout geometry

    fp_vb = widget._fp_plot_widget.getPlotItem().vb
    scene_pos = fp_vb.mapViewToScene(pg_point(1200.0, 50.0))

    from PySide6.QtCore import Qt

    event = MagicMock()
    event.scenePos.return_value = scene_pos
    event.modifiers.return_value = Qt.KeyboardModifier.NoModifier

    captured: list[float] = []
    widget.peak_clicked.connect(lambda wn, inten, y: captured.append(wn))
    widget._on_fp_mouse_clicked(event)

    assert captured, "click inside the fp panel should emit peak_clicked"
    assert 400.0 <= captured[0] <= 2000.0


def pg_point(x: float, y: float):
    from PySide6.QtCore import QPointF

    return QPointF(x, y)


# ── Packaged-build data resolution ────────────────────────────────────────────


def test_functional_group_repository_resolves_meipass_bundle(tmp_path, monkeypatch):
    """Under PyInstaller, the KB must be found beneath sys._MEIPASS."""
    import shutil

    from storage import functional_group_repository as fgr

    bundled = tmp_path / "storage" / "data"
    bundled.mkdir(parents=True)
    source = Path(fgr.__file__).resolve().parent / "data" / "functional_groups.v1.json"
    shutil.copy(source, bundled)

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    resolved = fgr._default_data_path()

    assert resolved == bundled / "functional_groups.v1.json"
    assert fgr.FunctionalGroupRepository(resolved).load().groups


def test_main_window_survives_broken_functional_group_kb(qtbot, monkeypatch):
    """A failing knowledge base must clear the panel, not break spectrum load."""
    import processing.functional_group_scoring as fg_scoring
    from core.project import Project
    from ui.main_window import MainWindow

    def _raise(*args, **kwargs):
        raise FileNotFoundError("functional_groups.v1.json missing from bundle")

    monkeypatch.setattr(fg_scoring, "score_functional_groups", _raise)

    db = MagicMock()
    db.get_vibration_presets.return_value = []
    settings = MagicMock()
    settings.get.return_value = None

    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)
    window._project = Project(name="broken-kb", spectrum=_make_spectrum())

    window._refresh_functional_group_analysis()  # must not raise

    assert window._current_functional_group_results == []
    assert "unavailable" in window.statusBar().currentMessage()
