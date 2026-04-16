"""
SPABinaryReader — Low-level binární parser pro .spa soubory.

Zodpovědnost:
- Přímé čtení binárního formátu SPA bez závislosti na SpectroChemPy
- Fallback pro případ, že SpectroChemPy selže
- Extrahuje minimálně: wavenumbers + intensities

Implementace je založena na reverse engineeringu SPA formátu.
Funguje spolehlivě pro data ze spektrometrů Thermo Nicolet/Nexus.

## SPA binary format — two variants handled

### Variant 1: OMNIC real-file format (Thermo Nicolet iS10 and similar)
- Bytes 0-17: magic "Spectral Data File"
- Bytes 18-19: CR LF
- Bytes 20-29: null padding
- Bytes 30-284: title/comment (255 bytes, null-terminated)
- Bytes 288+: section directory — entries are 16 bytes each:
    [type: u16 LE][data_offset: u32 LE][size: u32 LE][pad: 6 bytes]
    Walk until type==0 (end sentinel) or 30 entries max.
    Entry 0 (type=1) is always a header stub — skip it.
  - type 2: spectral parameters block
      +0  unknown (4 bytes)
      +4  n_points (uint32 LE)
      +8  unknown (8 bytes)
      +16 wn_max (float32 LE)
      +20 wn_min (float32 LE)
  - type 3: float32 intensity array
  - type 27: acquisition history text (latin-1)
- Fallback fixed offsets (if type-2 not found):
    Byte 564: n_points (u32 LE)
    Bytes 576-579: wn_max (f32 LE)
    Bytes 580-583: wn_min (f32 LE)

### Variant 2: Compact synthetic/legacy format
- Bytes 0-29: ASCII title, null-padded
- Bytes 30-31: n_sections (u16 LE) — must be 1–200
- Bytes 32+: 12-byte section directory entries:
    [u16 type][u16 sub][u32 offset][u32 size]
- type 11 = parameter block (wavenumber range)
- type 3  = float32 intensity block

Implemented in v0.1.0: Full SPA block structure navigation.
Updated in v0.1.1: Real OMNIC file support via dual-mode detection.
Updated in v0.1.2: Dynamic 16-byte directory walking; type-27 history parsing.
"""

from __future__ import annotations

import logging
import re
import struct
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np

from core.spectrum import SpectralUnit, Spectrum, XAxisUnit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OMNIC real-file constants (Variant 1)
# ---------------------------------------------------------------------------
_OMNIC_MAGIC = b"Spectral Data File"  # bytes 0-17
_OMNIC_TITLE_OFFSET = 30  # bytes 30-284: 255-byte comment/title
_OMNIC_TITLE_LENGTH = 255
_OMNIC_DIR_START = 288  # byte offset of first directory entry
_OMNIC_DIR_ENTRY_SIZE = 16  # each entry: u16 type + u32 offset + u32 size + 6 pad
_OMNIC_DIR_MAX_ENTRIES = 30  # walk at most this many entries
_OMNIC_DIR_TYPE_PARAMS = 2  # spectral parameters block
_OMNIC_DIR_TYPE_INTENSITIES = 3  # float32 intensity data
_OMNIC_DIR_TYPE_COMMENT = 4  # OMNIC user comment/notes (e.g. "CHCl3, film", "KBr, 1cm")
_OMNIC_DIR_TYPE_HISTORY = 27  # acquisition history text
_OMNIC_DIR_TYPE_CUSTOM_INFO = 146  # OMNIC Custom Info fields (client name, order ID, etc.)
_OMNIC_DIR_TYPE_NAMED_BLOCK = 130  # named metadata/report blocks (e.g. PEAKTABLE)
# Type-146 Custom Info block: 64-byte null-padded string fields
_OMNIC_CUSTOM_INFO_FIELD_SIZE = 64  # each field occupies 64 bytes
# Fallback fixed offsets (used when type-2 block is absent)
_OMNIC_N_POINTS_OFFSET = 564  # u32 LE: number of spectral points
_OMNIC_WN_MAX_OFFSET = 576  # f32 LE: wavenumber maximum (cm⁻¹)
_OMNIC_WN_MIN_OFFSET = 580  # f32 LE: wavenumber minimum (cm⁻¹)
_OMNIC_DIR_SCAN_END = 640  # legacy scan limit (kept for reference)

