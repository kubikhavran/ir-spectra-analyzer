"""Tests for MainWindow and peak interaction (headless, no display)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spectrum():
    """Create a minimal synthetic Spectrum."""
    from core.spectrum import Spectrum

    wavenumbers = np.linspace(400.0, 4000.0, 100)
    intensities = np.random.default_rng(0).random(100)
    return Spectrum(wavenumbers=wavenumbers, intensities=intensities, title="Test")


def _make_mock_db():
    """Return a mock Database with the methods MainWindow uses."""
    from unittest.mock import MagicMock

    db = MagicMock()
    db.get_vibration_presets.return_value = []
    return db


def _make_mock_settings():
    """Return a mock Settings object."""
    from unittest.mock import MagicMock

    settings = MagicMock()
    settings.get.return_value = None
    return settings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_main_window_creates(qtbot):
    """MainWindow should instantiate as a QMainWindow."""
    from PySide6.QtWidgets import QMainWindow

    from ui.main_window import MainWindow

    db = _make_mock_db()
    settings = _make_mock_settings()
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)

    assert isinstance(window, QMainWindow)


def test_spectrum_widget_set_spectrum(qtbot):
    """SpectrumWidget.set_spectrum should store the spectrum."""
    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    qtbot.addWidget(widget)

    spectrum = _make_spectrum()
    widget.set_spectrum(spectrum)

    assert widget._spectrum is not None
    assert widget._spectrum is spectrum


def test_spectrum_widget_set_peaks(qtbot):
    """SpectrumWidget.set_peaks should not raise and should store peaks."""
    from core.peak import Peak
    from ui.spectrum_widget import SpectrumWidget, _DraggableLabel

    widget = SpectrumWidget()
    qtbot.addWidget(widget)

    spectrum = _make_spectrum()
    widget.set_spectrum(spectrum)

    peaks = [Peak(position=1000.0, intensity=0.5)]
    widget.set_peaks(peaks)  # must not raise

    assert len(widget._peaks) == 1
    labels = [item for item in widget._peak_items if isinstance(item, _DraggableLabel)]
    assert len(labels) == 1
    assert labels[0]._data_y == pytest.approx(0.5 + 0.065 * np.ptp(spectrum.intensities))


def test_spectrum_widget_places_auto_labels_below_dip_like_percent_style_spectrum(qtbot):
    """Percent-style dip spectra should place automatic labels below the curve."""
    from core.peak import Peak
    from core.spectrum import SpectralUnit, Spectrum
    from ui.spectrum_widget import SpectrumWidget, _DraggableLabel

    widget = SpectrumWidget()
    qtbot.addWidget(widget)

    spectrum = Spectrum(
        wavenumbers=np.array([400.0, 1000.0, 1600.0, 2500.0, 4000.0]),
        intensities=np.array([99.8, 98.5, 72.0, 97.9, 100.0]),
        title="Percent-style",
        y_unit=SpectralUnit.ABSORBANCE,
    )
    widget.set_spectrum(spectrum)
    widget.set_peaks([Peak(position=1600.0, intensity=72.0)])

    assert spectrum.display_y_unit == SpectralUnit.TRANSMITTANCE
    labels = [item for item in widget._peak_items if isinstance(item, _DraggableLabel)]
    assert len(labels) == 1
    assert labels[0]._data_y < 72.0


def test_manual_peak_labels_anchor_to_each_peak_curve_level(qtbot):
    """Manually added peaks should place labels directly at each peak's own curve level."""
    from core.project import Project
    from core.spectrum import Spectrum
    from ui.main_window import MainWindow
    from ui.spectrum_widget import _DraggableLabel

    window = MainWindow(db=_make_mock_db(), settings=_make_mock_settings())
    qtbot.addWidget(window)

    wavenumbers = np.array([4000.0, 3000.0, 2000.0, 1000.0, 400.0])
    intensities = np.array([0.2, 0.8, 0.35, 1.2, 0.1])
    spectrum = Spectrum(wavenumbers=wavenumbers, intensities=intensities, title="Manual peaks")
    window._project = Project(name="Manual peaks", spectrum=spectrum)
    window._spectrum_widget.set_spectrum(spectrum)

    window._on_peak_clicked(3000.0, 0.8, 0.8)
    window._on_peak_clicked(1000.0, 1.2, 1.2)

    labels = [
        item for item in window._spectrum_widget._peak_items if isinstance(item, _DraggableLabel)
    ]
    labels_by_peak = {item._peak_x: item for item in labels}

    assert labels_by_peak[3000.0]._data_y == pytest.approx(0.8)
    assert labels_by_peak[1000.0]._data_y == pytest.approx(1.2)
    assert labels_by_peak[3000.0]._data_y != pytest.approx(labels_by_peak[1000.0]._data_y)


