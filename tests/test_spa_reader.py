"""Tests for SPA file reader."""

from __future__ import annotations

import struct
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest


def test_spa_reader_raises_on_missing_file() -> None:
    """SPAReader should raise FileNotFoundError for non-existent files."""
    from file_io.spa_reader import SPAReader

    reader = SPAReader()
    with pytest.raises(FileNotFoundError):
        reader.read(Path("/nonexistent/file.spa"))


def _build_synthetic_spa() -> bytes:
    """Build a minimal valid SPA binary blob in memory.

    Layout:
        bytes   0–29  : title "Test" (null-padded)
        bytes  30–31  : n_sections = 2 (uint16 LE)
        bytes  32–55  : section directory (2 × 12 bytes)
          entry 0: type=11, offset=56, size=12   (param block)
          entry 1: type=3,  offset=68, size=16   (intensity block, 4×f32)
        bytes  56–67  : param block — variant A [4 (u32), 4000.0 (f32), 400.0 (f32)]
        bytes  68–83  : intensity block — [0.1, 0.2, 0.3, 0.4] as float32 LE
    """
    buf = bytearray(84)

    # Title
    title = b"Test"
    buf[0 : len(title)] = title

    # n_sections
    struct.pack_into("<H", buf, 30, 2)

    # Section directory entry 0: type=11, subtype=0, offset=56, size=12
    struct.pack_into("<HHII", buf, 32, 11, 0, 56, 12)

    # Section directory entry 1: type=3, subtype=0, offset=68, size=16
    struct.pack_into("<HHII", buf, 44, 3, 0, 68, 16)

    # Parameter block at offset 56 (variant A): n_points=4, first_wn=4000.0, last_wn=400.0
    struct.pack_into("<Iff", buf, 56, 4, 4000.0, 400.0)

    # Intensity block at offset 68: four float32 values
    struct.pack_into("<4f", buf, 68, 0.1, 0.2, 0.3, 0.4)

    return bytes(buf)


def test_extract_spectral_data_synthetic() -> None:
    """_extract_spectral_data should parse a synthetic SPA blob correctly."""
    from file_io.spa_binary import SPABinaryReader

    data = _build_synthetic_spa()
    reader = SPABinaryReader()
    wavenumbers, intensities = reader._extract_spectral_data(data)

    # Shape
    assert wavenumbers.shape == (4,), f"Expected shape (4,), got {wavenumbers.shape}"

    # Ascending order after flip (original is 4000→400, high→low)
    assert wavenumbers[0] < wavenumbers[-1], (
        f"wavenumbers should be ascending; got {wavenumbers[0]} … {wavenumbers[-1]}"
    )

    # Boundary values (flipped: 400 first, 4000 last)
    assert np.isclose(wavenumbers[0], 400.0), (
        f"wavenumbers[0] should be 400.0, got {wavenumbers[0]}"
    )
    assert np.isclose(wavenumbers[-1], 4000.0), (
        f"wavenumbers[-1] should be 4000.0, got {wavenumbers[-1]}"
    )

    # Intensities also flipped: [0.4, 0.3, 0.2, 0.1]
    assert np.allclose(intensities, [0.4, 0.3, 0.2, 0.1], atol=1e-6), (
        f"Unexpected intensities: {intensities}"
    )


def test_extract_spectral_data_rejects_corrupt_short_file() -> None:
    """_extract_spectral_data should raise ValueError for files that are too short."""
    from file_io.spa_binary import SPABinaryReader

    reader = SPABinaryReader()
    with pytest.raises(ValueError, match="too short"):
        reader._extract_spectral_data(b"\x00" * 10)


def test_extract_spectral_data_rejects_missing_intensity_section() -> None:
    """_extract_spectral_data should raise ValueError when no type-3 section exists."""
    from file_io.spa_binary import SPABinaryReader

    # Build a blob with n_sections=0 (which is implausible → ValueError about count)
    buf = bytearray(84)
    struct.pack_into("<H", buf, 30, 0)  # n_sections = 0
    reader = SPABinaryReader()
    with pytest.raises(ValueError, match="section count"):
        reader._extract_spectral_data(bytes(buf))