# ---------------------------------------------------------------------------
# Compact/legacy format constants (Variant 2 — used in synthetic test blobs)
# ---------------------------------------------------------------------------
_TITLE_LENGTH = 30  # bytes 0–29: ASCII title, null-padded
_N_SECTIONS_OFFSET = 30  # bytes 30–31: uint16 LE, number of sections
_SECTION_DIR_OFFSET = 32  # byte 32: start of section directory
_SECTION_ENTRY_SIZE = 12  # each directory entry is 12 bytes

# Section entry field offsets (within a 12-byte entry)
_ENTRY_TYPE_OFFSET = 0  # uint16 LE: section type
_ENTRY_DATA_OFFSET = 4  # uint32 LE: byte offset of data block from file start
_ENTRY_SIZE_OFFSET = 8  # uint32 LE: size in bytes of data block

# Known section type codes (compact format)
_SECTION_PARAMS = 11  # 0x000B — spectral parameters (wavenumber range)
_SECTION_INTENSITIES = 3  # 0x0003 — float32 intensity array

# ---------------------------------------------------------------------------
# Shared sanity limits
# ---------------------------------------------------------------------------
_MAX_SECTIONS = 200  # reject obviously corrupt section counts (compact format)
_MIN_FILE_BYTES = 68  # title(30) + n_sections(2) + 2 entries(24) + min blocks(12)
_WN_MIN = 200.0  # minimum plausible wavenumber (cm⁻¹)
_WN_MAX = 20_000.0  # maximum plausible wavenumber (cm⁻¹)