def test_spectrum_widget_honors_manual_label_offsets_from_peak_model(qtbot):
    """Explicit peak label offsets stored in the model must drive label rendering."""
    from core.peak import Peak
    from ui.spectrum_widget import SpectrumWidget, _DraggableLabel

    widget = SpectrumWidget()
    qtbot.addWidget(widget)

    spectrum = _make_spectrum()
    widget.set_spectrum(spectrum)

    peak = Peak(
        position=1000.0,
        intensity=0.5,
        manual_placement=True,
        label_offset_x=12.0,
        label_offset_y=-0.2,
    )
    widget.set_peaks([peak])

    labels = [item for item in widget._peak_items if isinstance(item, _DraggableLabel)]
    assert len(labels) == 1
    assert labels[0]._data_x == pytest.approx(1012.0)
    assert labels[0]._data_y == pytest.approx(0.3)


def test_sideways_label_uses_shorter_diagonal_segment(qtbot):
    """Sideways label placement should keep the diagonal branch visually short."""
    import pyqtgraph as pg

    from core.peak import Peak
    from ui.spectrum_widget import _DraggableLabel

    peak = Peak(position=1500.0, intensity=80.0, manual_placement=True)
    label = _DraggableLabel(
        peak=peak,
        peak_x=1500.0,
        peak_y=80.0,
        label_offset=20.0,
        label_x=1450.0,
        label_y=100.0,
        text="1500.0",
    )
    leader = pg.PlotCurveItem()
    label.set_leader(leader)

    x_data, y_data = leader.getData()
    assert x_data is not None
    assert y_data is not None
    assert y_data[0] == pytest.approx(80.0)
    assert y_data[2] == pytest.approx(100.0)
    assert y_data[1] == pytest.approx(93.0)
    assert (y_data[2] - y_data[1]) == pytest.approx(7.0)


def test_sideways_label_uses_shorter_diagonal_segment_for_transmittance(qtbot):
    """The shortened diagonal should also behave correctly for dip-like spectra."""
    import pyqtgraph as pg

    from core.peak import Peak
    from ui.spectrum_widget import _DraggableLabel

    peak = Peak(position=1500.0, intensity=88.0, manual_placement=True)
    label = _DraggableLabel(
        peak=peak,
        peak_x=1500.0,
        peak_y=88.0,
        label_offset=-20.0,
        label_x=1550.0,
        label_y=68.0,
        text="1500.0",
    )
    leader = pg.PlotCurveItem()
    label.set_leader(leader)

    x_data, y_data = leader.getData()
    assert x_data is not None
    assert y_data is not None
    assert y_data[0] == pytest.approx(88.0)
    assert y_data[2] == pytest.approx(68.0)
    assert y_data[1] == pytest.approx(75.0)
    assert (y_data[1] - y_data[2]) == pytest.approx(7.0)


def test_manual_peak_labels_anchor_to_curve_level_for_transmittance(qtbot):
    """Manual peaks in transmittance mode should still start from each dip's own level."""
    from core.project import Project
    from core.spectrum import SpectralUnit, Spectrum
    from ui.main_window import MainWindow
    from ui.spectrum_widget import _DraggableLabel

    window = MainWindow(db=_make_mock_db(), settings=_make_mock_settings())
    qtbot.addWidget(window)

    wavenumbers = np.array([4000.0, 3000.0, 2000.0, 1000.0, 400.0])
    intensities = np.array([99.0, 81.5, 94.0, 88.2, 98.5])
    spectrum = Spectrum(
        wavenumbers=wavenumbers,
        intensities=intensities,
        title="Transmittance peaks",
        y_unit=SpectralUnit.TRANSMITTANCE,
    )
    window._project = Project(name="Transmittance peaks", spectrum=spectrum)
    window._spectrum_widget.set_spectrum(spectrum)

    window._on_peak_clicked(3000.0, 81.5, 81.5)
    window._on_peak_clicked(1000.0, 88.2, 88.2)

    labels = [
        item for item in window._spectrum_widget._peak_items if isinstance(item, _DraggableLabel)
    ]
    labels_by_peak = {item._peak_x: item for item in labels}

    assert labels_by_peak[3000.0]._data_y == pytest.approx(81.5)
    assert labels_by_peak[1000.0]._data_y == pytest.approx(88.2)
    assert labels_by_peak[3000.0]._data_y != pytest.approx(labels_by_peak[1000.0]._data_y)


