"""Tests for hover structure previews of matched spectra."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.structure_preview import StructurePreviewService
from core.peak import Peak
from core.project import Project
from core.project_structure import (
    ProjectStructureCache,
    read_project_structure,
)
from core.spectrum import SpectralUnit, Spectrum
from storage.project_serializer import ProjectSerializer

SMILES = "O=C(OCC)Nc1ccccc1"


def _save_project(path: Path, *, smiles: str = SMILES, points: int = 400) -> Path:
    """Write a realistic .irproj carrying a spectrum, peaks and a structure."""
    wn = np.linspace(650, 4000, points)
    ints = 97.0 - 30.0 * np.exp(-0.5 * ((wn - 1700) / 9.0) ** 2)
    project = Project(
        name=path.stem,
        spectrum=Spectrum(wavenumbers=wn, intensities=ints, y_unit=SpectralUnit.TRANSMITTANCE),
    )
    project.smiles = smiles
    # A peak carries its own "smiles" key — the reader must not pick that one up.
    project.peaks.append(Peak(position=1700.0, intensity=67.0, smiles="DECOY"))
    ProjectSerializer().save(project, str(path))
    return path


def test_reads_structure_without_parsing_the_whole_project(tmp_path: Path) -> None:
    """The scan stops after the structure fields — proven by corrupting the rest."""
    path = _save_project(tmp_path / "FER60-SE.irproj")
    text = path.read_text(encoding="utf-8")
    marker = text.index('"spectrum"')
    # Everything from the spectrum on is now unparseable JSON. A full json.load
    # would raise; the head scan must still return the structure.
    path.write_text(text[:marker] + '"spectrum": {{{ NOT JSON', encoding="utf-8")

    structure = read_project_structure(path)

    assert structure.smiles == SMILES
    assert bool(structure) is True


def test_project_level_structure_wins_over_peak_fields(tmp_path: Path) -> None:
    """A peak's own smiles field must never be mistaken for the project's."""
    path = _save_project(tmp_path / "with-decoy.irproj")

    assert read_project_structure(path).smiles == SMILES


def test_project_without_structure_reads_as_empty(tmp_path: Path) -> None:
    """A saved project with no molecule assigned yields a falsy structure."""
    path = _save_project(tmp_path / "bare.irproj", smiles="")

    structure = read_project_structure(path)

    assert structure.smiles == ""
    assert bool(structure) is False


def test_unreadable_file_is_not_an_error(tmp_path: Path) -> None:
    """A missing or junk file reports "no structure" instead of raising."""
    assert bool(read_project_structure(tmp_path / "missing.irproj")) is False
    junk = tmp_path / "junk.irproj"
    junk.write_text("not json at all", encoding="utf-8")
    assert bool(read_project_structure(junk)) is False


def test_structure_cache_rereads_only_after_the_file_changes(tmp_path: Path) -> None:
    """Repeated lookups hit the cache; editing the project invalidates it."""
    path = _save_project(tmp_path / "cached.irproj")
    cache = ProjectStructureCache()
    reads: list[Path] = []

    import core.project_structure as module

    original = module.read_project_structure

    def _counting_read(target, **kwargs):
        reads.append(Path(target))
        return original(target, **kwargs)

    module.read_project_structure = _counting_read
    try:
        assert cache.get(path).smiles == SMILES
        assert cache.get(path).smiles == SMILES
        assert len(reads) == 1

        _save_project(path, smiles="CCO")
        os.utime(path, (0, 0))  # force a different mtime regardless of clock speed
        assert cache.get(path).smiles == "CCO"
        assert len(reads) == 2
    finally:
        module.read_project_structure = original


def test_preview_service_renders_and_caches(tmp_path: Path) -> None:
    """A name maps to PNG bytes, and a second hover costs no extra render."""
    path = _save_project(tmp_path / "FER60-SE.irproj")
    service = StructurePreviewService()
    service.set_project_paths({"fer60-se": path})

    png = service.preview_png("FER60-SE")
    assert png is not None
    assert png[:4] == b"\x89PNG"

    import app.structure_preview as module

    renders: list[str] = []
    original = module.StructurePreviewService._render

    def _counting_render(self, target):
        renders.append(str(target))
        return original(self, target)

    module.StructurePreviewService._render = _counting_render
    try:
        assert service.preview_png("fer60-se") == png  # case-insensitive + cached
        assert renders == []
    finally:
        module.StructurePreviewService._render = original


def test_preview_service_returns_none_when_there_is_nothing_to_show(tmp_path: Path) -> None:
    """Unknown names, missing files and structure-less projects all yield None."""
    bare = _save_project(tmp_path / "bare.irproj", smiles="")
    service = StructurePreviewService()
    service.set_project_paths({"bare": bare, "gone": tmp_path / "gone.irproj"})

    assert service.preview_png("bare") is None
    assert service.preview_png("gone") is None
    assert service.preview_png("never-searched") is None


def test_changing_the_projects_folder_drops_stale_previews(tmp_path: Path) -> None:
    """Pointing at another folder must not keep showing the old structures."""
    first = _save_project(tmp_path / "a.irproj")
    second = _save_project(tmp_path / "b.irproj", smiles="CCO")
    service = StructurePreviewService()

    service.set_project_paths({"a": first})
    assert service.preview_png("a") is not None

    service.set_project_paths({"b": second})
    assert service.preview_png("a") is None
    assert service.preview_png("b") is not None


def test_panel_shows_the_structure_on_hover(qtbot, tmp_path: Path) -> None:
    """Hovering a match asks the provider once and shows the returned image."""
    from types import SimpleNamespace

    from ui.match_results_panel import MatchResultsPanel

    path = _save_project(tmp_path / "FER60-SE.irproj")
    service = StructurePreviewService()
    service.set_project_paths({"fer60-se": path})

    asked: list[str] = []

    def _provider(name: str) -> bytes | None:
        asked.append(name)
        return service.preview_png(name)

    panel = MatchResultsPanel()
    qtbot.addWidget(panel)
    panel.set_structure_preview_provider(_provider)
    panel.set_results(
        [
            SimpleNamespace(ref_id=1, name="FER60-SE", score=0.9, fingerprint_score=0.9),
            SimpleNamespace(ref_id=2, name="NO-PROJECT", score=0.5, fingerprint_score=0.5),
        ]
    )

    panel._list.itemEntered.emit(panel._list.item(0))
    assert asked == ["FER60-SE"]
    popup = panel._preview_popup
    assert popup is not None
    assert popup.isVisible()
    assert not popup.pixmap().isNull()

    # A match with nothing saved hides whatever was on screen.
    panel._list.itemEntered.emit(panel._list.item(1))
    assert asked == ["FER60-SE", "NO-PROJECT"]
    assert not popup.isVisible()


def test_main_window_feeds_the_panel_from_the_annotated_projects_folder(
    qtbot, tmp_path: Path
) -> None:
    """End to end: setting the folder makes hovering a match show its structure."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from storage.settings import Settings
    from ui.main_window import MainWindow

    folder = tmp_path / "annotated"
    folder.mkdir()
    _save_project(folder / "FER60-SE.irproj")

    settings = Settings(tmp_path / "settings.json")
    settings.load()
    settings.set("annotated_projects_folder", str(folder))
    db = MagicMock()
    db.get_vibration_presets.return_value = []
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)

    panel = window._match_results_panel
    # Selecting a row would draw a spectrum overlay out of the mocked database,
    # which is not what this test is about.
    panel.candidate_selected.disconnect(window._on_match_candidate_selected)

    window._refresh_saved_project_names()
    panel.set_results(
        [SimpleNamespace(ref_id=1, name="FER60-SE", score=0.9, fingerprint_score=0.9)]
    )

    panel._list.itemEntered.emit(panel._list.item(0))

    assert panel._preview_popup is not None
    assert panel._preview_popup.isVisible()