class SPABinaryReader:
    """Minimal SPA binary reader as SpectroChemPy fallback.

    Detects whether the file is a real OMNIC format or a compact/synthetic
    format and dispatches to the appropriate parser.
    """

    def read(self, filepath: Path) -> Spectrum:
        """Read spectral data directly from SPA binary format.

        Args:
            filepath: Path to .spa file.

        Returns:
            Spectrum with wavenumbers and intensities.

        Raises:
            ValueError: If the file is corrupt or missing required sections.
        """
        data = filepath.read_bytes()
        wavenumbers, intensities, extra = self._extract_spectral_data_with_meta(data)

        title = self._extract_title(data) or filepath.stem
        y_unit = extra.pop("_parsed_y_unit", SpectralUnit.ABSORBANCE)
        acquired_at = extra.pop("_parsed_acquired_at", None)

        return Spectrum(
            wavenumbers=wavenumbers,
            intensities=intensities,
            title=title,
            source_path=filepath,
            y_unit=y_unit,
            acquired_at=acquired_at,
            x_unit=XAxisUnit.WAVENUMBER,
            extra_metadata=extra,
        )

    # ------------------------------------------------------------------
    # Public extraction entry point (for tests that call _extract_spectral_data)
    # ------------------------------------------------------------------

    def _extract_spectral_data(self, data: bytes) -> tuple[np.ndarray, np.ndarray]:
        """Extract wavenumber and intensity arrays from raw SPA bytes.

        Public surface used by tests.  Delegates to the appropriate variant.

        Returns:
            Tuple of (wavenumbers, intensities) as float64 arrays,
            both sorted in ascending wavenumber order.
        """
        wns, ints, _extra = self._extract_spectral_data_with_meta(data)
        return wns, ints

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _extract_spectral_data_with_meta(self, data: bytes) -> tuple[np.ndarray, np.ndarray, dict]:
        """Detect file variant and dispatch to the appropriate parser.

        Returns:
            (wavenumbers, intensities, extra_metadata_dict)
        """
        if data[: len(_OMNIC_MAGIC)] == _OMNIC_MAGIC:
            return self._parse_omnic_format(data)
        return self._parse_compact_format(data)

    # ------------------------------------------------------------------
    # OMNIC real-file parser (Variant 1)
    # ------------------------------------------------------------------

    def _parse_omnic_format(self, data: bytes) -> tuple[np.ndarray, np.ndarray, dict]:
        """Parse the OMNIC real-file SPA format (Thermo Nicolet instruments).

        Walks the 16-byte section directory starting at byte 288:
            [type: u16 LE][data_offset: u32 LE][size: u32 LE][pad: 6 bytes]

        Collects:
        - type-2 block: spectral parameters (n_points, wn_max, wn_min)
        - type-3 block: float32 intensity array
        - type-27 block: acquisition history text

        Falls back to fixed offsets (564/576/580) for n_points/wn_max/wn_min
        if the type-2 block is absent.

        Raises:
            ValueError: If required data cannot be found or is out of bounds.
        """
        # --- Walk section directory ---
        params_offset: int | None = None
        params_size: int | None = None
        intensity_offset: int | None = None
        intensity_size: int | None = None
        history_offset: int | None = None
        history_size: int | None = None
        comment_offset: int | None = None
        comment_size: int | None = None
        custom_info_offset: int | None = None
        custom_info_size: int | None = None
        named_blocks: list[tuple[int, int]] = []

        pos = _OMNIC_DIR_START
        for entry_idx in range(_OMNIC_DIR_MAX_ENTRIES):
            if pos + _OMNIC_DIR_ENTRY_SIZE > len(data):
                break
            sec_type = struct.unpack_from("<H", data, pos)[0]
            sec_data_offset = struct.unpack_from("<I", data, pos + 2)[0]
            sec_size = struct.unpack_from("<I", data, pos + 6)[0]
            pos += _OMNIC_DIR_ENTRY_SIZE

            if sec_type == 0:
                # End-of-directory sentinel
                break
            if entry_idx == 0:
                # Entry 0 (type=1) is always a header stub with invalid offset/size — skip
                continue

            if sec_type == _OMNIC_DIR_TYPE_PARAMS and params_offset is None:
                params_offset = sec_data_offset
                params_size = sec_size
            elif sec_type == _OMNIC_DIR_TYPE_INTENSITIES and intensity_offset is None:
                intensity_offset = sec_data_offset
                intensity_size = sec_size
            elif sec_type == _OMNIC_DIR_TYPE_COMMENT and comment_offset is None:
                comment_offset = sec_data_offset
                comment_size = sec_size
            elif sec_type == _OMNIC_DIR_TYPE_CUSTOM_INFO and custom_info_offset is None:
                custom_info_offset = sec_data_offset
                custom_info_size = sec_size
            elif sec_type == _OMNIC_DIR_TYPE_HISTORY and history_offset is None:
                history_offset = sec_data_offset
                history_size = sec_size
            elif sec_type == _OMNIC_DIR_TYPE_NAMED_BLOCK and sec_size > 0:
                named_blocks.append((sec_data_offset, sec_size))

        # --- Parse spectral parameters (type-2 block) ---
        # Type-2 layout: +0 unknown(4), +4 n_points(u32), +8 unknown(8),
        #                +16 wn_max(f32), +20 wn_min(f32)
        n_points: int | None = None
        wn_max: float | None = None
        wn_min: float | None = None

        if (
            params_offset is not None
            and params_size is not None
            and params_size >= 24
            and params_offset + params_size <= len(data)
        ):
            n_points = struct.unpack_from("<I", data, params_offset + 4)[0]
            wn_max = struct.unpack_from("<f", data, params_offset + 16)[0]
            wn_min = struct.unpack_from("<f", data, params_offset + 20)[0]
            if n_points == 0 or n_points > 1_000_000:
                logger.warning(
                    "OMNIC SPA type-2 block: implausible n_points=%d; falling back to fixed offset.",
                    n_points,
                )
                n_points = None
            if wn_max is not None and wn_min is not None and not self._wn_plausible(wn_max, wn_min):
                logger.warning(
                    "OMNIC SPA type-2 block: implausible wn range [%.2f, %.2f]; falling back to fixed offset.",
                    wn_max,
                    wn_min,
                )
                wn_max = None
                wn_min = None

        # --- Fallback: fixed offsets ---
        if n_points is None:
            if len(data) < _OMNIC_N_POINTS_OFFSET + 4:
                raise ValueError(
                    f"OMNIC SPA file too short ({len(data)} bytes) to contain n_points "
                    f"at fallback offset {_OMNIC_N_POINTS_OFFSET}."
                )
            (n_points,) = struct.unpack_from("<I", data, _OMNIC_N_POINTS_OFFSET)
            if n_points == 0 or n_points > 1_000_000:
                raise ValueError(
                    f"OMNIC SPA: implausible n_points={n_points} at fallback offset {_OMNIC_N_POINTS_OFFSET}."
                )
            logger.warning("OMNIC SPA: using fallback fixed offset for n_points.")

        if wn_max is None or wn_min is None:
            if len(data) < _OMNIC_WN_MIN_OFFSET + 4:
                raise ValueError(
                    f"OMNIC SPA file too short to contain wavenumber params at fallback offset {_OMNIC_WN_MAX_OFFSET}."
                )
            wn_max = struct.unpack_from("<f", data, _OMNIC_WN_MAX_OFFSET)[0]
            wn_min = struct.unpack_from("<f", data, _OMNIC_WN_MIN_OFFSET)[0]
            logger.warning("OMNIC SPA: using fallback fixed offsets for wn_max/wn_min.")

        if not self._wn_plausible(wn_max, wn_min):
            logger.warning(
                "OMNIC SPA: wavenumber range [%.2f, %.2f] is implausible; "
                "defaulting to 4000–400 cm⁻¹.",
                wn_max,
                wn_min,
            )
            warnings.warn(
                "OMNIC SPA wavenumber range is implausible; defaulting to 4000–400 cm⁻¹.",
                UserWarning,
                stacklevel=4,
            )
            wn_max, wn_min = 4000.0, 400.0

        # --- Locate intensity data ---
        if intensity_offset is None:
            raise ValueError(
                "OMNIC SPA: could not find type-3 (intensity) entry in section directory."
            )

        # If intensity_size is known use it; otherwise fall back to n_points * 4
        if intensity_size is not None and intensity_size > 0:
            n_intensity = intensity_size // 4
            # Prefer n_points from params over size-derived count if they agree
            if n_intensity != n_points:
                logger.warning(
                    "OMNIC SPA: type-3 size implies %d points but n_points=%d; using n_points.",
                    n_intensity,
                    n_points,
                )
        expected_bytes = n_points * 4
        if intensity_offset + expected_bytes > len(data):
            raise ValueError(
                f"OMNIC SPA: intensity block at offset {intensity_offset} with {n_points} points "
                f"({expected_bytes} bytes) extends beyond file end ({len(data)} bytes)."
            )

        # --- Read intensities ---
        intensities = np.frombuffer(
            data, dtype="<f4", count=n_points, offset=intensity_offset
        ).astype(np.float64)

        # --- Build wavenumber axis ---
        # OMNIC convention: wn_max is the first point, wn_min is the last
        wavenumbers = np.linspace(wn_max, wn_min, n_points)

        # --- Ensure ascending order ---
        if wavenumbers[0] > wavenumbers[-1]:
            wavenumbers = wavenumbers[::-1].copy()
            intensities = intensities[::-1].copy()

        # --- Parse type-27 history text ---
        y_unit = SpectralUnit.ABSORBANCE
        acquired_at: datetime | None = None
        extra: dict = {
            "omnic_n_points": int(n_points),
            "omnic_wn_max": float(wn_max),
            "omnic_wn_min": float(wn_min),
            "omnic_data_offset": int(intensity_offset),
            "omnic_format": True,
        }

        if (
            history_offset is not None
            and history_size is not None
            and history_size > 0
            and history_offset + history_size <= len(data)
        ):
            hist_bytes = data[history_offset : history_offset + history_size]
            hist_text = hist_bytes.decode("latin-1", errors="replace")
            parsed = self._parse_omnic_history(hist_text)
            y_unit = parsed.get("y_unit", SpectralUnit.ABSORBANCE) or SpectralUnit.ABSORBANCE
            acquired_at = parsed.get("acquired_at")
            if "resolution_cm" in parsed and parsed["resolution_cm"] is not None:
                extra["resolution_cm"] = parsed["resolution_cm"]
            if "instrument_serial" in parsed and parsed["instrument_serial"] is not None:
                extra["instrument_serial"] = parsed["instrument_serial"]
            # Store only a short snippet — the full text can be hundreds of bytes
            extra["omnic_history_snippet"] = hist_text[:512]

        # --- Parse type-4 comment block (OMNIC user comment, e.g. "CHCl3, film") ---
        if (
            comment_offset is not None
            and comment_size is not None
            and comment_size > 0
            and comment_offset + comment_size <= len(data)
        ):
            comment_bytes = data[comment_offset : comment_offset + comment_size]
            comment_text = comment_bytes.decode("latin-1", errors="replace")
            # Multi-line OMNIC comments use embedded NUL bytes as line separators
            comment_text = comment_text.replace("\x00", "\n").strip()
            if comment_text:
                extra["omnic_comment"] = comment_text

        # --- Parse type-146 Custom Info block (client name, order/lab ID) ---
        if (
            custom_info_offset is not None
            and custom_info_size is not None
            and custom_info_size >= _OMNIC_CUSTOM_INFO_FIELD_SIZE
            and custom_info_offset + custom_info_size <= len(data)
        ):
            ci_block = data[custom_info_offset : custom_info_offset + custom_info_size]
            # Field layout: each field is a 64-byte null-padded string
            def _read_ci_field(buf: bytes, field_idx: int) -> str:
                start = field_idx * _OMNIC_CUSTOM_INFO_FIELD_SIZE
                end = start + _OMNIC_CUSTOM_INFO_FIELD_SIZE
                if end > len(buf):
                    return ""
                return buf[start:end].rstrip(b"\x00").decode("latin-1", errors="replace").strip()

            ci_1 = _read_ci_field(ci_block, 0)  # Custom Info 1: lab/order identifier
            ci_2 = _read_ci_field(ci_block, 1)  # Custom Info 2: client name
            if ci_1:
                extra["omnic_custom_info_1"] = ci_1
            if ci_2:
                extra["omnic_custom_info_2"] = ci_2

        annotated_peaks = self._parse_omnic_peak_tables(data, named_blocks)
        if annotated_peaks:
            extra["annotated_peaks"] = annotated_peaks

        extra["_parsed_y_unit"] = y_unit
        extra["_parsed_acquired_at"] = acquired_at

        return wavenumbers, intensities, extra

    def _parse_omnic_peak_tables(
        self, data: bytes, named_blocks: list[tuple[int, int]]
    ) -> list[dict[str, float]]:
        """Extract stored OMNIC peak annotations from named type-130 blocks.

        OMNIC stores "Find Peaks" results inside PEAKTABLE blocks. These may
        exist in both plain-text and RTF variants, so matches are deduplicated
        by `(position, intensity)` while preserving the original report order.
        """
        if not named_blocks:
            return []

        peaks: list[dict[str, float]] = []
        seen: set[tuple[float, float]] = set()
        for offset, size in named_blocks:
            if offset < 0 or size <= 0 or offset + size > len(data):
                continue
            block = data[offset : offset + size]
            if b"PEAKTABLE" not in block:
                continue
            text = block.decode("latin-1", errors="replace")
            for match in re.finditer(
                r"Position:\s*([-+]?\d+(?:\.\d+)?)\s*Intensity:\s*([-+]?\d+(?:\.\d+)?)",
                text,
            ):
                position = float(match.group(1))
                intensity = float(match.group(2))
                key = (round(position, 6), round(intensity, 6))
                if key in seen:
                    continue
                seen.add(key)
                peaks.append({"position": position, "intensity": intensity})

        peaks.sort(key=lambda peak: peak["position"], reverse=True)
        return peaks

    @staticmethod
    def _parse_omnic_history(text: str) -> dict:
        """Parse acquisition metadata from an OMNIC type-27 history text block.

        All fields are optional — returns a dict with None values for any field
        that is absent or unparseable.

        Args:
            text: latin-1 decoded content of the type-27 block.

        Returns:
            Dict with keys: y_unit, acquired_at, resolution_cm, instrument_serial.
        """
        result: dict = {
            "y_unit": None,
            "acquired_at": None,
            "resolution_cm": None,
            "instrument_serial": None,
        }

        # y_unit — "Final format:\t%(Transmittance|Absorbance|Reflectance|Single Beam)"
        m_fmt = re.search(
            r"Final format:\s*%?(Transmittance|Absorbance|Reflectance|Single Beam)",
            text,
        )
        if m_fmt:
            fmt = m_fmt.group(1)
            _unit_map = {
                "Transmittance": SpectralUnit.TRANSMITTANCE,
                "Absorbance": SpectralUnit.ABSORBANCE,
                "Reflectance": SpectralUnit.REFLECTANCE,
                "Single Beam": SpectralUnit.SINGLE_BEAM,
            }
            result["y_unit"] = _unit_map.get(fmt, SpectralUnit.ABSORBANCE)

        # acquired_at — "Background collected on <weekday> <mon> <dd> HH:MM:SS YYYY ..."
        m_date = re.search(
            r"Background collected on\s+(\w{3}\s+\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2}\s+\d{4})",
            text,
        )
        if m_date:
            date_str = m_date.group(1)
            try:
                result["acquired_at"] = datetime.strptime(date_str, "%a %b %d %H:%M:%S %Y")
            except ValueError:
                logger.debug("OMNIC history: could not parse date string %r", date_str)

        # resolution_cm — "Resolution:\t 0.500 from ..."
        m_res = re.search(r"Resolution:\s*([\d.]+)", text)
        if m_res:
            try:
                result["resolution_cm"] = float(m_res.group(1))
            except ValueError:
                pass

        # instrument_serial — "Bench Serial Number:AKX1300131"
        m_serial = re.search(r"Bench Serial Number:(\S+)", text)
        if m_serial:
            result["instrument_serial"] = m_serial.group(1)

        return result

    # ------------------------------------------------------------------
    # Compact/legacy format parser (Variant 2)
    # ------------------------------------------------------------------

    def _parse_compact_format(self, data: bytes) -> tuple[np.ndarray, np.ndarray, dict]:
        """Parse the compact/synthetic SPA format used in test blobs.

        Raises:
            ValueError: On corrupt header, missing intensity block, or
                        out-of-bounds offsets.
        """
        if len(data) < _MIN_FILE_BYTES:
            raise ValueError(
                f"SPA file too short ({len(data)} bytes); minimum expected {_MIN_FILE_BYTES} bytes."
            )

        # --- Parse section count ---
        (n_sections,) = struct.unpack_from("<H", data, _N_SECTIONS_OFFSET)
        if n_sections == 0 or n_sections > _MAX_SECTIONS:
            raise ValueError(
                f"Implausible section count {n_sections}; "
                f"expected 1–{_MAX_SECTIONS}. File may be corrupt."
            )

        # --- Walk section directory ---
        params_block: bytes | None = None
        intensity_block: bytes | None = None

        for i in range(n_sections):
            entry_start = _SECTION_DIR_OFFSET + i * _SECTION_ENTRY_SIZE
            if entry_start + _SECTION_ENTRY_SIZE > len(data):
                break  # directory truncated; use what we have

            sec_type = struct.unpack_from("<H", data, entry_start + _ENTRY_TYPE_OFFSET)[0]
            offset = struct.unpack_from("<I", data, entry_start + _ENTRY_DATA_OFFSET)[0]
            size = struct.unpack_from("<I", data, entry_start + _ENTRY_SIZE_OFFSET)[0]

            # Validate offset and size are within file bounds
            if offset + size > len(data):
                logger.warning(
                    "SPA section %d (type=%d) has out-of-bounds range [%d, %d]; skipping.",
                    i,
                    sec_type,
                    offset,
                    offset + size,
                )
                continue

            block = data[offset : offset + size]

            if sec_type == _SECTION_PARAMS and params_block is None:
                params_block = block
            elif sec_type == _SECTION_INTENSITIES and intensity_block is None:
                intensity_block = block

        # --- Require intensity block ---
        if intensity_block is None:
            raise ValueError(
                f"SPA file missing intensity section (type {_SECTION_INTENSITIES}). "
                "File may be corrupt or use an unsupported variant."
            )

        n_floats = len(intensity_block) // 4
        intensities = np.frombuffer(intensity_block, dtype="<f4", count=n_floats).astype(np.float64)

        # --- Parse wavenumber parameters ---
        first_wn, last_wn = self._parse_wavenumber_params(params_block, n_floats)

        # Build wavenumber axis
        wavenumbers = np.linspace(first_wn, last_wn, intensities.shape[0])

        # --- Ensure ascending order ---
        if wavenumbers[0] > wavenumbers[-1]:
            wavenumbers = wavenumbers[::-1].copy()
            intensities = intensities[::-1].copy()

        return wavenumbers, intensities, {"omnic_format": False}

    # ------------------------------------------------------------------
    # Title extraction
    # ------------------------------------------------------------------

    def _extract_title(self, data: bytes) -> str:
        """Extract title/comment from file header.

        For OMNIC files: bytes 30–284 (255-byte comment, null-terminated).
        For compact files: bytes 0–29 (30-byte title, null-padded).
        """
        if data[: len(_OMNIC_MAGIC)] == _OMNIC_MAGIC:
            raw = data[_OMNIC_TITLE_OFFSET : _OMNIC_TITLE_OFFSET + _OMNIC_TITLE_LENGTH]
        else:
            raw = data[:_TITLE_LENGTH]
        return raw.rstrip(b"\x00").decode("latin-1", errors="replace").strip()

    # ------------------------------------------------------------------
    # Wavenumber parameter parsing (compact format only)
    # ------------------------------------------------------------------

    def _parse_wavenumber_params(
        self, block: bytes | None, n_intensity_points: int
    ) -> tuple[float, float]:
        """Extract (first_wn, last_wn) from compact-format parameter block.

        Tries Variant A [n_points, first_wn, last_wn] then
        Variant B [first_wn, last_wn, n_points].  Falls back to
        a default 4000→400 cm⁻¹ range with a warning if the block
        is missing or both variants yield implausible values.

        Args:
            block: Raw bytes of the type-11 section (may be None).
            n_intensity_points: Number of intensity points (used as fallback).

        Returns:
            (first_wn, last_wn) as floats.
        """
        if block is not None and len(block) >= 12:
            # Variant A: [n_points: u32, first_wn: f32, last_wn: f32]
            n_pts_a, wn_a, wn_b = struct.unpack_from("<Iff", block, 0)
            if self._wn_plausible(wn_a, wn_b):
                return float(wn_a), float(wn_b)

            # Variant B: [first_wn: f32, last_wn: f32, n_points: u32]
            wn_c, wn_d, n_pts_b = struct.unpack_from("<ffI", block, 0)
            if self._wn_plausible(wn_c, wn_d):
                return float(wn_c), float(wn_d)

            logger.warning(
                "SPA parameter block found but wavenumbers are implausible "
                "(variants A=%s/%s, B=%s/%s); using default range.",
                wn_a,
                wn_b,
                wn_c,
                wn_d,
            )

        warnings.warn(
            "SPA parameter block not found or unreadable; "
            "defaulting to 4000–400 cm⁻¹ wavenumber range.",
            UserWarning,
            stacklevel=3,
        )
        return 4000.0, 400.0

    @staticmethod
    def _wn_plausible(wn1: float, wn2: float) -> bool:
        """Return True if both wavenumbers are in the physically plausible range
        and are distinct from each other."""
        in_range = _WN_MIN <= wn1 <= _WN_MAX and _WN_MIN <= wn2 <= _WN_MAX
        return in_range and wn1 != wn2