def test_manual_peak_click_uses_interpolated_curve_intensity(qtbot):
    """Manual peak picking should use the real curve intensity at each clicked wavenumber."""
    from core.project import Project
    from core.spectrum import Spectrum
    from ui.main_window import MainWindow

    window = MainWindow(db=_make_mock_db(), settings=_make_mock_settings())
    qtbot.addWidget(window)

    wavenumbers = np.array([400.0, 1000.0, 1452.0, 3000.0, 4000.0])
    intensities = np.array([0.1, 0.81, 0.55, 0.32, 0.2])
    spectrum = Spectrum(wavenumbers=wavenumbers, intensities=intensities, title="Interpolation")
    window._project = Project(name="Interpolation", spectrum=spectrum)
    window._spectrum_widget.set_spectrum(spectrum)

    for x in (1000.0, 1452.0, 3000.0):
        intensity = window._spectrum_widget._intensity_at(x)
        window._on_peak_clicked(x, intensity, intensity)

    observed = {peak.position: peak.intensity for peak in window._project.peaks}
    assert observed[1000.0] == pytest.approx(0.81)
    assert observed[1452.0] == pytest.approx(0.55)
    assert observed[3000.0] == pytest.approx(0.32)


def test_peak_table_set_peaks(qtbot):
    """PeakTableWidget.set_peaks should populate the table correctly."""
    from core.peak import Peak
    from ui.peak_table_widget import PeakTableWidget

    widget = PeakTableWidget()
    qtbot.addWidget(widget)

    peaks = [Peak(position=1000.0, intensity=0.5), Peak(position=2000.0, intensity=0.3)]
    widget.set_peaks(peaks)

    assert widget._table.rowCount() == 2


def test_main_window_load_spectrum_updates_widget(qtbot, tmp_path):
    """_load_spectrum should update the spectrum widget with the loaded spectrum."""
    import sys
    import types
    from unittest.mock import MagicMock

    from ui.main_window import MainWindow

    spectrum = _make_spectrum()

    db = _make_mock_db()
    settings = _make_mock_settings()
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)

    # Create a dummy .spa file path (content doesn't matter — we mock the registry)
    spa_file = tmp_path / "test.spa"
    spa_file.write_bytes(b"\x00" * 16)

    # _load_spectrum uses a local `from file_io.format_registry import FormatRegistry`.
    # Inject a fake module into sys.modules so the import resolves to our mock.
    fake_fr_mod = types.ModuleType("file_io.format_registry")
    mock_registry_cls = MagicMock()
    mock_registry_cls.return_value.read.return_value = spectrum
    fake_fr_mod.FormatRegistry = mock_registry_cls

    original = sys.modules.get("file_io.format_registry")
    sys.modules["file_io.format_registry"] = fake_fr_mod
    try:
        window._load_spectrum(str(spa_file))
    finally:
        if original is None:
            sys.modules.pop("file_io.format_registry", None)
        else:
            sys.modules["file_io.format_registry"] = original

    assert window._spectrum_widget._spectrum is not None


def test_main_window_load_spectrum_uses_stored_annotated_peaks(qtbot, tmp_path):
    """Stored OMNIC annotated peaks should appear immediately after loading the file."""
    import sys
    import types
    from unittest.mock import MagicMock

    from core.spectrum import SpectralUnit, Spectrum
    from ui.main_window import MainWindow

    spectrum = Spectrum(
        wavenumbers=np.array([400.0, 1000.0, 1700.0, 2500.0, 4000.0]),
        intensities=np.array([99.0, 95.0, 74.5, 97.0, 100.0]),
        title="Stored peaks",
        y_unit=SpectralUnit.TRANSMITTANCE,
        extra_metadata={
            "annotated_peaks": [
                {"position": 1700.0, "intensity": 74.5},
                {"position": 1000.0, "intensity": 95.0},
            ]
        },
    )

    db = _make_mock_db()
    settings = _make_mock_settings()
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)

    spa_file = tmp_path / "stored.spa"
    spa_file.write_bytes(b"\x00" * 16)

    fake_fr_mod = types.ModuleType("file_io.format_registry")
    mock_registry_cls = MagicMock()
    mock_registry_cls.return_value.read.return_value = spectrum
    fake_fr_mod.FormatRegistry = mock_registry_cls

    original = sys.modules.get("file_io.format_registry")
    sys.modules["file_io.format_registry"] = fake_fr_mod
    try:
        window._load_spectrum(str(spa_file))
    finally:
        if original is None:
            sys.modules.pop("file_io.format_registry", None)
        else:
            sys.modules["file_io.format_registry"] = original

    assert window._project is not None
    assert [peak.position for peak in window._project.peaks] == [1700.0, 1000.0]
    assert [peak.intensity for peak in window._project.peaks] == [74.5, 95.0]
    assert window._peak_table._table.rowCount() == 2