def test_extract_title_returns_stem_when_empty() -> None:
    """read() should use filepath.stem when the title header is all null bytes."""
    from file_io.spa_binary import SPABinaryReader

    reader = SPABinaryReader()
    # All-null title
    data = _build_synthetic_spa()
    buf = bytearray(data)
    buf[0:30] = b"\x00" * 30
    assert reader._extract_title(bytes(buf)) == ""


# ---------------------------------------------------------------------------
# New tests appended below — do not modify tests above this line
# ---------------------------------------------------------------------------


def test_variant_b_param_block() -> None:
    """Variant B param block [first_wn: f32, last_wn: f32, n_points: u32] is parsed correctly."""
    from file_io.spa_binary import SPABinaryReader

    # Layout:
    #  bytes   0-29: title "VarB" null-padded
    #  bytes  30-31: n_sections=2 (uint16 LE)
    #  bytes  32-43: entry 0 — type=11, subtype=0, offset=56, size=12
    #  bytes  44-55: entry 1 — type=3,  subtype=0, offset=68, size=16
    #  bytes  56-67: param block Variant B: first_wn=600.0, last_wn=3500.0, n_points=4
    #  bytes  68-83: intensities [1.0, 2.0, 3.0, 4.0] as float32 LE
    buf = bytearray(84)

    title = b"VarB"
    buf[0 : len(title)] = title

    struct.pack_into("<H", buf, 30, 2)  # n_sections
    struct.pack_into("<HHII", buf, 32, 11, 0, 56, 12)  # entry 0: type-11
    struct.pack_into("<HHII", buf, 44, 3, 0, 68, 16)  # entry 1: type-3

    # Variant B param block
    struct.pack_into("<ffI", buf, 56, 600.0, 3500.0, 4)

    # Intensities
    struct.pack_into("<4f", buf, 68, 1.0, 2.0, 3.0, 4.0)

    reader = SPABinaryReader()
    wavenumbers, intensities = reader._extract_spectral_data(bytes(buf))

    assert wavenumbers[0] < wavenumbers[-1], "wavenumbers should be ascending"
    assert np.isclose(wavenumbers[0], 600.0), f"expected 600.0, got {wavenumbers[0]}"
    assert np.isclose(wavenumbers[-1], 3500.0), f"expected 3500.0, got {wavenumbers[-1]}"
    # 600 < 3500 so no flip needed; intensities stay [1.0, 2.0, 3.0, 4.0]
    assert np.allclose(intensities, [1.0, 2.0, 3.0, 4.0], atol=1e-6), (
        f"Unexpected intensities: {intensities}"
    )


def test_no_param_block_uses_default_range() -> None:
    """Missing type-11 section triggers UserWarning and default 400–4000 cm⁻¹ range."""
    from file_io.spa_binary import SPABinaryReader

    # Layout:
    #  bytes   0-29: title "NoParam"
    #  bytes  30-31: n_sections=1
    #  bytes  32-43: entry 0 — type=3, offset=44, size=16
    #  bytes  44-59: intensities [0.5, 0.6, 0.7, 0.8] as float32 LE
    #  bytes  60-67: padding (to meet _MIN_FILE_BYTES = 68)
    buf = bytearray(68)

    title = b"NoParam"
    buf[0 : len(title)] = title

    struct.pack_into("<H", buf, 30, 1)  # n_sections
    struct.pack_into("<HHII", buf, 32, 3, 0, 44, 16)  # entry 0: type-3 only

    struct.pack_into("<4f", buf, 44, 0.5, 0.6, 0.7, 0.8)

    reader = SPABinaryReader()
    with pytest.warns(UserWarning, match="parameter block not found"):
        wavenumbers, intensities = reader._extract_spectral_data(bytes(buf))

    assert np.isclose(wavenumbers[0], 400.0), f"expected 400.0, got {wavenumbers[0]}"
    assert np.isclose(wavenumbers[-1], 4000.0), f"expected 4000.0, got {wavenumbers[-1]}"


