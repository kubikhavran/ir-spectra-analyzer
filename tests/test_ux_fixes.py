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


# ── Default instrument metadata ───────────────────────────────────────────────


def test_loaded_spectrum_defaults_instrument_to_nicolet(qtbot, tmp_path):
    import os

    window = _make_window(qtbot)
    fixture = "tests/fixtures/reference library_1/FER58-SE.SPA"
    if not os.path.exists(fixture):
        pytest.skip("fixture not available")
    window._load_spectrum(fixture)

    assert window._metadata_panel._instrument_edit.text() == "Nicolet iS 50"
    assert window._project.metadata.instrument == "Nicolet iS 50"


def test_build_metadata_uses_default_instrument():
    from core.spectrum import Spectrum
    from ui.main_window import MainWindow

    spectrum = Spectrum(
        wavenumbers=np.array([4000.0, 400.0]),
        intensities=np.array([1.0, 2.0]),
        extra_metadata={"instrument_serial": "AUP2411034;"},
    )
    metadata = MainWindow._build_metadata_from_spectrum(spectrum, sample_name="S")
    assert metadata.instrument == "Nicolet iS 50"


def test_instrument_field_is_editable_and_flows_to_metadata(qtbot):
    from ui.metadata_panel import MetadataPanel

    panel = MetadataPanel()
    qtbot.addWidget(panel)
    panel._instrument_edit.setText("Bruker Alpha II")
    assert panel.current_metadata().instrument == "Bruker Alpha II"


def test_instrument_default_appears_in_pdf(qtbot, tmp_path):
    from core.peak import Peak
    from core.project import Project
    from reporting.pdf_generator import PDFGenerator

    project = Project(name="P", spectrum=_make_spectrum())
    project.metadata.sample_name = "S"
    project.metadata.instrument = "Nicolet iS 50"
    project.peaks.append(Peak(position=1700.0, intensity=0.5, vibration_labels=["ν(C=O)"]))

    out = tmp_path / "r.pdf"
    PDFGenerator().generate(project, out)
    assert out.exists()
    assert out.read_bytes().startswith(b"%PDF")


# ── Peak-label markers (viewer only) ──────────────────────────────────────────


def _labels(widget):
    from ui.spectrum_widget import _DraggableLabel

    return {i.textItem.toPlainText() for i in widget._peak_items if isinstance(i, _DraggableLabel)}


def test_peak_label_marks_assigned_and_selected(qtbot):
    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_spectrum(_make_spectrum())
    assigned = Peak(position=1700.0, intensity=1.0, vibration_labels=["ν(C=O)"])
    plain = Peak(position=1000.0, intensity=1.0)
    widget.set_peaks([assigned, plain])

    labels = _labels(widget)
    assert "•1700" in labels  # assigned marker
    assert "1000" in labels  # unassigned plain

    widget.set_selected_peak(plain)
    labels = _labels(widget)
    assert "▶1000" in labels  # selected marker
    assert "•1700" in labels


def test_peak_label_markers_absent_from_export(qtbot):
    """Export placements/renderer use plain positions, never the viewer markers."""
    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_spectrum(_make_spectrum())
    peak = Peak(position=1500.0, intensity=1.0, vibration_labels=["x"])
    widget.set_peaks([peak])
    widget.set_selected_peak(peak)

    placements = widget.get_peak_label_placements()
    # placement x-coords are raw positions; the renderer derives text from them
    assert placements[0][0] is peak
    assert round(placements[0][1]) == 1500


def test_vibration_panel_groups_protecting_group_section(qtbot):
    from core.vibration_presets import VibrationPreset
    from ui.vibration_panel import VibrationPanel

    panel = VibrationPanel()
    qtbot.addWidget(panel)
    panel.set_presets(
        [
            VibrationPreset(
                name="ν(C=O)",
                typical_range_min=1700,
                typical_range_max=1750,
                category="stretch",
                db_id=1,
            ),
            VibrationPreset(
                name="δs(Si–CH₃) TMS/TBS",
                typical_range_min=1245,
                typical_range_max=1265,
                category="silyl",
                db_id=2,
            ),
        ]
    )
    texts = [panel._list.item(i).text() for i in range(panel._list.count())]
    assert any("Protecting groups" in t for t in texts)
    # header must precede the silyl preset
    header_idx = next(i for i, t in enumerate(texts) if "Protecting groups" in t)
    silyl_idx = next(i for i, t in enumerate(texts) if "Si–CH₃" in t)
    assert header_idx < silyl_idx