def test_vibration_panel_preset_selected_signal(qtbot):
    """Double-clicking a preset in VibrationPanel emits preset_selected."""
    from core.vibration_presets import VibrationPreset
    from ui.vibration_panel import VibrationPanel

    panel = VibrationPanel()
    qtbot.addWidget(panel)

    preset = VibrationPreset(name="C-H stretch", typical_range_min=2800, typical_range_max=3000)
    panel.set_presets([preset])

    received = []
    panel.preset_selected.connect(received.append)

    # Simulate double-click on the first item
    item = panel._list.item(0)
    panel._list.itemDoubleClicked.emit(item)

    assert len(received) == 1
    assert received[0].name == "C-H stretch"


def test_vibration_panel_highlight_for_peak(qtbot):
    """highlight_for_peak sets background on matching presets."""
    from core.vibration_presets import VibrationPreset
    from ui.vibration_panel import VibrationPanel

    panel = VibrationPanel()
    qtbot.addWidget(panel)

    presets = [
        VibrationPreset(name="C-H stretch", typical_range_min=2800, typical_range_max=3000),
        VibrationPreset(name="C=O stretch", typical_range_min=1700, typical_range_max=1750),
    ]
    panel.set_presets(presets)
    panel.highlight_for_peak(2918.0)  # falls in C-H stretch range

    # Hint label updated
    assert "2918" in panel._hint_label.text()


def test_vibration_panel_filter(qtbot):
    """Text filter hides non-matching presets."""
    from core.vibration_presets import VibrationPreset
    from ui.vibration_panel import VibrationPanel

    panel = VibrationPanel()
    qtbot.addWidget(panel)

    presets = [
        VibrationPreset(name="C-H stretch", typical_range_min=2800, typical_range_max=3000),
        VibrationPreset(name="C=O stretch", typical_range_min=1700, typical_range_max=1750),
        VibrationPreset(name="O-H bend", typical_range_min=1300, typical_range_max=1420),
    ]
    panel.set_presets(presets)

    panel._filter_edit.setText("C=O")
    assert panel._list.count() == 1
    assert "C=O" in panel._list.item(0).text()


def test_add_vibration_dialog_supports_symbol_editing(qtbot):
    """Custom vibration dialog should support Greek letters and index conversion."""
    from ui.vibration_panel import _AddVibrationDialog

    dialog = _AddVibrationDialog()
    qtbot.addWidget(dialog)

    dialog._name_edit.set_text("v(CH3) cm-1")
    dialog._name_edit.line_edit.setSelection(0, 1)
    dialog._name_edit.insert_text("ν")
    dialog._name_edit.line_edit.setSelection(4, 1)
    dialog._name_edit.apply_subscript()
    dialog._name_edit.line_edit.setSelection(len("ν(CH₃) cm"), 2)
    dialog._name_edit.apply_superscript()

    assert dialog.get_values()[0] == "ν(CH₃) cm⁻¹"


def test_preset_assigned_to_peak_updates_label(qtbot):
    """Assigning a preset updates peak label and is reflected in PeakTableWidget."""
    from core.peak import Peak
    from core.vibration_presets import VibrationPreset
    from ui.peak_table_widget import PeakTableWidget

    table = PeakTableWidget()
    qtbot.addWidget(table)

    peak = Peak(position=2918.0, intensity=50.0)
    table.set_peaks([peak])

    # Simulate assignment
    preset = VibrationPreset(
        name="C-H stretch", typical_range_min=2800, typical_range_max=3000, db_id=1
    )
    peak.vibration_id = preset.db_id
    peak.label = preset.name
    table.set_peaks([peak])  # refresh

    assert table._table.item(0, 2).text() == "C-H stretch"


def test_peak_table_emits_vibration_edit_request_on_double_click(qtbot):
    """Double-clicking the vibration column should request the dedicated editor dialog."""
    from core.peak import Peak
    from ui.peak_table_widget import PeakTableWidget

    table = PeakTableWidget()
    qtbot.addWidget(table)

    peak = Peak(position=1715.0, intensity=0.7, vibration_labels=["C=O stretch"])
    table.set_peaks([peak])

    received = []
    table.vibration_edit_requested.connect(received.append)

    table._on_cell_double_clicked(0, 3)

    assert received == [peak]