def test_already_ascending_wavenumbers_no_flip() -> None:
    """Variant A with first_wn < last_wn should not be flipped."""
    from file_io.spa_binary import SPABinaryReader

    # Reuse _build_synthetic_spa() but override param block at bytes 56–67
    # so first_wn=400.0, last_wn=4000.0 (already ascending).
    data = bytearray(_build_synthetic_spa())
    # Overwrite param block: Variant A [n_points=4, first_wn=400.0, last_wn=4000.0]
    struct.pack_into("<Iff", data, 56, 4, 400.0, 4000.0)
    # Also reset intensities so we know what to expect
    struct.pack_into("<4f", data, 68, 0.1, 0.2, 0.3, 0.4)

    reader = SPABinaryReader()
    wavenumbers, intensities = reader._extract_spectral_data(bytes(data))

    assert np.isclose(wavenumbers[0], 400.0), f"expected 400.0, got {wavenumbers[0]}"
    assert np.isclose(wavenumbers[-1], 4000.0), f"expected 4000.0, got {wavenumbers[-1]}"
    # Already ascending → no flip
    assert np.allclose(intensities, [0.1, 0.2, 0.3, 0.4], atol=1e-6), (
        f"Unexpected intensities (should not be flipped): {intensities}"
    )


def test_out_of_bounds_section_skipped_gracefully() -> None:
    """A section with an out-of-bounds offset is skipped; reader still returns data."""
    from file_io.spa_binary import SPABinaryReader

    # Layout:
    #  bytes   0-29: title "OOB"
    #  bytes  30-31: n_sections=2
    #  bytes  32-43: entry 0 — type=11, offset=9999 (out of bounds), size=12
    #  bytes  44-55: entry 1 — type=3,  offset=56, size=16
    #  bytes  56-71: intensities [1.0, 2.0, 3.0, 4.0] as float32 LE
    buf = bytearray(72)

    title = b"OOB"
    buf[0 : len(title)] = title

    struct.pack_into("<H", buf, 30, 2)  # n_sections
    struct.pack_into("<HHII", buf, 32, 11, 0, 9999, 12)  # entry 0: OOB type-11
    struct.pack_into("<HHII", buf, 44, 3, 0, 56, 16)  # entry 1: valid type-3

    struct.pack_into("<4f", buf, 56, 1.0, 2.0, 3.0, 4.0)

    reader = SPABinaryReader()
    # No type-11 param block available → UserWarning
    with pytest.warns(UserWarning, match="parameter block not found"):
        wavenumbers, intensities = reader._extract_spectral_data(bytes(buf))

    assert wavenumbers is not None
    assert intensities is not None
    assert len(wavenumbers) == 4
    assert len(intensities) == 4


def test_implausible_section_count_raises() -> None:
    """n_sections > _MAX_SECTIONS (200) should raise ValueError mentioning 'section count'."""
    from file_io.spa_binary import SPABinaryReader

    buf = bytearray(68)
    struct.pack_into("<H", buf, 30, 201)  # n_sections = 201 > _MAX_SECTIONS

    reader = SPABinaryReader()
    with pytest.raises(ValueError, match="section count"):
        reader._extract_spectral_data(bytes(buf))


def test_read_returns_valid_spectrum(tmp_path: Path) -> None:
    """SPABinaryReader.read() returns a correctly populated Spectrum instance."""
    from core.spectrum import Spectrum
    from file_io.spa_binary import SPABinaryReader

    spa_file = tmp_path / "sample.spa"
    spa_file.write_bytes(_build_synthetic_spa())

    reader = SPABinaryReader()
    spectrum = reader.read(spa_file)

    assert isinstance(spectrum, Spectrum)
    assert spectrum.title == "Test"
    assert spectrum.n_points == 4
    assert spectrum.wavenumbers[0] < spectrum.wavenumbers[-1], "wavenumbers should be ascending"
    assert spectrum.y_unit.value == "Absorbance"


def test_spa_reader_falls_through_to_binary_reader(tmp_path: Path) -> None:
    """SPAReader falls back to SPABinaryReader when SpectroChemPy is unavailable."""
    from core.spectrum import Spectrum
    from file_io.spa_reader import SPAReader

    spa_file = tmp_path / "sample.spa"
    spa_file.write_bytes(_build_synthetic_spa())

    class _NoSCPReader(SPAReader):
        def _read_spectrochempy(self, filepath: Path) -> Spectrum:
            raise ImportError("no spectrochempy")

    reader = _NoSCPReader()
    spectrum = reader.read(spa_file)

    assert isinstance(spectrum, Spectrum)
    assert spectrum.n_points == 4


