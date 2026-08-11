"""Clicking a vibration outlines the window it can occupy in the spectrum.

The outline is a reading aid: it must appear for custom entries as well as
built-in ones, must not depend on a peak being selected, and must be possible to
switch off when it gets in the way.
"""

import numpy as np
import pytest

from core.spectrum import SpectralUnit, Spectrum
from core.vibration_presets import VibrationPreset
from storage.database import Database
from storage.settings import Settings
from ui.main_window import MainWindow
from ui.spectrum_widget import SpectrumWidget


@pytest.fixture
def window(qtbot, tmp_path):
    db = Database(tmp_path / "projects.db")
    db.initialize()
    main_window = MainWindow(db=db, settings=Settings(tmp_path / "settings.json"))
    qtbot.addWidget(main_window)
    yield main_window
    db.close()


def _preset(name="ν(C=O) test", low=1650.0, high=1750.0) -> VibrationPreset:
    return VibrationPreset(
        name=name,
        typical_range_min=low,
        typical_range_max=high,
        category="test",
        description="",
        color="#4A90D9",
    )


def test_widget_outlines_the_requested_range(qtbot):
    widget = SpectrumWidget()
    qtbot.addWidget(widget)

    widget.set_vibration_range(1650.0, 1750.0)

    assert widget.vibration_range() == (1650.0, 1750.0)


def test_widget_normalises_a_reversed_range(qtbot):
    widget = SpectrumWidget()
    qtbot.addWidget(widget)

    widget.set_vibration_range(1750.0, 1650.0)

    assert widget.vibration_range() == (1650.0, 1750.0)


def test_hiding_the_outline_keeps_the_range_for_later(qtbot):
    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_vibration_range(1650.0, 1750.0)

    widget.set_vibration_range_visible(False)

    assert widget.vibration_range_visible() is False
    assert widget.vibration_range() == (1650.0, 1750.0), "turning it off must not forget it"

    widget.set_vibration_range_visible(True)
    assert widget.vibration_range_visible() is True


def test_clearing_removes_the_outline(qtbot):
    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_vibration_range(1650.0, 1750.0)

    widget.clear_vibration_range()

    assert widget.vibration_range() is None


def test_the_outline_does_not_disturb_functional_group_regions(qtbot):
    """The two overlays are independent layers."""
    widget = SpectrumWidget()
    qtbot.addWidget(widget)

    widget.set_diagnostic_regions([])
    widget.set_vibration_range(1650.0, 1750.0)
    widget.set_vibration_range_visible(False)

    assert widget.diagnostic_regions_visible() is True


def test_clicking_a_vibration_outlines_its_range(window):
    window._on_preset_range_requested(_preset(low=1650.0, high=1750.0))

    assert window._spectrum_widget.vibration_range() == (1650.0, 1750.0)


def test_a_custom_vibration_is_outlined_the_same_way(window):
    """Custom entries carry the same typical range, so nothing special is needed."""
    window._on_preset_range_requested(_preset(name="my own band", low=905.0, high=930.0))

    assert window._spectrum_widget.vibration_range() == (905.0, 930.0)


def test_outlining_does_not_require_a_selected_peak(window):
    """Looking up where a vibration appears is independent of assignment."""
    assert window._peak_table.selected_peak() is None

    window._on_preset_range_requested(_preset())

    assert window._spectrum_widget.vibration_range() is not None


def test_a_preset_without_a_usable_range_clears_the_outline(window):
    window._on_preset_range_requested(_preset(low=1650.0, high=1750.0))

    window._on_preset_range_requested(_preset(low=1200.0, high=1200.0))

    assert window._spectrum_widget.vibration_range() is None


def test_panel_checkbox_drives_the_outline_visibility(window):
    window._on_preset_range_requested(_preset())

    window._vibration_panel._show_range_checkbox.setChecked(False)
    assert window._spectrum_widget.vibration_range_visible() is False

    window._vibration_panel._show_range_checkbox.setChecked(True)
    assert window._spectrum_widget.vibration_range_visible() is True


def test_clicking_the_list_emits_the_range_request(qtbot, window):
    """The panel reports the click even when there is no peak to assign to."""
    panel = window._vibration_panel
    panel.set_presets([_preset(name="ν(OH) test", low=3200.0, high=3600.0)])
    received: list = []
    panel.preset_range_requested.connect(received.append)

    item = panel._list.item(0)
    panel._list.itemClicked.emit(item)

    assert len(received) == 1
    assert received[0].typical_range_min == 3200.0


def test_range_survives_switching_to_split_view(qtbot, window):
    """Split view rebuilds the panels; the outline has to be redrawn with them."""
    wavenumbers = np.linspace(400.0, 4000.0, 401)
    spectrum = Spectrum(
        wavenumbers=wavenumbers,
        intensities=np.full_like(wavenumbers, 99.0),
        y_unit=SpectralUnit.TRANSMITTANCE,
    )
    window._spectrum_widget.set_spectrum(spectrum)
    window._on_preset_range_requested(_preset(low=1650.0, high=1750.0))

    window._spectrum_widget._on_split_toggled(True)

    assert window._spectrum_widget.vibration_range() == (1650.0, 1750.0)