def test_main_window_manual_vibration_edit_updates_peak_and_supports_undo(qtbot, monkeypatch):
    """Manual vibration text editing should update the peak and remain undoable."""
    from PySide6.QtWidgets import QDialog

    from core.peak import Peak
    from core.project import Project
    from ui.main_window import MainWindow

    window = MainWindow(db=_make_mock_db(), settings=_make_mock_settings())
    qtbot.addWidget(window)

    peak = Peak(
        position=1715.0,
        intensity=0.7,
        vibration_ids=[42],
        vibration_labels=["C=O stretch"],
    )
    window._project = Project(name="Manual vibration", spectrum=_make_spectrum())
    window._project.peaks.append(peak)
    window._peak_table.set_peaks(window._project.peaks)
    window._peak_table.select_peak(peak)

    captured: dict[str, str | None] = {"text": None}

    class _FakeDialog:
        def __init__(self, parent=None, *, title="", label="", text="") -> None:
            captured["text"] = text

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

        def value(self) -> str:
            return "δd(CH₃) CH₃–C=O/N/S"

    monkeypatch.setattr("ui.main_window.VibrationTextEditDialog", _FakeDialog)

    window._on_edit_peak_vibration_requested(peak)

    assert captured["text"] == "C=O stretch"
    assert peak.vibration_labels == ["δd(CH₃) CH₃–C=O/N/S"]
    assert peak.vibration_ids == [None]
    assert window._peak_table._table.item(0, 3).text() == "δd(CH₃) CH₃–C=O/N/S"

    window._undo_stack.undo()

    assert peak.vibration_labels == ["C=O stretch"]
    assert peak.vibration_ids == [42]


def test_set_tool_mode_zoom(qtbot):
    """set_tool_mode('zoom') switches ViewBox to RectMode."""
    import pyqtgraph as pg

    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    qtbot.addWidget(widget)

    widget.set_tool_mode("zoom")
    vb = widget._plot_widget.getPlotItem().vb
    assert vb.state["mouseMode"] == pg.ViewBox.RectMode


def test_set_tool_mode_pan(qtbot):
    """set_tool_mode('pan') switches ViewBox to PanMode."""
    import pyqtgraph as pg

    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    qtbot.addWidget(widget)

    widget.set_tool_mode("pan")
    vb = widget._plot_widget.getPlotItem().vb
    assert vb.state["mouseMode"] == pg.ViewBox.PanMode


def test_set_tool_mode_add_peak(qtbot):
    """set_tool_mode('add_peak') enables _add_peak_mode."""
    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    qtbot.addWidget(widget)

    widget.set_tool_mode("add_peak")
    assert widget._add_peak_mode is True


def test_add_to_recent_dedupes(qtbot):
    """Recent files: duplicate paths are moved to front."""
    from unittest.mock import MagicMock

    from ui.main_window import MainWindow

    settings = MagicMock()
    settings.get.return_value = ["/old/a.spa", "/old/b.spa"]
    window = MainWindow(db=MagicMock(), settings=settings)
    qtbot.addWidget(window)

    window._add_to_recent("/old/a.spa")
    saved = settings.set.call_args[0][1]
    assert saved[0] == "/old/a.spa"
    assert saved.count("/old/a.spa") == 1


def test_open_recent_routes_irproj_to_project_loader(qtbot, monkeypatch):
    """Recent project files must reopen through the project loader, not SPA import."""
    from ui.main_window import MainWindow

    window = MainWindow(db=_make_mock_db(), settings=_make_mock_settings())
    qtbot.addWidget(window)

    project_calls: list[str] = []
    spectrum_calls: list[str] = []
    monkeypatch.setattr(window, "_load_project_from_path", lambda path: project_calls.append(path))
    monkeypatch.setattr(window, "_load_spectrum", lambda path: spectrum_calls.append(path))

    window._open_recent_path("/tmp/test.irproj")
    window._open_recent_path("/tmp/test.spa")

    assert project_calls == ["/tmp/test.irproj"]
    assert spectrum_calls == ["/tmp/test.spa"]