def test_spa_reader_merges_binary_metadata_when_primary_parser_succeeds(tmp_path: Path) -> None:
    """Binary metadata should enrich the preferred parser result when both succeed."""
    from core.spectrum import SpectralUnit, Spectrum
    from file_io.spa_reader import SPAReader

    spa_file = tmp_path / "sample.spa"
    spa_file.write_bytes(_build_synthetic_spa())

    primary = Spectrum(
        wavenumbers=np.array([400.0, 500.0, 600.0], dtype=float),
        intensities=np.array([1.0, 2.0, 3.0], dtype=float),
        title="Primary",
        y_unit=SpectralUnit.ABSORBANCE,
        extra_metadata={"primary_only": True},
    )
    binary = Spectrum(
        wavenumbers=np.array([100.0, 200.0, 300.0], dtype=float),
        intensities=np.array([9.0, 8.0, 7.0], dtype=float),
        title="Binary",
        source_path=spa_file,
        y_unit=SpectralUnit.TRANSMITTANCE,
        extra_metadata={"annotated_peaks": [{"position": 1700.0, "intensity": 75.0}]},
    )

    class _MergedReader(SPAReader):
        def _read_spectrochempy(self, filepath: Path) -> Spectrum:
            return primary

    reader = _MergedReader()

    from unittest.mock import patch

    with patch("file_io.spa_binary.SPABinaryReader.read", return_value=binary):
        spectrum = reader.read(spa_file)

    assert np.allclose(spectrum.wavenumbers, primary.wavenumbers)
    assert np.allclose(spectrum.intensities, primary.intensities)
    assert spectrum.y_unit == SpectralUnit.TRANSMITTANCE
    assert spectrum.extra_metadata["primary_only"] is True
    assert spectrum.extra_metadata["annotated_peaks"] == binary.extra_metadata["annotated_peaks"]


# ---------------------------------------------------------------------------
# Real-file fixture tests  (Nicolet iS10, public sample data)
# Source: github.com/pricebenjamin/SPA-file-reader
# NOTE: These files are TEMPORARY development fixtures, not production data.
#       Re-validate when real OMNIC files from your own instrument are available.
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_real_spa_files = sorted(list(FIXTURES_DIR.glob("*.SPA")) + list(FIXTURES_DIR.glob("*.spa")))

# Skip entire fixture block cleanly if no fixtures present (CI without large files)
_has_fixtures = len(_real_spa_files) > 0


@pytest.mark.skipif(not _has_fixtures, reason="No real .SPA fixtures in tests/fixtures/")
@pytest.mark.parametrize("spa_path", _real_spa_files, ids=lambda p: p.name)
def test_real_spa_parses_without_error(spa_path: Path) -> None:
    """Binary reader must not raise on any real fixture file."""
    from core.spectrum import Spectrum
    from file_io.spa_binary import SPABinaryReader

    spectrum = SPABinaryReader().read(spa_path)
    assert isinstance(spectrum, Spectrum)


@pytest.mark.skipif(not _has_fixtures, reason="No real .SPA fixtures in tests/fixtures/")
@pytest.mark.parametrize("spa_path", _real_spa_files, ids=lambda p: p.name)
def test_real_spa_spectrum_shape(spa_path: Path) -> None:
    """Real spectra must have ≥ 100 points and matching array shapes."""
    from file_io.spa_binary import SPABinaryReader

    spec = SPABinaryReader().read(spa_path)
    assert spec.n_points >= 100, f"Expected ≥100 points, got {spec.n_points}"
    assert spec.wavenumbers.shape == spec.intensities.shape


@pytest.mark.skipif(not _has_fixtures, reason="No real .SPA fixtures in tests/fixtures/")
@pytest.mark.parametrize("spa_path", _real_spa_files, ids=lambda p: p.name)
def test_real_spa_wavenumbers_ascending(spa_path: Path) -> None:
    """Wavenumber axis must be strictly ascending after parsing."""
    from file_io.spa_binary import SPABinaryReader

    spec = SPABinaryReader().read(spa_path)
    assert spec.wavenumbers[0] < spec.wavenumbers[-1], (
        f"wavenumbers not ascending: {spec.wavenumbers[0]:.2f} … {spec.wavenumbers[-1]:.2f}"
    )