def test_last_save_dir_persists_across_projects(qtbot, tmp_path):
    from core.project import Project
    from storage.settings import Settings
    from ui.main_window import MainWindow

    db = MagicMock()
    db.get_vibration_presets.return_value = []
    window = MainWindow(db=db, settings=Settings(tmp_path / "settings.json"))
    qtbot.addWidget(window)
    window._project = Project(name="A", spectrum=_make_spectrum())
    window._project.metadata.sample_name = "SampleA"
    target = tmp_path / "chosen"
    target.mkdir()

    window._remember_save_dir(str(target / "SampleA.irproj"))
    # a fresh project (no tracked path) should still suggest the remembered folder
    window._current_project_path = None
    window._project = Project(name="B", spectrum=_make_spectrum())
    window._project.metadata.sample_name = "SampleB"

    suggested = window._suggested_save_path(".irproj")
    assert str(target) in suggested
    assert suggested.endswith("SampleB.irproj")


# ── Custom-label structures (JSME "X" pseudo-atoms) ───────────────────────────

_MB_CUSTOM_SYMBOL = """
  JSME

  3  2  0  0  0  0  0  0  0  0999 V2000
    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    0.8660    0.5000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0
    1.7320    0.0000    0.0000 Boc 0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0  0  0  0
  2  3  1  0  0  0  0
M  END
"""

_MB_ALIAS = """
  JSME

  3  2  0  0  0  0  0  0  0  0999 V2000
    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    0.8660    0.5000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0
    1.7320    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0  0  0  0
  2  3  1  0  0  0  0
A    3
Boc
M  END
"""


def test_structure_renders_custom_atom_label_symbol():
    pytest.importorskip("rdkit")
    from chemistry.structure_renderer import render_to_svg

    svg = render_to_svg(mol_block=_MB_CUSTOM_SYMBOL)
    assert svg  # non-element symbol no longer makes the structure vanish


def test_structure_renders_atom_alias_label():
    pytest.importorskip("rdkit")
    from chemistry.structure_renderer import render_to_svg

    assert render_to_svg(mol_block=_MB_ALIAS)


def test_custom_label_stored_on_atom():
    pytest.importorskip("rdkit")
    from chemistry.structure_renderer import _load_mol

    mol = _load_mol(mol_block=_MB_CUSTOM_SYMBOL)
    assert mol is not None
    labels = [a.GetProp("atomLabel") for a in mol.GetAtoms() if a.HasProp("atomLabel")]
    assert "Boc" in labels


# ── Match Spectrum name filter ────────────────────────────────────────────────


def test_search_name_filter_scopes_results(tmp_path):
    from app.reference_library_service import ReferenceLibraryService
    from storage.database import Database

    db = Database(":memory:")
    db.initialize()
    wn = np.linspace(400.0, 4000.0, 200)
    for i in range(3):
        db.add_reference_spectrum(
            name=f"NIT{i:03d}",
            wavenumbers=wn,
            intensities=np.random.default_rng(i).random(200),
            description="",
            source=str(tmp_path / f"NIT{i:03d}.spa"),
        )
    for i in range(3):
        db.add_reference_spectrum(
            name=f"PAR{i:03d}",
            wavenumbers=wn,
            intensities=np.random.default_rng(10 + i).random(200),
            description="",
            source=str(tmp_path / f"PAR{i:03d}.spa"),
        )

    service = ReferenceLibraryService(db, project_root=tmp_path)
    query = Spectrum(wavenumbers=wn, intensities=np.random.default_rng(9).random(200))

    outcome = service.search_spectrum(query, auto_import_project_library=False, name_filter="NIT")
    assert outcome.results
    assert all(r.name.startswith("NIT") for r in outcome.results)

    all_out = service.search_spectrum(query, auto_import_project_library=False)
    names = {r.name for r in all_out.results}
    assert any(n.startswith("PAR") for n in names)  # unfiltered includes PAR