def test_delete_peak_shortcut(qtbot):
    """_on_delete_peak removes selected peak from project and refreshes UI."""
    from unittest.mock import MagicMock

    import numpy as np

    from core.peak import Peak
    from core.project import Project
    from core.spectrum import Spectrum
    from ui.main_window import MainWindow

    window = MainWindow(db=MagicMock(), settings=MagicMock())
    qtbot.addWidget(window)

    wn = np.linspace(400.0, 4000.0, 100)
    sp = Spectrum(wavenumbers=wn, intensities=np.ones(100), title="T")
    window._project = Project(name="T", spectrum=sp)
    peaks = [Peak(position=1000.0, intensity=0.5), Peak(position=2000.0, intensity=0.3)]
    for p in peaks:
        window._project.add_peak(p)
    window._peak_table.set_peaks(window._project.peaks)
    window._spectrum_widget.set_spectrum(sp)

    # select the first row
    window._peak_table._table.setCurrentCell(0, 0)
    window._on_delete_peak()

    assert len(window._project.peaks) == 1
    assert window._project.peaks[0].position == pytest.approx(2000.0)


def test_main_window_save_and_open_project(qtbot, tmp_path):
    from unittest.mock import patch

    from core.peak import Peak
    from core.project import Project
    from core.spectrum import Spectrum
    from ui.main_window import MainWindow

    db = _make_mock_db()
    settings = _make_mock_settings()
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)

    wn = np.linspace(400.0, 4000.0, 10)
    spectrum = Spectrum(wavenumbers=wn, intensities=np.linspace(0.0, 1.0, 10), title="Test")
    project = Project(name="Test", spectrum=spectrum)
    project.peaks.append(Peak(position=1000.0, intensity=0.5, label="P1", vibration_id=99))
    window._project = project

    project_path = tmp_path / "test_project.irproj"

    with patch(
        "ui.main_window.QFileDialog.getSaveFileName",
        return_value=(str(project_path), "IR Project Files (*.irproj)"),
    ):
        window._on_save_project()

    # intentionally clear to validate load path
    window._project = None
    window._spectrum_widget._spectrum = None

    with patch(
        "ui.main_window.QFileDialog.getOpenFileName",
        return_value=(str(project_path), "IR Project Files (*.irproj)"),
    ):
        window._on_open_project()

    assert window._project is not None
    assert window._project.name == "Test"
    assert len(window._project.peaks) == 1
    assert window._project.peaks[0].vibration_id == 99


def test_main_window_save_and_open_project_restores_metadata_and_vibrations(qtbot, tmp_path):
    from unittest.mock import patch

    from core.peak import Peak
    from core.project import Project
    from core.spectrum import Spectrum
    from ui.main_window import MainWindow

    db = _make_mock_db()
    settings = _make_mock_settings()
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)

    wn = np.linspace(400.0, 4000.0, 10)
    spectrum = Spectrum(wavenumbers=wn, intensities=np.linspace(0.0, 1.0, 10), title="Raw Title")
    project = Project(name="Project Name", spectrum=spectrum)
    project.peaks.append(
        Peak(
            position=1250.0,
            intensity=0.5,
            label="P1",
            vibration_id=99,
            vibration_ids=[99, None],
            vibration_labels=["ν(C=O)", "custom note"],
            manual_placement=True,
            label_offset_x=8.0,
            label_offset_y=-0.2,
        )
    )
    window._project = project
    window._peak_table.set_peaks(project.peaks)
    window._metadata_panel._title_edit.setText("Edited Title")
    window._metadata_panel._sample_edit.setText("Sample A")
    window._metadata_panel._operator_edit.setText("Analyst X")

    project_path = tmp_path / "restored_project.irproj"

    with patch(
        "ui.main_window.QFileDialog.getSaveFileName",
        return_value=(str(project_path), "IR Project Files (*.irproj)"),
    ):
        window._on_save_project()

    window._project = None
    window._spectrum_widget._spectrum = None

    with patch(
        "ui.main_window.QFileDialog.getOpenFileName",
        return_value=(str(project_path), "IR Project Files (*.irproj)"),
    ):
        window._on_open_project()

    assert window._project is not None
    assert len(window._project.peaks) == 1
    loaded_peak = window._project.peaks[0]
    assert loaded_peak.vibration_ids == [99, None]
    assert loaded_peak.vibration_labels == ["ν(C=O)", "custom note"]
    assert loaded_peak.manual_placement is True
    assert loaded_peak.label_offset_x == pytest.approx(8.0)
    assert loaded_peak.label_offset_y == pytest.approx(-0.2)
    assert window._peak_table._table.item(0, 3).text() == "ν(C=O) / custom note"
    assert window._metadata_panel._title_edit.text() == "Edited Title"
    assert window._metadata_panel._sample_edit.text() == "Sample A"
    assert window._metadata_panel._operator_edit.text() == "Analyst X"
    assert window._project.metadata.title == "Edited Title"
    assert window._project.metadata.sample_name == "Sample A"
    assert window._project.metadata.operator == "Analyst X"