def test_panel_hover_is_inert_without_a_provider(qtbot) -> None:
    """Without a provider the panel never pops anything up."""
    from types import SimpleNamespace

    from ui.match_results_panel import MatchResultsPanel

    panel = MatchResultsPanel()
    qtbot.addWidget(panel)
    panel.set_results([SimpleNamespace(ref_id=1, name="X", score=0.9, fingerprint_score=0.9)])

    panel._list.itemEntered.emit(panel._list.item(0))

    assert panel._preview_popup is None


def test_new_results_take_the_preview_off_screen(qtbot, tmp_path: Path) -> None:
    """A fresh search must not leave the previous molecule floating around."""
    from types import SimpleNamespace

    from ui.match_results_panel import MatchResultsPanel

    path = _save_project(tmp_path / "FER60-SE.irproj")
    service = StructurePreviewService()
    service.set_project_paths({"fer60-se": path})

    panel = MatchResultsPanel()
    qtbot.addWidget(panel)
    panel.set_structure_preview_provider(service.preview_png)
    panel.set_results(
        [SimpleNamespace(ref_id=1, name="FER60-SE", score=0.9, fingerprint_score=0.9)]
    )

    panel._list.itemEntered.emit(panel._list.item(0))
    assert panel._preview_popup is not None
    assert panel._preview_popup.isVisible()

    panel.set_results([SimpleNamespace(ref_id=2, name="OTHER", score=0.4, fingerprint_score=0.4)])

    assert not panel._preview_popup.isVisible()
