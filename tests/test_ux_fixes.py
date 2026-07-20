"""Regression tests for the 2026-07-14 UX/bug-fix batch."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.peak import Peak
from core.spectrum import Spectrum


def _make_spectrum() -> Spectrum:
    wn = np.linspace(400.0, 4000.0, 200)
    intensities = 1.0 + 0.5 * np.exp(-0.5 * ((wn - 1500.0) / 40.0) ** 2)
    return Spectrum(wavenumbers=wn, intensities=intensities, title="T")


def _make_window(qtbot):
    from ui.main_window import MainWindow

    db = MagicMock()
    db.get_vibration_presets.return_value = []
    settings = MagicMock()
    settings.get.return_value = None
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)
    return window


def _make_preset(name: str = "ν(C=O) test", lo: float = 1600.0, hi: float = 1800.0):
    from core.vibration_presets import VibrationPreset

    return VibrationPreset(name=name, typical_range_min=lo, typical_range_max=hi, db_id=1)


# ── Assignment flow ───────────────────────────────────────────────────────────


def test_clicking_preset_assigns_to_selected_peak(qtbot):
    from core.project import Project

    window = _make_window(qtbot)
    window._project = Project(name="T", spectrum=_make_spectrum())
    peak = Peak(position=1700.0, intensity=0.5)
    window._project.add_peak(peak)
    window._peak_table.set_peaks(window._project.peaks)
    window._peak_table._table.setCurrentCell(0, 0)

    window._on_preset_clicked_for_assign(_make_preset())

    assert "ν(C=O) test" in peak.vibration_labels


def test_clicking_preset_without_selected_peak_does_not_assign(qtbot):
    from core.project import Project

    window = _make_window(qtbot)
    window._project = Project(name="T", spectrum=_make_spectrum())
    peak = Peak(position=1700.0, intensity=0.5)
    window._project.add_peak(peak)
    window._peak_table.set_peaks(window._project.peaks)
    window._peak_table._table.clearSelection()
    window._peak_table._table.setCurrentCell(-1, -1)

    window._on_preset_clicked_for_assign(_make_preset())

    assert not peak.vibration_labels


def test_viewer_peak_click_only_selects_never_assigns(qtbot):
    """Regression: selecting a peak in the viewer must not consume any preset."""
    from core.project import Project

    window = _make_window(qtbot)
    window._project = Project(name="T", spectrum=_make_spectrum())
    first = Peak(position=1700.0, intensity=0.5)
    second = Peak(position=1000.0, intensity=0.4)
    window._project.add_peak(first)
    window._project.add_peak(second)
    window._peak_table.set_peaks(window._project.peaks)

    window._peak_table._table.setCurrentCell(0, 0)
    window._on_preset_clicked_for_assign(_make_preset())  # assigns to `first`
    window._on_peak_selected_in_viewer(second)  # must NOT assign anything

    assert not second.vibration_labels
    assert not hasattr(window, "_pending_preset")


# ── Peak ordering ─────────────────────────────────────────────────────────────


def test_add_peak_inserts_sorted_descending():
    from core.project import Project

    project = Project(name="T", spectrum=_make_spectrum())
    for position in (1000.0, 3000.0, 2000.0, 3500.0):
        project.add_peak(Peak(position=position, intensity=0.5))

    assert [peak.position for peak in project.peaks] == [3500.0, 3000.0, 2000.0, 1000.0]


# ── Vibration panel ───────────────────────────────────────────────────────────


def test_vibration_panel_rebuild_preserves_scroll(qtbot):
    from ui.vibration_panel import VibrationPanel

    panel = VibrationPanel()
    panel.resize(300, 200)
    qtbot.addWidget(panel)
    panel.show()
    qtbot.waitExposed(panel)
    presets = [_make_preset(name=f"preset {i}", lo=400.0 + i, hi=500.0 + i) for i in range(80)]
    panel.set_presets(presets)
    panel._list.scrollToItem(panel._list.item(40))
    top_before = panel._list.itemAt(2, 2).data(256)

    panel.highlight_for_peak(450.0)

    assert panel._list.itemAt(2, 2).data(256) is top_before


def test_vibration_panel_functional_group_tag_filters_presets(qtbot):
    from ui.vibration_panel import VibrationPanel

    panel = VibrationPanel()
    qtbot.addWidget(panel)
    acid = _make_preset(name="ν(C=O) acid", lo=1690.0, hi=1760.0)
    alkyl = _make_preset(name="νas(CH₃)", lo=2950.0, hi=2975.0)
    panel.set_presets([acid, alkyl])
    panel.set_functional_group_tags([("Carboxylic Acid", frozenset({"ν(C=O) acid"}))])

    assert panel._list.count() == 2  # "All functional groups"
    panel._tag_combo.setCurrentIndex(1)
    assert panel._list.count() == 1
    assert panel._list.item(0).data(256) is acid


# ── Structure rendering with unusual valences ─────────────────────────────────


@pytest.mark.parametrize("smiles", ["B(C)(C)(C)(C)", "F[P](F)(F)(F)(F)F"])
def test_structure_renderer_survives_unusual_valences(smiles):
    pytest.importorskip("rdkit")
    from chemistry.structure_renderer import render_to_svg, smiles_to_mol_block

    assert render_to_svg(smiles=smiles)
    assert smiles_to_mol_block(smiles)


# ── PDF label placements ──────────────────────────────────────────────────────


def test_renderer_uses_exact_viewer_label_placements():
    from reporting.spectrum_renderer import SpectrumRenderer

    spectrum = _make_spectrum()
    peak = Peak(position=1500.0, intensity=0.4)
    renderer = SpectrumRenderer()
    common = {
        "dpi": 80,
        "y_unit": spectrum.y_unit,
        "is_dip_spectrum": False,
        "x_min": 400.0,
        "x_max": 3800.0,
        "split_at": None,
    }
    default_png = renderer.render_to_bytes(
        spectrum.wavenumbers, spectrum.intensities, [peak], **common
    )
    placed_png = renderer.render_to_bytes(
        spectrum.wavenumbers,
        spectrum.intensities,
        [peak],
        label_placements={id(peak): (1500.0, 0.9)},
        **common,
    )
    assert placed_png.startswith(b"\x89PNG")
    assert placed_png != default_png


# ── Reference-library search caching ─────────────────────────────────────────


def test_repeated_search_skips_feature_reload(tmp_path):
    from app.reference_library_service import ReferenceLibraryService
    from storage.database import Database

    db = Database(":memory:")
    db.initialize()
    wn = np.linspace(400.0, 4000.0, 200)
    for i in range(3):
        db.add_reference_spectrum(
            name=f"ref{i}",
            wavenumbers=wn,
            intensities=np.random.default_rng(i).random(200),
            description="",
            source=str(tmp_path / f"ref{i}.spa"),
        )

    service = ReferenceLibraryService(db, project_root=tmp_path)
    query = Spectrum(wavenumbers=wn, intensities=np.random.default_rng(9).random(200))

    calls = {"n": 0}
    original = db.get_reference_search_rows

    def _counting(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    db.get_reference_search_rows = _counting

    first = service.search_spectrum(query, auto_import_project_library=False)
    second = service.search_spectrum(query, auto_import_project_library=False)

    assert first.results
    assert second.results
    assert calls["n"] == 1  # second search reused the loaded matrix
    assert [r.ref_id for r in first.results] == [r.ref_id for r in second.results]


# ── Zoom preserved on add-peak / undo-redo ────────────────────────────────────


def test_add_peak_preserves_zoom(qtbot):
    """Regression: adding a peak while zoomed in must not reset the view."""
    from core.project import Project

    window = _make_window(qtbot)
    window._project = Project(name="Z", spectrum=_make_spectrum())
    window._spectrum_widget.set_spectrum(window._project.spectrum)
    vb = window._spectrum_widget._plot_widget.getPlotItem().vb
    window._spectrum_widget._plot_widget.setXRange(1400.0, 1700.0, padding=0.0)
    before = [round(v, 1) for v in vb.viewRange()[0]]

    window._on_peak_clicked(1550.0, 1.2, 1.2)

    after = [round(v, 1) for v in vb.viewRange()[0]]
    assert after == before == [1400.0, 1700.0]


def test_set_spectrum_preserve_view_keeps_range(qtbot):
    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    spectrum = _make_spectrum()
    widget.set_spectrum(spectrum)
    widget._plot_widget.setXRange(1400.0, 1700.0, padding=0.0)

    widget.set_spectrum(spectrum, preserve_view=True)

    vb = widget._plot_widget.getPlotItem().vb
    assert [round(v, 1) for v in vb.viewRange()[0]] == [1400.0, 1700.0]


# ── Export/save filename defaults from Sample metadata ────────────────────────


def test_default_export_basename_uses_sample_metadata(qtbot):
    from core.project import Project

    window = _make_window(qtbot)
    window._project = Project(name="proj-name", spectrum=_make_spectrum())
    window._project.metadata.sample_name = "Sample-42"
    assert window._default_export_basename() == "Sample-42"


def test_default_export_basename_sanitizes_illegal_chars(qtbot):
    from core.project import Project

    window = _make_window(qtbot)
    window._project = Project(name="p", spectrum=_make_spectrum())
    window._project.metadata.sample_name = "A/B:C*?"
    assert "/" not in window._default_export_basename()
    assert ":" not in window._default_export_basename()


def test_default_export_basename_falls_back_to_project_name(qtbot):
    from core.project import Project

    window = _make_window(qtbot)
    window._project = Project(name="ProjectX", spectrum=_make_spectrum())
    assert window._default_export_basename() == "ProjectX"


def test_suggested_save_path_uses_project_directory(qtbot, tmp_path):
    from core.project import Project
    from storage.project_serializer import ProjectSerializer

    window = _make_window(qtbot)
    window._project = Project(name="P", spectrum=_make_spectrum())
    window._project.metadata.sample_name = "MySample"
    proj_path = tmp_path / "saved.irproj"
    ProjectSerializer().save(window._project, str(proj_path))

    window._load_project_from_path(str(proj_path))

    assert window._current_project_path == str(proj_path)
    suggested = window._suggested_save_path(".csv")
    assert suggested == str(tmp_path / "MySample.csv")