def test_export_dialog_defaults_to_all_report_sections_enabled(qtbot):
    """The main export dialog should default to PDF with all report sections enabled."""
    from reporting.pdf_generator import ReportOptions
    from ui.dialogs.export_dialog import ExportDialog

    dialog = ExportDialog()
    qtbot.addWidget(dialog)

    assert dialog.selected_format == "pdf"
    assert dialog.report_options == ReportOptions()


def test_main_window_on_export_passes_report_options_from_dialog(qtbot, monkeypatch):
    """Interactive export should pass the dialog's report options into PDF export."""
    from core.project import Project
    from reporting.pdf_generator import ReportOptions
    from ui.main_window import MainWindow

    window = MainWindow(db=_make_mock_db(), settings=_make_mock_settings())
    qtbot.addWidget(window)
    window._project = Project(name="Test", spectrum=_make_spectrum())

    selected_options = ReportOptions(
        include_structures=False,
        include_peak_table=False,
        include_metadata=True,
    )
    captured: dict[str, object] = {"options": None, "preset_manager": None, "remembered": False}

    class _FakeDialog:
        Accepted = 1

        def __init__(self, parent=None, *, preset_manager=None) -> None:
            self._parent = parent
            captured["preset_manager"] = preset_manager

        def exec(self) -> int:
            return self.Accepted

        @property
        def selected_format(self) -> str:
            return "pdf"

        @property
        def report_options(self) -> ReportOptions:
            return selected_options

        def remember_selected_preset(self) -> None:
            captured["remembered"] = True

    monkeypatch.setattr("ui.dialogs.export_dialog.ExportDialog", _FakeDialog)
    monkeypatch.setattr(
        window, "_export_pdf", lambda options=None: captured.__setitem__("options", options) or True
    )

    window._on_export()

    assert captured["options"] == selected_options
    assert captured["preset_manager"] is window._report_preset_manager
    assert captured["remembered"] is True


def test_main_window_export_pdf_uses_default_report_builder(qtbot, tmp_path):
    """Calling _export_pdf without explicit options should still use build_with_options."""
    from unittest.mock import MagicMock, patch

    from core.project import Project
    from ui.main_window import MainWindow

    window = MainWindow(db=_make_mock_db(), settings=_make_mock_settings())
    qtbot.addWidget(window)
    window._project = Project(name="Test", spectrum=_make_spectrum())
    output_path = tmp_path / "report.pdf"
    builder = MagicMock()

    with (
        patch(
            "ui.main_window.QFileDialog.getSaveFileName",
            return_value=(str(output_path), "PDF Files (*.pdf)"),
        ),
        patch("reporting.report_builder.ReportBuilder", return_value=builder),
    ):
        window._export_pdf()

    builder.build.assert_not_called()
    builder.build_with_options.assert_called_once()


def test_main_window_export_pdf_uses_selected_report_options(qtbot, tmp_path):
    """Calling _export_pdf with options should route through build_with_options."""
    from unittest.mock import MagicMock, patch

    from core.project import Project
    from reporting.pdf_generator import ReportOptions
    from ui.main_window import MainWindow

    window = MainWindow(db=_make_mock_db(), settings=_make_mock_settings())
    qtbot.addWidget(window)
    window._project = Project(name="Test", spectrum=_make_spectrum())
    output_path = tmp_path / "report.pdf"
    builder = MagicMock()
    options = ReportOptions(
        include_structures=False,
        include_peak_table=False,
        include_metadata=False,
    )

    with (
        patch(
            "ui.main_window.QFileDialog.getSaveFileName",
            return_value=(str(output_path), "PDF Files (*.pdf)"),
        ),
        patch("reporting.report_builder.ReportBuilder", return_value=builder),
    ):
        window._export_pdf(options)

    builder.build.assert_not_called()
    builder.build_with_options.assert_called_once_with(window._project, output_path, options)


# ---------------------------------------------------------------------------
# Project-level SMILES tests
# ---------------------------------------------------------------------------


