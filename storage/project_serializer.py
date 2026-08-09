"""ProjectSerializer — save and load Projects as JSON files."""

from __future__ import annotations

import base64
import binascii
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from core.metadata import SpectrumMetadata
from core.peak import Peak
from core.project import Project
from core.spectrum import Spectrum
from file_io.atomic_output import atomic_output_path


class ProjectSerializer:
    """Serialize and deserialize Project objects."""

    FORMAT = "ir-spectra-analyzer-project"
    VERSION = 1

    def save(self, project: Project, path: str | Path) -> None:
        """Save project to a JSON file at path."""
        output_path = Path(path)
        payload = {
            "format": self.FORMAT,
            "version": self.VERSION,
            "project": self._project_to_dict(project),
        }
        with atomic_output_path(output_path) as temp_path:
            with temp_path.open("w", encoding="utf-8") as fp:
                json.dump(
                    payload,
                    fp,
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                    default=self._json_default,
                )
                fp.flush()

    def load(self, path: str | Path) -> Project:
        """Load project from a JSON file at path."""
        input_path = Path(path)
        if not input_path.exists():
            raise FileNotFoundError(f"Project file not found: {input_path}")

        with input_path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)

        if not isinstance(data, dict):
            raise ValueError("Project file is not a valid JSON object")

        if data.get("format") != self.FORMAT:
            raise ValueError("Unsupported project format")

        if data.get("version") != self.VERSION:
            raise ValueError("Unsupported project version")

        project_data = data.get("project")
        if not isinstance(project_data, dict):
            raise ValueError("Missing project data in file")

        return self._project_from_dict(project_data)

    def _project_to_dict(self, project: Project) -> dict[str, Any]:
        return {
            "name": project.name,
            "smiles": project.smiles,
            "mol_block": project.mol_block,
            "structure_image": base64.b64encode(project.structure_image).decode()
            if project.structure_image
            else "",
            "created_at": self._datetime_to_iso(project.created_at),
            "updated_at": self._datetime_to_iso(project.updated_at),
            "db_id": project.db_id,
            "spectrum": self._spectrum_to_dict(project.spectrum) if project.spectrum else None,
            "corrected_spectrum": self._spectrum_to_dict(project.corrected_spectrum)
            if project.corrected_spectrum
            else None,
            "metadata": self._metadata_to_dict(project.metadata),
            "peaks": [self._peak_to_dict(p) for p in project.peaks],
        }

    def _project_from_dict(self, data: dict[str, Any]) -> Project:
        spectrum_data = data.get("spectrum")
        corrected_data = data.get("corrected_spectrum")
        peaks_data = data.get("peaks", [])
        if not isinstance(peaks_data, list):
            raise ValueError("Project peaks must be a JSON array")

        spectrum = self._spectrum_from_dict(spectrum_data) if spectrum_data is not None else None
        corrected_spectrum = (
            self._spectrum_from_dict(corrected_data) if corrected_data is not None else None
        )
        created_at = self._iso_to_datetime(data.get("created_at")) or datetime.now()
        updated_at = self._iso_to_datetime(data.get("updated_at")) or created_at

        project = Project(
            name=data.get("name", ""),
            smiles=data.get("smiles", ""),
            spectrum=spectrum,
            peaks=[self._peak_from_dict(p) for p in peaks_data],
            metadata=self._metadata_from_dict(data.get("metadata")),
            created_at=created_at,
            updated_at=updated_at,
            db_id=data.get("db_id"),
        )
        project.corrected_spectrum = corrected_spectrum
        project.mol_block = data.get("mol_block", "")
        si_raw = data.get("structure_image", "")
        if si_raw is None or si_raw == "":
            project.structure_image = b""
        elif not isinstance(si_raw, str):
            raise ValueError("Project structure_image must be a base64 string")
        else:
            try:
                project.structure_image = base64.b64decode(si_raw, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("Project structure_image is not valid base64") from exc
        return project

    @staticmethod
    def _intensities_to_json(intensities: np.ndarray) -> list[Any]:
        """Serialise intensities, mapping blanked points to JSON ``null``.

        OMNIC writes NaN where a region was blanked because the solvent absorbs
        completely. JSON has no NaN literal and the writer runs with
        ``allow_nan=False`` to keep the file standards-compliant, so those points
        travel as ``null`` and come back as NaN. Infinities are left untouched so
        that genuinely corrupt data still fails the write.
        """
        values = intensities.tolist()
        return [None if isinstance(v, float) and math.isnan(v) else v for v in values]

    @staticmethod
    def _spectrum_to_dict(spectrum: Spectrum) -> dict[str, Any]:
        return {
            "wavenumbers": spectrum.wavenumbers.tolist(),
            "intensities": ProjectSerializer._intensities_to_json(spectrum.intensities),
            "title": spectrum.title,
            "source_path": str(spectrum.source_path) if spectrum.source_path is not None else None,
            "acquired_at": spectrum.acquired_at.isoformat() if spectrum.acquired_at else None,
            "y_unit": spectrum.y_unit.value if spectrum.y_unit else None,
            "x_unit": spectrum.x_unit.value if spectrum.x_unit else None,
            "comments": spectrum.comments,
            "extra_metadata": spectrum.extra_metadata or {},
        }

    @staticmethod
    def _spectrum_from_dict(data: dict[str, Any]) -> Spectrum:
        if not isinstance(data, dict):
            raise ValueError("Spectrum data must be a JSON object")

        from core.spectrum import SpectralUnit, XAxisUnit

        try:
            wavenumbers = np.asarray(data.get("wavenumbers", []), dtype=float)
            intensities = np.asarray(data.get("intensities", []), dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError("Spectrum arrays must contain numeric values") from exc

        if wavenumbers.shape != intensities.shape:
            raise ValueError("Spectrum wavenumbers and intensities shape mismatch")
        if wavenumbers.ndim != 1:
            raise ValueError("Spectrum arrays must be one-dimensional")
        if not np.all(np.isfinite(wavenumbers)):
            raise ValueError("Spectrum wavenumbers must contain only finite values")
        # NaN intensities are legitimate — they mark blanked regions, and JSON
        # ``null`` decodes straight to NaN here. Infinities remain a hard error.
        if np.isinf(intensities).any():
            raise ValueError("Spectrum intensities must not contain infinite values")

        extra_metadata = data.get("extra_metadata", {})
        if extra_metadata is None:
            extra_metadata = {}
        if not isinstance(extra_metadata, dict):
            raise ValueError("Spectrum extra_metadata must be a JSON object")

        y_unit_value = data.get("y_unit")
        x_unit_value = data.get("x_unit")

        return Spectrum(
            wavenumbers=wavenumbers,
            intensities=intensities,
            title=data.get("title", ""),
            source_path=Path(data["source_path"]) if data.get("source_path") else None,
            acquired_at=ProjectSerializer._iso_to_datetime(data.get("acquired_at")),
            y_unit=SpectralUnit(y_unit_value) if y_unit_value else SpectralUnit.ABSORBANCE,
            x_unit=XAxisUnit(x_unit_value) if x_unit_value else XAxisUnit.WAVENUMBER,
            comments=data.get("comments", ""),
            extra_metadata=extra_metadata,
        )

    @staticmethod
    def _metadata_to_dict(metadata: SpectrumMetadata) -> dict[str, Any]:
        return {
            "title": metadata.title,
            "file_name": metadata.file_name,
            # Legacy alias kept so a project saved here still opens in builds
            # before 0.20.0, where this field was called "sample_name".
            "sample_name": metadata.file_name,
            "operator": metadata.operator,
            "instrument": metadata.instrument,
            "acquired_at": ProjectSerializer._datetime_to_iso(metadata.acquired_at),
            "resolution": metadata.resolution,
            "scans": metadata.scans,
            "comments": metadata.comments,
            "extra": metadata.extra or {},
        }

    @staticmethod
    def _metadata_from_dict(data: dict[str, Any] | None) -> SpectrumMetadata:
        if data is None:
            return SpectrumMetadata()
        if not isinstance(data, dict):
            raise ValueError("Project metadata must be a JSON object")
        extra = data.get("extra", {})
        if extra is None:
            extra = {}
        if not isinstance(extra, dict):
            raise ValueError("Project metadata extra must be a JSON object")
        return SpectrumMetadata(
            title=data.get("title", ""),
            file_name=data.get("file_name") or data.get("sample_name", ""),
            operator=data.get("operator", ""),
            instrument=data.get("instrument", ""),
            acquired_at=ProjectSerializer._iso_to_datetime(data.get("acquired_at")),
            resolution=data.get("resolution"),
            scans=data.get("scans"),
            comments=data.get("comments", ""),
            extra=extra,
        )

    @staticmethod
    def _peak_to_dict(peak: Peak) -> dict[str, Any]:
        return {
            "position": peak.position,
            "intensity": peak.intensity,
            "label": peak.label,
            "vibration_id": peak.vibration_id,
            "vibration_ids": peak.vibration_ids,
            "vibration_labels": peak.vibration_labels,
            "label_offset_x": peak.label_offset_x,
            "label_offset_y": peak.label_offset_y,
            "manual_placement": peak.manual_placement,
            "fwhm": peak.fwhm,
            "db_id": peak.db_id,
            "smiles": peak.smiles,
        }

    @staticmethod
    def _peak_from_dict(data: dict[str, Any]) -> Peak:
        if not isinstance(data, dict):
            raise ValueError("Each project peak must be a JSON object")

        try:
            position = float(data.get("position", 0.0))
            intensity = float(data.get("intensity", 0.0))
            label_offset_x = float(data.get("label_offset_x", 0.0))
            label_offset_y = float(data.get("label_offset_y", 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError("Peak numeric fields must contain numbers") from exc
        if not all(
            np.isfinite(value) for value in (position, intensity, label_offset_x, label_offset_y)
        ):
            raise ValueError("Peak numeric fields must contain only finite values")

        # New format
        vibration_ids = data.get("vibration_ids", [])
        vibration_labels = data.get("vibration_labels", [])
        if not isinstance(vibration_ids, list) or not isinstance(vibration_labels, list):
            raise ValueError("Peak vibration_ids and vibration_labels must be JSON arrays")
        vibration_ids = list(vibration_ids)
        vibration_labels = list(vibration_labels)
        if not all(
            value is None or (isinstance(value, int) and not isinstance(value, bool))
            for value in vibration_ids
        ):
            raise ValueError("Peak vibration_ids entries must be integers or null")
        if not all(isinstance(value, str) for value in vibration_labels):
            raise ValueError("Peak vibration_labels entries must be strings")

        # Backward-compat: old single-vibration projects
        legacy_vibration_id = data.get("vibration_id")
        if legacy_vibration_id is not None and (
            not isinstance(legacy_vibration_id, int) or isinstance(legacy_vibration_id, bool)
        ):
            raise ValueError("Peak vibration_id must be an integer or null")
        if not vibration_ids and legacy_vibration_id is not None:
            vibration_ids = [legacy_vibration_id]
        if vibration_labels and not vibration_ids:
            vibration_ids = [None] * len(vibration_labels)
        if not vibration_labels and len(vibration_ids) == 1:
            legacy_label = data.get("label") or str(int(round(position)))
            vibration_labels = [str(legacy_label)]
        if len(vibration_ids) != len(vibration_labels):
            raise ValueError("Peak vibration_ids and vibration_labels must have equal lengths")

        fwhm_raw = data.get("fwhm")
        fwhm = None if fwhm_raw is None else float(fwhm_raw)
        if fwhm is not None and not np.isfinite(fwhm):
            raise ValueError("Peak fwhm must be finite")

        return Peak(
            position=position,
            intensity=intensity,
            label=data.get("label", ""),
            vibration_id=legacy_vibration_id,
            vibration_ids=vibration_ids,
            vibration_labels=vibration_labels,
            label_offset_x=label_offset_x,
            label_offset_y=label_offset_y,
            manual_placement=bool(data.get("manual_placement", False)),
            fwhm=fwhm,
            db_id=data.get("db_id"),
            smiles=data.get("smiles", ""),
        )

    @staticmethod
    def _datetime_to_iso(dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return dt.isoformat()

    @staticmethod
    def _json_default(value: Any) -> str | int | float | bool:
        """Convert NumPy scalar values at serialization boundaries.

        Parsers normally normalize these values already, but metadata and
        manually assembled projects are public extension points where NumPy
        scalar types can legitimately appear. Unsupported objects still fail
        loudly instead of being stringified and silently changing meaning.
        """
        if isinstance(value, np.bool_):
            return bool(value)
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return float(value)
        if isinstance(value, np.str_):
            return str(value)
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    @staticmethod
    def _iso_to_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value)
