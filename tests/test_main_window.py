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
    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    qtbot.addWidget(widget)

    spectrum = _make_spectrum()
    widget.set_spectrum(spectrum)

    peaks = [Peak(position=1000.0, intensity=0.5)]
    widget.set_peaks(peaks)  # must not raise

    assert len(widget._peaks) == 1


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
    """Calling _export_pdf without explicit options should keep the default report path."""
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

    builder.build.assert_called_once()
    builder.build_with_options.assert_not_called()


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