def test_load_project_shows_project_smiles_in_molecule_widget(qtbot, tmp_path):
    """Loading a project with project.smiles='CCO' shows 'CCO' in molecule_widget."""
    from unittest.mock import patch

    from core.peak import Peak
    from core.project import Project
    from core.spectrum import Spectrum
    from storage.project_serializer import ProjectSerializer
    from ui.main_window import MainWindow

    db = _make_mock_db()
    settings = _make_mock_settings()
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)

    wn = np.linspace(400.0, 4000.0, 10)
    spectrum = Spectrum(wavenumbers=wn, intensities=np.linspace(0.0, 1.0, 10), title="T")
    project = Project(name="Mol", spectrum=spectrum, smiles="CCO")
    project.peaks.append(
        Peak(position=1000.0, intensity=0.5, smiles="c1ccccc1")
    )  # peak smiles differ

    project_path = tmp_path / "project_smiles.irproj"
    ProjectSerializer().save(project, project_path)

    with patch(
        "ui.main_window.QFileDialog.getOpenFileName",
        return_value=(str(project_path), "IR Project Files (*.irproj)"),
    ):
        window._on_open_project()

    assert window._project is not None
    assert window._project.smiles == "CCO"
    # molecule_widget should show project-level SMILES, not the peak's SMILES
    assert window._molecule_widget._current_smiles == "CCO"


def test_on_structure_edited_updates_project_smiles_without_peak_selected(qtbot):
    """_on_structure_edited pushes SetProjectSMILESCommand and updates project.smiles."""
    from core.project import Project
    from core.spectrum import Spectrum
    from ui.main_window import MainWindow

    db = _make_mock_db()
    settings = _make_mock_settings()
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)

    wn = np.linspace(400.0, 4000.0, 10)
    spectrum = Spectrum(wavenumbers=wn, intensities=np.linspace(0.0, 1.0, 10), title="T")
    window._project = Project(name="Test", spectrum=spectrum)

    # No peak selected — should still work now
    assert window._peak_table.selected_peak() is None

    window._on_structure_edited("CCO")

    assert window._project.smiles == "CCO"
    # Note: _current_smiles on the widget is already updated by the widget itself
    # before emitting smiles_changed; calling _on_structure_edited directly (as done
    # in this test) bypasses that path, so we only verify project state here.

    # Verify undo restores the empty SMILES
    window._undo_stack.undo()
    assert window._project.smiles == ""


def test_peak_selection_does_not_change_molecule_widget(qtbot):
    """Clicking a peak should NOT update the molecule_widget SMILES (project-level only)."""
    from core.peak import Peak
    from core.project import Project
    from core.spectrum import Spectrum
    from ui.main_window import MainWindow

    db = _make_mock_db()
    settings = _make_mock_settings()
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)

    wn = np.linspace(400.0, 4000.0, 10)
    spectrum = Spectrum(wavenumbers=wn, intensities=np.linspace(0.0, 1.0, 10), title="T")
    project = Project(name="Test", spectrum=spectrum, smiles="CCO")
    peak = Peak(position=1000.0, intensity=0.5, smiles="c1ccccc1")
    project.peaks.append(peak)
    window._project = project
    # Set molecule widget to the project SMILES as it would be after load
    window._molecule_widget.set_smiles("CCO")

    # Simulate peak selection from table
    window._on_peak_selected(peak)

    # molecule_widget must still show project SMILES, not peak SMILES
    assert window._molecule_widget._current_smiles == "CCO"


def test_load_spectrum_shows_empty_smiles_in_molecule_widget(qtbot, tmp_path):
    """Loading a fresh .spa sets molecule_widget to empty (new project.smiles='')."""
    import sys
    import types
    from unittest.mock import MagicMock

    from ui.main_window import MainWindow

    spectrum = _make_spectrum()
    db = _make_mock_db()
    settings = _make_mock_settings()
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)
    # Pre-set some SMILES to verify it gets cleared
    window._molecule_widget.set_smiles("c1ccccc1")

    spa_file = tmp_path / "fresh.spa"
    spa_file.write_bytes(b"\x00" * 16)

    fake_fr_mod = types.ModuleType("file_io.format_registry")
    mock_registry_cls = MagicMock()
    mock_registry_cls.return_value.read.return_value = spectrum
    fake_fr_mod.FormatRegistry = mock_registry_cls

    original = sys.modules.get("file_io.format_registry")
    sys.modules["file_io.format_registry"] = fake_fr_mod
    try:
        window._load_spectrum(str(spa_file))
    finally:
        if original is None:
            sys.modules.pop("file_io.format_registry", None)
        else:
            sys.modules["file_io.format_registry"] = original

    assert window._project is not None
    assert window._project.smiles == ""
    assert window._molecule_widget._current_smiles == ""
