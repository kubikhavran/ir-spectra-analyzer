"""JCAMP-DX reader for IR spectra."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import numpy as np

from core.spectrum import SpectralUnit, Spectrum, XAxisUnit

_NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?")


class JCAMPReadError(Exception):
    """Raised when a JCAMP-DX file cannot be parsed into a spectrum."""


class JCAMPReader:
    """Reader for a practical subset of JCAMP-DX used by public IR libraries."""

    def read(self, filepath: Path) -> Spectrum:
        """Read a JCAMP-DX IR spectrum from disk."""
        if not filepath.exists():
            raise FileNotFoundError(f"JCAMP file not found: {filepath}")

        return self.read_bytes(filepath.read_bytes(), source_path=filepath, title_hint=filepath.stem)

    def read_bytes(
        self,
        data: bytes,
        *,
        source_path: Path | None = None,
        title_hint: str = "",
    ) -> Spectrum:
        """Read a JCAMP-DX IR spectrum from raw bytes."""
        text = self._decode_text(data)
        records = self._parse_records(text)
        metadata = dict(records)

        x_values, intensities = self._extract_xy_arrays(records)
        x_values = self._normalize_x_axis(x_values, metadata.get("XUNITS", "1/CM"))

        order = np.argsort(x_values)
        x_values = x_values[order]
        intensities = intensities[order]

        y_unit = self._parse_y_unit(metadata.get("YUNITS", ""))
        acquired_at = self._parse_acquired_at(
            metadata.get("LONGDATE", ""),
            metadata.get("DATE", ""),
            metadata.get("TIME", ""),
        )

        extra_metadata = self._build_extra_metadata(metadata)
        comments = self._build_comments(metadata)

        return Spectrum(
            wavenumbers=x_values.astype(np.float64, copy=False),
            intensities=intensities.astype(np.float64, copy=False),
            title=metadata.get("TITLE", title_hint),
            source_path=source_path,
            acquired_at=acquired_at,
            y_unit=y_unit,
            x_unit=XAxisUnit.WAVENUMBER,
            comments=comments,
            extra_metadata=extra_metadata,
        )

    @staticmethod
    def _decode_text(data: bytes) -> str:
        for encoding in ("utf-8", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("latin-1", errors="replace")

    def _parse_records(self, text: str) -> list[tuple[str, str]]:
        records: list[tuple[str, str]] = []
        current_key: str | None = None
        current_lines: list[str] = []

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("$$"):
                continue
            if line.startswith("##"):
                if current_key is not None:
                    records.append((current_key, "\n".join(current_lines).strip()))
                body = line[2:]
                if "=" in body:
                    key, value = body.split("=", 1)
                else:
                    key, value = body, ""
                current_key = key.strip().upper()
                current_lines = [value.strip()]
                continue
            if current_key is not None:
                current_lines.append(line)

        if current_key is not None:
            records.append((current_key, "\n".join(current_lines).strip()))
        return records

    def _extract_xy_arrays(self, records: list[tuple[str, str]]) -> tuple[np.ndarray, np.ndarray]:
        metadata = dict(records)
        x_factor = self._parse_float(metadata.get("XFACTOR", "1.0"), default=1.0)
        y_factor = self._parse_float(metadata.get("YFACTOR", "1.0"), default=1.0)

        for key, value in records:
            if key == "XYDATA":
                return self._parse_xydata(value, metadata, x_factor=x_factor, y_factor=y_factor)
            if key == "XYPOINTS":
                return self._parse_xy_pairs(value, x_factor=x_factor, y_factor=y_factor)
            if key == "PEAK TABLE":
                return self._parse_xy_pairs(value, x_factor=x_factor, y_factor=y_factor)

        raise JCAMPReadError("JCAMP file does not contain XYDATA, XYPOINTS, or PEAK TABLE.")

    def _parse_xydata(
        self,
        value: str,
        metadata: dict[str, str],
        *,
        x_factor: float,
        y_factor: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if not lines:
            raise JCAMPReadError("XYDATA section is empty.")

        mode = lines[0].upper()
        data_lines = lines[1:] if mode.startswith("(") else lines
        if "X++" not in mode and lines[0].startswith("("):
            raise JCAMPReadError(f"Unsupported XYDATA mode: {lines[0]}")

        delta_x = self._parse_float(metadata.get("DELTAX", ""), default=np.nan)
        if np.isnan(delta_x):
            first_x = self._parse_float(metadata.get("FIRSTX", ""), default=np.nan)
            last_x = self._parse_float(metadata.get("LASTX", ""), default=np.nan)
            n_points = int(self._parse_float(metadata.get("NPOINTS", "0"), default=0.0))
            if n_points > 1 and not np.isnan(first_x) and not np.isnan(last_x):
                delta_x = (last_x - first_x) / (n_points - 1)
        if np.isnan(delta_x):
            raise JCAMPReadError("XYDATA requires DELTAX or FIRSTX/LASTX/NPOINTS metadata.")

        x_values: list[float] = []
        y_values: list[float] = []
        for line in data_lines:
            numbers = [float(token) for token in _NUMBER_RE.findall(line)]
            if len(numbers) < 2:
                continue
            base_x = numbers[0]
            for index, y_raw in enumerate(numbers[1:]):
                x_values.append((base_x + index * delta_x) * x_factor)
                y_values.append(y_raw * y_factor)

        if not x_values:
            raise JCAMPReadError("XYDATA section does not contain numeric samples.")
        return np.asarray(x_values, dtype=np.float64), np.asarray(y_values, dtype=np.float64)

    def _parse_xy_pairs(
        self,
        value: str,
        *,
        x_factor: float,
        y_factor: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if lines and lines[0].startswith("("):
            lines = lines[1:]

        numbers = [float(token) for token in _NUMBER_RE.findall(" ".join(lines))]
        if len(numbers) < 2 or len(numbers) % 2 != 0:
            raise JCAMPReadError("XYPOINTS / PEAK TABLE requires paired X/Y numeric values.")

        x_values = np.asarray(numbers[0::2], dtype=np.float64) * x_factor
        y_values = np.asarray(numbers[1::2], dtype=np.float64) * y_factor
        return x_values, y_values

    def _normalize_x_axis(self, x_values: np.ndarray, x_units: str) -> np.ndarray:
        unit = x_units.strip().upper().replace(" ", "")
        if unit in {"1/CM", "CM-1", "CM^-1", "WAVENUMBER"}:
            return x_values
        if unit in {"MICROMETERS", "MICROMETER", "MICRONS", "MICRON", "UM", "ΜM", "μM"}:
            return 10000.0 / x_values
        if unit in {"NANOMETERS", "NANOMETER", "NM"}:
            return 1.0e7 / x_values
        raise JCAMPReadError(f"Unsupported X units for IR import: {x_units}")

    def _parse_y_unit(self, value: str) -> SpectralUnit:
        unit = value.strip().upper().replace(" ", "")
        if not unit:
            return SpectralUnit.ABSORBANCE
        if any(token in unit for token in ("%T", "TRANSMITTANCE", "TRANSMISSION")):
            return SpectralUnit.TRANSMITTANCE
        if "REFLECT" in unit:
            return SpectralUnit.REFLECTANCE
        if "SINGLEBEAM" in unit or "SINGLE-BEAM" in value.upper():
            return SpectralUnit.SINGLE_BEAM
        if "ABS" in unit:
            return SpectralUnit.ABSORBANCE
        return SpectralUnit.ABSORBANCE

    def _parse_acquired_at(self, longdate: str, date: str, time: str) -> datetime | None:
        candidates = [longdate.strip()]
        if date.strip() and time.strip():
            candidates.append(f"{date.strip()} {time.strip()}")
        candidates.extend([date.strip(), time.strip()])

        formats = (
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d-%b-%Y %H:%M:%S",
            "%d-%b-%Y %H:%M",
            "%d-%b-%y %H:%M:%S",
            "%d-%b-%y %H:%M",
            "%Y/%m/%d",
            "%Y-%m-%d",
        )
        for candidate in candidates:
            if not candidate:
                continue
            for dt_format in formats:
                try:
                    return datetime.strptime(candidate, dt_format)
                except ValueError:
                    continue
        return None

    def _build_extra_metadata(self, metadata: dict[str, str]) -> dict:
        interesting_keys = {
            "JCAMP-DX": "jcamp_dx_version",
            "DATA TYPE": "data_type",
            "ORIGIN": "origin",
            "OWNER": "owner",
            "STATE": "state",
            "SAMPLING PROCEDURE": "sampling_procedure",
            "PATH LENGTH": "path_length",
            "RESOLUTION": "resolution",
            "SPECTROMETER/DATA SYSTEM": "instrument",
            "CAS REGISTRY NO": "cas_registry_no",
            "MOLFORM": "molecular_formula",
            "XUNITS": "raw_x_units",
            "YUNITS": "raw_y_units",
            "LONGDATE": "longdate",
            "DATE": "date",
            "TIME": "time",
        }
        extra = {
            target_key: metadata[source_key]
            for source_key, target_key in interesting_keys.items()
            if metadata.get(source_key)
        }
        extra["jcamp_headers"] = dict(metadata)
        return extra

    def _build_comments(self, metadata: dict[str, str]) -> str:
        comment_fields = [
            metadata.get("ORIGIN", "").strip(),
            metadata.get("OWNER", "").strip(),
            metadata.get("SAMPLING PROCEDURE", "").strip(),
            metadata.get("STATE", "").strip(),
        ]
        return " | ".join(field for field in comment_fields if field)

    @staticmethod
    def _parse_float(value: str, *, default: float) -> float:
        match = _NUMBER_RE.search(value)
        if match is None:
            return default
        try:
            return float(match.group(0))
        except ValueError:
            return default