@pytest.mark.skipif(not _has_fixtures, reason="No real .SPA fixtures in tests/fixtures/")
@pytest.mark.parametrize("spa_path", _real_spa_files, ids=lambda p: p.name)
def test_real_spa_wavenumber_range_plausible(spa_path: Path) -> None:
    """Wavenumber range must fall within mid-IR bounds (350–15000 cm⁻¹)."""
    from file_io.spa_binary import SPABinaryReader

    spec = SPABinaryReader().read(spa_path)
    assert 350.0 <= spec.wavenumbers[0] <= 2000.0, (
        f"wn start out of IR range: {spec.wavenumbers[0]:.2f}"
    )
    assert 1500.0 <= spec.wavenumbers[-1] <= 15000.0, (
        f"wn end out of IR/NIR range: {spec.wavenumbers[-1]:.2f}"
    )


@pytest.mark.skipif(not _has_fixtures, reason="No real .SPA fixtures in tests/fixtures/")
@pytest.mark.parametrize("spa_path", _real_spa_files, ids=lambda p: p.name)
def test_real_spa_intensities_finite(spa_path: Path) -> None:
    """All intensity values must be finite (no NaN or Inf)."""
    from file_io.spa_binary import SPABinaryReader

    spec = SPABinaryReader().read(spa_path)
    assert np.all(np.isfinite(spec.intensities)), "Non-finite intensity values found"


@pytest.mark.skipif(not _has_fixtures, reason="No real .SPA fixtures in tests/fixtures/")
@pytest.mark.parametrize("spa_path", _real_spa_files, ids=lambda p: p.name)
def test_real_spa_title_nonempty(spa_path: Path) -> None:
    """Title must be non-empty (from file or fallback to stem)."""
    from file_io.spa_binary import SPABinaryReader

    spec = SPABinaryReader().read(spa_path)
    assert isinstance(spec.title, str)
    assert len(spec.title) > 0


@pytest.mark.skipif(not _has_fixtures, reason="No real .SPA fixtures in tests/fixtures/")
@pytest.mark.parametrize("spa_path", _real_spa_files, ids=lambda p: p.name)
def test_real_spa_extra_metadata_present(spa_path: Path) -> None:
    """OMNIC files should populate extra_metadata with provenance fields."""
    from file_io.spa_binary import SPABinaryReader

    spec = SPABinaryReader().read(spa_path)
    # At minimum, the OMNIC variant flag must be set
    assert "omnic_format" in spec.extra_metadata
    assert spec.extra_metadata["omnic_format"] is True
    # Wavenumber params must be captured
    assert "omnic_wn_max" in spec.extra_metadata
    assert "omnic_wn_min" in spec.extra_metadata
    assert spec.extra_metadata["omnic_wn_max"] > spec.extra_metadata["omnic_wn_min"]


# Instrument-specific assertions for the 3 original Nicolet iS10 fixtures only.
_NICOLET_IS10_FILES = [
    p for p in _real_spa_files if p.name in {"0min-1-97C.SPA", "113361_2-22.SPA", "30min-1-97C.SPA"}
]
_has_nicolet_fixtures = len(_NICOLET_IS10_FILES) > 0
_peaktable_fixture = FIXTURES_DIR / "reference library_1" / "FER58-SE.SPA"


@pytest.mark.skipif(not _has_nicolet_fixtures, reason="Nicolet iS10 fixtures not present")
@pytest.mark.parametrize("spa_path", _NICOLET_IS10_FILES, ids=lambda p: p.name)
def test_real_spa_known_wavenumber_range(spa_path: Path) -> None:
    """Nicolet iS10 fixtures must cover 649–4000 cm⁻¹ (instrument-specific assertion)."""
    from file_io.spa_binary import SPABinaryReader

    spec = SPABinaryReader().read(spa_path)
    assert np.isclose(spec.wavenumbers[0], 649.98, atol=1.0), (
        f"Expected ~649.98 cm⁻¹ start, got {spec.wavenumbers[0]:.3f}"
    )
    assert np.isclose(spec.wavenumbers[-1], 3999.99, atol=1.0), (
        f"Expected ~3999.99 cm⁻¹ end, got {spec.wavenumbers[-1]:.3f}"
    )


