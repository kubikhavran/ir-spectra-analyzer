"""Tests for showing a spectrum in a unit other than the one it was loaded in."""

from __future__ import annotations

import numpy as np
import pytest

from core.spectrum import SpectralUnit, Spectrum
from processing.unit_conversion import convert_intensities, convertible_units


def _absorbance_spectrum() -> Spectrum:
    """An ATR-like absorbance curve: baseline near zero, weak bands pointing up."""
    wn = np.linspace(400.0, 4000.0, 800)
    curve = np.full_like(wn, 0.004)
    for centre, height in ((1050.0, 0.12), (1700.0, 0.16), (2925.0, 0.05)):
        curve += height * np.exp(-0.5 * ((wn - centre) / 15.0) ** 2)
    return Spectrum(wavenumbers=wn, intensities=curve, y_unit=SpectralUnit.ABSORBANCE)


# ── The conversion itself ────────────────────────────────────────────────────


def test_absorbance_round_trips_through_transmittance() -> None:
    values = np.array([0.0, 0.1, 0.5, 2.0])
    percent = convert_intensities(values, SpectralUnit.ABSORBANCE, SpectralUnit.TRANSMITTANCE)
    back = convert_intensities(percent, SpectralUnit.TRANSMITTANCE, SpectralUnit.ABSORBANCE)
    assert percent[0] == pytest.approx(100.0)
    assert np.allclose(back, values)


def test_blanked_bands_stay_blanked() -> None:
    """A region OMNIC cut out is missing in either unit; filling it would invent data."""
    values = np.array([0.1, np.nan, 0.3])
    percent = convert_intensities(values, SpectralUnit.ABSORBANCE, SpectralUnit.TRANSMITTANCE)
    assert np.isnan(percent[1])
    assert np.isfinite(percent[[0, 2]]).all()


def test_units_without_a_defined_transform_are_refused() -> None:
    values = np.array([1.0, 2.0])
    assert convert_intensities(values, SpectralUnit.SINGLE_BEAM, SpectralUnit.ABSORBANCE) is None
    assert convertible_units(SpectralUnit.REFLECTANCE) == ()
    assert convertible_units(SpectralUnit.SINGLE_BEAM) == ()


def test_same_unit_is_a_no_op() -> None:
    values = np.array([1.0, 2.0])
    same = convert_intensities(values, SpectralUnit.ABSORBANCE, SpectralUnit.ABSORBANCE)
    assert np.allclose(same, values)


# ── Spectrum keeps the original ──────────────────────────────────────────────


def test_converted_spectrum_leaves_the_original_alone() -> None:
    spectrum = _absorbance_spectrum()
    before = spectrum.intensities.copy()
    percent = spectrum.converted_to(SpectralUnit.TRANSMITTANCE)
    assert percent is not None
    assert percent.y_unit == SpectralUnit.TRANSMITTANCE
    assert percent.is_dip_spectrum  # bands now point down
    assert np.allclose(spectrum.intensities, before)
    assert spectrum.y_unit == SpectralUnit.ABSORBANCE


def test_converting_to_the_native_unit_returns_the_same_object() -> None:
    spectrum = _absorbance_spectrum()
    assert spectrum.converted_to(SpectralUnit.ABSORBANCE) is spectrum


def test_a_mislabeled_file_converts_from_the_scale_it_is_really_on() -> None:
    """display_y_unit is the source, so a bad header does not corrupt the maths."""
    wn = np.linspace(400.0, 4000.0, 400)
    percent = np.full_like(wn, 99.0)
    percent[100:120] = 60.0
    mislabeled = Spectrum(wavenumbers=wn, intensities=percent, y_unit=SpectralUnit.ABSORBANCE)
    assert mislabeled.display_y_unit == SpectralUnit.TRANSMITTANCE
    converted = mislabeled.converted_to(SpectralUnit.ABSORBANCE)
    assert converted is not None
    # -log10(0.60) = 0.22, not -log10(60/100 of an absorbance value)
    assert float(np.nanmax(converted.intensities)) == pytest.approx(0.2218, abs=1e-3)


# ── The viewer ───────────────────────────────────────────────────────────────


def test_viewer_redraws_in_the_chosen_unit(qtbot) -> None:
    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_spectrum(_absorbance_spectrum())
    assert widget.display_unit() is None
    assert not widget.is_converted_view()

    widget.set_display_unit(SpectralUnit.TRANSMITTANCE)
    assert widget.is_converted_view()
    assert widget._spectrum is not None
    assert widget._spectrum.y_unit == SpectralUnit.TRANSMITTANCE
    # The loaded spectrum is untouched underneath.
    assert widget._source_spectrum is not None
    assert widget._source_spectrum.y_unit == SpectralUnit.ABSORBANCE

    widget.set_display_unit(None)
    assert not widget.is_converted_view()


def test_overlays_follow_the_displayed_unit(qtbot) -> None:
    """A %T reference over an absorbance query is what made the two unreadable."""
    from ui.spectrum_widget import SpectrumWidget

    wn = np.linspace(400.0, 4000.0, 800)
    reference = Spectrum(
        wavenumbers=wn,
        intensities=np.full_like(wn, 98.0),
        y_unit=SpectralUnit.TRANSMITTANCE,
    )
    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_spectrum(_absorbance_spectrum())
    widget.set_overlay_spectra([reference])

    drawn = widget._overlay_in_display_unit(reference)
    assert drawn.y_unit == SpectralUnit.ABSORBANCE
    assert float(np.nanmax(drawn.intensities)) < 1.0  # on the query's scale now

    widget.set_display_unit(SpectralUnit.TRANSMITTANCE)
    assert widget._overlay_in_display_unit(reference).y_unit == SpectralUnit.TRANSMITTANCE


def test_label_dragging_is_off_while_the_view_is_converted(qtbot) -> None:
    """Offsets are stored in the file's own units, so they must not be written here."""
    from core.peak import Peak
    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_spectrum(_absorbance_spectrum())
    widget.set_peaks([Peak(position=1700.0, intensity=0.16)])
    assert widget.compute_auto_label_placements() is not None

    widget.set_display_unit(SpectralUnit.TRANSMITTANCE)
    assert widget.compute_auto_label_placements() == []


def test_selector_stays_hidden_for_units_with_no_counterpart(qtbot) -> None:
    from ui.spectrum_widget import SpectrumWidget

    wn = np.linspace(400.0, 4000.0, 200)
    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_spectrum(
        Spectrum(
            wavenumbers=wn,
            intensities=np.full_like(wn, 0.5),
            y_unit=SpectralUnit.SINGLE_BEAM,
        )
    )
    assert not widget._unit_combo.isVisible()
    assert widget.display_unit() is None