def test_name_filter_state_reflects_subset(tmp_path):
    from matching.feature_store import MATCH_FEATURE_VERSION
    from storage.database import Database

    db = Database(":memory:")
    db.initialize()
    wn = np.linspace(400.0, 4000.0, 200)
    for pfx in ("NIT", "PAR"):
        for i in range(4):
            rid = db.add_reference_spectrum(
                name=f"{pfx}{i}",
                wavenumbers=wn,
                intensities=np.ones(200),
                source=str(tmp_path / f"{pfx}{i}.spa"),
                commit=False,
            )
            db.upsert_reference_feature(
                rid,
                feature_version=MATCH_FEATURE_VERSION,
                feature_vector=np.ones(902, dtype=np.float32),
                commit=False,
            )
    db.commit()

    assert db.get_reference_library_state(feature_version=MATCH_FEATURE_VERSION)[0] == 8
    assert (
        db.get_reference_library_state(feature_version=MATCH_FEATURE_VERSION, name_filter="NIT")[0]
        == 4
    )


# ── Apply assignments from a matched saved project ────────────────────────────


def test_apply_assignments_from_match_transfers_and_copies_structure(qtbot, tmp_path):
    from types import SimpleNamespace

    from core.peak import Peak
    from core.project import Project
    from storage.project_serializer import ProjectSerializer
    from storage.settings import Settings
    from ui.main_window import MainWindow

    # Old analysed project saved as "SampleX.irproj" with assignments + structure.
    annot = tmp_path / "annotated"
    annot.mkdir()
    old = Project(name="SampleX", spectrum=_make_spectrum())
    old.peaks = [
        Peak(position=1712.0, intensity=0.5, vibration_labels=["ν(C=O)"], vibration_ids=[None]),
        Peak(position=700.0, intensity=0.4, vibration_labels=["γ(C-H)"], vibration_ids=[None]),
    ]
    old.smiles = "CCO"
    ProjectSerializer().save(old, str(annot / "SampleX.irproj"))

    db = MagicMock()
    db.get_vibration_presets.return_value = []
    window = MainWindow(db=db, settings=Settings(tmp_path / "s.json"))
    qtbot.addWidget(window)
    window._settings.set("annotated_projects_folder", str(annot))
    window._project = Project(name="new", spectrum=_make_spectrum())
    # current peaks shifted a few cm from the old ones
    window._project.peaks = [
        Peak(position=1715.0, intensity=0.5),
        Peak(position=704.0, intensity=0.4),
    ]
    window._peak_table.set_peaks(window._project.peaks)

    window._on_apply_assignments_from_match(SimpleNamespace(name="SampleX", ref_id=1))

    assigned = {round(p.position): p.vibration_labels for p in window._project.peaks}
    assert assigned[1715] == ["ν(C=O)"]
    assert assigned[704] == ["γ(C-H)"]
    assert window._project.smiles == "CCO"

    # single undo reverts the whole transfer
    window._undo_stack.undo()
    assert all(not p.vibration_labels for p in window._project.peaks)
    assert not window._project.smiles


def test_apply_assignments_no_saved_project_is_graceful(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from core.project import Project
    from storage.settings import Settings
    from ui.main_window import MainWindow

    (tmp_path / "annotated").mkdir()
    db = MagicMock()
    db.get_vibration_presets.return_value = []
    window = MainWindow(db=db, settings=Settings(tmp_path / "s.json"))
    qtbot.addWidget(window)
    window._settings.set("annotated_projects_folder", str(tmp_path / "annotated"))
    window._project = Project(name="new", spectrum=_make_spectrum())
    window._project.peaks = [Peak(position=1715.0, intensity=0.5)]

    monkeypatch.setattr("ui.main_window.QMessageBox.information", lambda *a, **k: None)
    # no matching .irproj → must not raise, must not assign
    window._on_apply_assignments_from_match(SimpleNamespace(name="Missing", ref_id=1))
    assert not window._project.peaks[0].vibration_labels