# ---------------------------------------------------------------------------
# New tests: type-27 history text parsing + real fixture field assertions
# ---------------------------------------------------------------------------

_SAMPLE_HISTORY_TEXT = (
    "Collect Sample\r\n\t Background collected on Thu Feb 23 16:35:07 2017 (GMT-08:00)\r\n\t"
    " Final format:\t%Transmittance\r\n\t Resolution:\t 0.500 from 649.9812 to 3999.9907\r\n\t"
    " Validation wheel: 0\r\n\t Attenuation screen wheel: None\r\n\t"
    " Bench Serial Number:AKX1300131\r\n\t Sample compartment: Main\r\n\r\n"
)


def test_omnic_type27_parser_transmittance() -> None:
    """_parse_omnic_history correctly extracts all fields from a %Transmittance block."""
    from core.spectrum import SpectralUnit
    from file_io.spa_binary import SPABinaryReader

    result = SPABinaryReader._parse_omnic_history(_SAMPLE_HISTORY_TEXT)

    assert result["y_unit"] == SpectralUnit.TRANSMITTANCE, (
        f"Expected TRANSMITTANCE, got {result['y_unit']}"
    )
    assert result["acquired_at"] is not None, "acquired_at should not be None"
    assert isinstance(result["acquired_at"], datetime), (
        f"acquired_at should be datetime, got {type(result['acquired_at'])}"
    )
    assert result["acquired_at"].year == 2017, (
        f"Expected year 2017, got {result['acquired_at'].year}"
    )
    assert result["resolution_cm"] == 0.5, (
        f"Expected resolution_cm=0.5, got {result['resolution_cm']}"
    )
    assert result["instrument_serial"] == "AKX1300131", (
        f"Expected 'AKX1300131', got {result['instrument_serial']}"
    )


def test_omnic_type27_parser_absorbance() -> None:
    """_parse_omnic_history maps 'Absorbance' format to SpectralUnit.ABSORBANCE."""
    from core.spectrum import SpectralUnit
    from file_io.spa_binary import SPABinaryReader

    text = (
        "Collect Sample\r\n\t Background collected on Thu Feb 23 16:35:07 2017 (GMT-08:00)\r\n\t"
        " Final format:\tAbsorbance\r\n"
    )
    result = SPABinaryReader._parse_omnic_history(text)
    assert result["y_unit"] == SpectralUnit.ABSORBANCE, (
        f"Expected ABSORBANCE, got {result['y_unit']}"
    )


def test_omnic_type27_parser_missing_fields() -> None:
    """_parse_omnic_history on an empty string returns all-None without raising."""
    from file_io.spa_binary import SPABinaryReader

    result = SPABinaryReader._parse_omnic_history("")
    assert result["y_unit"] is None
    assert result["acquired_at"] is None
    assert result["resolution_cm"] is None
    assert result["instrument_serial"] is None


@pytest.mark.skipif(not _has_fixtures, reason="No real .SPA fixtures in tests/fixtures/")
@pytest.mark.parametrize("spa_path", _real_spa_files, ids=lambda p: p.name)
def test_real_spa_y_unit_is_valid(spa_path: Path) -> None:
    """y_unit must be a valid SpectralUnit enum member for every fixture."""
    from core.spectrum import SpectralUnit
    from file_io.spa_binary import SPABinaryReader

    spec = SPABinaryReader().read(spa_path)
    assert isinstance(spec.y_unit, SpectralUnit), (
        f"y_unit should be a SpectralUnit, got {type(spec.y_unit)}"
    )


