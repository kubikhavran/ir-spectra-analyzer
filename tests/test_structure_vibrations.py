"""The drawn structure narrows the Vibrations panel and marks its bands in the plot."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from chemistry.structure_motifs import perceive_smiles
from core.project import Project
from core.vibration_presets import VibrationPreset
from file_io.spa_reader import SPAReader
from storage.database import Database
from ui.structure_bands import motif_colors, structure_bands
from ui.vibration_panel import MODE_STRUCTURE, VibrationPanel

FIXTURES = Path(__file__).parent / "fixtures"


def _library() -> list[VibrationPreset]:
    return [
        VibrationPreset(
            name=name,
            typical_range_min=low,
            typical_range_max=high,
            category=category,
            seed_name=name,
        )
        for name, low, high, category, _description, _color in Database._builtin_vibration_catalog()
    ]


def _rows(panel: VibrationPanel) -> list[str]:
    return [panel._list.item(row).data(256).name for row in panel.preset_rows()]


def _headers(panel: VibrationPanel) -> list[str]:
    return [
        panel._list.item(row).text()
        for row in range(panel._list.count())
        if panel._list.item(row).data(257) is not None
    ]


def test_structure_mode_lists_only_the_structures_vibrations(qtbot) -> None:
    panel = VibrationPanel()
    qtbot.addWidget(panel)
    panel.set_presets(_library())
    panel.set_view_mode(MODE_STRUCTURE)
    panel.set_structure_motifs(perceive_smiles("CCOC(C)=O"))  # ethyl acetate

    rows = set(_rows(panel))
    assert "ν(C=O) –CO–O– sat. ester" in rows
    assert "νs(COC) R–CO–O–R' sat." in rows
    assert "νas(CH₃) –CH₃" in rows
    assert not any("amide" in name or "aldehyde" in name or "Ar" in name.split() for name in rows)
    headers = " ".join(_headers(panel))
    assert "Ester" in headers
    assert "Methyl" in headers


def test_structure_mode_puts_the_vibrations_that_fit_the_peak_first(qtbot) -> None:
    panel = VibrationPanel()
    qtbot.addWidget(panel)
    panel.set_presets(_library())
    panel.set_view_mode(MODE_STRUCTURE)
    panel.set_structure_motifs(perceive_smiles("CC(C)(C)OC(=O)NCCO"))  # Boc-aminoethanol
    panel.highlight_for_peak(1700.0)

    first_header = panel._list.item(0).data(257)
    assert first_header == "fits"
    fitting = []
    for row in range(1, panel._list.count()):
        item = panel._list.item(row)
        if item.data(257) is not None:
            break
        fitting.append(item.data(256).name)
    assert "ν(C=O) –NH–CO–O– carbamate" in fitting
    assert all(name != "ν(C=O) –CO–O– sat. ester" for name in fitting)


def test_structure_mode_without_a_structure_explains_itself(qtbot) -> None:
    panel = VibrationPanel()
    qtbot.addWidget(panel)
    panel.set_presets(_library())
    panel.set_view_mode(MODE_STRUCTURE)
    assert panel.preset_rows() == []
    assert "Draw a structure" in panel._list.item(0).text()


def test_bands_get_one_lane_and_colour_per_group() -> None:
    found = perceive_smiles("CC(=O)Nc1ccc(O)cc1")  # paracetamol
    bands = structure_bands(found, _library())
    colors = motif_colors(found)
    lanes = {band.motif_id: band.lane for band in bands}
    assert len(set(lanes.values())) == len(lanes)
    assert {"secondary_amide", "phenol"} <= set(lanes)
    assert "methyl" not in lanes  # skeleton groups are listed, not drawn
    for band in bands:
        assert band.color == colors[band.motif_id]
        assert band.low < band.high


def test_main_window_follows_the_drawn_structure(qtbot, tmp_path) -> None:
    from ui.main_window import MainWindow

    db = Database(tmp_path / "db.sqlite")
    db.initialize()
    settings = MagicMock()
    settings.get.side_effect = lambda key, default=None: default
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)
    spectrum = SPAReader().read(FIXTURES / "atrcor.spa")
    window._apply_project_to_ui(Project(name="m", spectrum=spectrum, smiles="CO"))

    ids = {f.id for f in window._vibration_panel.structure_motifs()}
    assert "primary_alcohol" in ids
    bands = window._spectrum_widget.structure_bands()
    assert any(b.motif_id == "primary_alcohol" for b in bands)
    assert window._spectrum_widget._structure_band_items

    window._vibration_panel._show_structure_bands_checkbox.setChecked(False)
    assert not window._spectrum_widget._structure_band_items
    window._vibration_panel._show_structure_bands_checkbox.setChecked(True)
    assert window._spectrum_widget._structure_band_items

    window._project.smiles = "CCOC(C)=O"
    window._refresh_structure_motifs()
    ids = {f.id for f in window._vibration_panel.structure_motifs()}
    assert "ester" in ids
    assert "primary_alcohol" not in ids

    window._project.smiles = ""
    window._refresh_structure_motifs()
    assert window._vibration_panel.structure_motifs() == []
    assert window._spectrum_widget.structure_bands() == []
    db.close()


def test_structure_bands_survive_split_view(qtbot) -> None:
    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_spectrum(SPAReader().read(FIXTURES / "atrcor.spa"))
    widget.set_structure_bands(structure_bands(perceive_smiles("CO"), _library()))
    widget._on_split_toggled(True)
    assert widget._structure_band_items
    assert widget._structure_band_items_fp
    widget._on_split_toggled(False)
    assert widget._structure_band_items