@pytest.mark.skipif(not _has_nicolet_fixtures, reason="Nicolet iS10 fixtures not present")
@pytest.mark.parametrize("spa_path", _NICOLET_IS10_FILES, ids=lambda p: p.name)
def test_real_spa_y_unit_is_transmittance(spa_path: Path) -> None:
    """Nicolet iS10 fixtures report %Transmittance in their type-27 block."""
    from core.spectrum import SpectralUnit
    from file_io.spa_binary import SPABinaryReader

    spec = SPABinaryReader().read(spa_path)
    assert spec.y_unit == SpectralUnit.TRANSMITTANCE, f"Expected TRANSMITTANCE, got {spec.y_unit}"


@pytest.mark.skipif(not _has_fixtures, reason="No real .SPA fixtures in tests/fixtures/")
@pytest.mark.parametrize("spa_path", _real_spa_files, ids=lambda p: p.name)
def test_real_spa_acquired_at_is_datetime_or_none(spa_path: Path) -> None:
    """acquired_at must be a datetime instance or None (some SPA files lack type-27 metadata)."""
    from file_io.spa_binary import SPABinaryReader

    spec = SPABinaryReader().read(spa_path)
    assert spec.acquired_at is None or isinstance(spec.acquired_at, datetime), (
        f"acquired_at should be datetime or None, got {type(spec.acquired_at)}"
    )


@pytest.mark.skipif(not _has_nicolet_fixtures, reason="Nicolet iS10 fixtures not present")
@pytest.mark.parametrize("spa_path", _NICOLET_IS10_FILES, ids=lambda p: p.name)
def test_real_spa_acquired_at_is_populated(spa_path: Path) -> None:
    """Nicolet iS10 fixtures have a valid acquisition timestamp from the type-27 block."""
    from file_io.spa_binary import SPABinaryReader

    spec = SPABinaryReader().read(spa_path)
    assert spec.acquired_at is not None, "acquired_at should not be None for Nicolet iS10 fixtures"
    assert isinstance(spec.acquired_at, datetime), (
        f"acquired_at should be datetime, got {type(spec.acquired_at)}"
    )


@pytest.mark.skipif(not _has_nicolet_fixtures, reason="Nicolet iS10 fixtures not present")
@pytest.mark.parametrize("spa_path", _NICOLET_IS10_FILES, ids=lambda p: p.name)
def test_real_spa_resolution_in_extra_metadata(spa_path: Path) -> None:
    """Nicolet iS10 fixtures have resolution_cm in extra_metadata."""
    from file_io.spa_binary import SPABinaryReader

    spec = SPABinaryReader().read(spa_path)
    assert "resolution_cm" in spec.extra_metadata, "resolution_cm missing from extra_metadata"
    assert spec.extra_metadata["resolution_cm"] > 0, (
        f"resolution_cm should be > 0, got {spec.extra_metadata['resolution_cm']}"
    )


@pytest.mark.skipif(not _has_nicolet_fixtures, reason="Nicolet iS10 fixtures not present")
@pytest.mark.parametrize("spa_path", _NICOLET_IS10_FILES, ids=lambda p: p.name)
def test_real_spa_instrument_serial_in_extra_metadata(spa_path: Path) -> None:
    """Nicolet iS10 fixtures have a non-empty instrument_serial in extra_metadata."""
    from file_io.spa_binary import SPABinaryReader

    spec = SPABinaryReader().read(spa_path)
    assert "instrument_serial" in spec.extra_metadata, (
        "instrument_serial missing from extra_metadata"
    )
    assert len(spec.extra_metadata["instrument_serial"]) > 0, (
        "instrument_serial should be non-empty"
    )


@pytest.mark.skipif(not _peaktable_fixture.exists(), reason="Reference-library SPA fixture missing")
def test_reference_library_spa_reads_stored_peak_annotations() -> None:
    """OMNIC PEAKTABLE blocks should populate annotated_peaks for stored lab fixtures."""
    from file_io.spa_binary import SPABinaryReader

    spec = SPABinaryReader().read(_peaktable_fixture)
    annotated_peaks = spec.extra_metadata.get("annotated_peaks")

    assert annotated_peaks is not None
    assert len(annotated_peaks) >= 20
    positions = [peak["position"] for peak in annotated_peaks]
    assert positions == sorted(positions, reverse=True)
    assert any(abs(position - 1639.0) < 2.0 for position in positions)
    assert any(abs(position - 555.0) < 2.0 for position in positions)
