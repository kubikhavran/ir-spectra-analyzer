"""ProjectSerializer — save and load Projects as JSON files."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from core.peak import Peak
from core.project import Project
from core.spectrum import Spectrum


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
        with output_path.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)

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
            "created_at": self._datetime_to_iso(project.created_at),
            "updated_at": self._datetime_to_iso(project.updated_at),
            "db_id": project.db_id,
            "spectrum": self._spectrum_to_dict(project.spectrum) if project.spectrum else None,
            "corrected_spectrum": self._spectrum_to_dict(project.corrected_spectrum)
            if project.corrected_spectrum
            else None,
            "peaks": [self._peak_to_dict(p) for p in project.peaks],
        }

    def _project_from_dict(self, data: dict[str, Any]) -> Project:
        spectrum = self._spectrum_from_dict(data.get("spectrum")) if data.get("spectrum") else None
        corrected_spectrum = (
            self._spectrum_from_dict(data.get("corrected_spectrum"))
            if data.get("corrected_spectrum")
            else None
        )

        project = Project(
            name=data.get("name", ""),
            spectrum=spectrum,
            peaks=[self._peak_from_dict(p) for p in data.get("peaks", [])],
            created_at=self._iso_to_datetime(data.get("created_at")),
            updated_at=self._iso_to_datetime(data.get("updated_at")),
            db_id=data.get("db_id"),
        )
        project.corrected_spectrum = corrected_spectrum
        return project

    @staticmethod
    def _spectrum_to_dict(spectrum: Spectrum) -> dict[str, Any]:
        return {
            "wavenumbers": spectrum.wavenumbers.tolist(),
            "intensities": spectrum.intensities.tolist(),
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
        if data is None:
            raise ValueError("Spectrum data is missing")

        from core.spectrum import SpectralUnit, XAxisUnit

        wavenumbers = np.asarray(data.get("wavenumbers", []), dtype=float)
        intensities = np.asarray(data.get("intensities", []), dtype=float)

        if wavenumbers.shape != intensities.shape:
            raise ValueError("Spectrum wavenumbers and intensities shape mismatch")

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
            extra_metadata=data.get("extra_metadata", {}) or {},
        )

    @staticmethod
    def _peak_to_dict(peak: Peak) -> dict[str, Any]:
        return {
            "position": peak.position,
            "intensity": peak.intensity,
            "label": peak.label,
            "vibration_id": peak.vibration_id,
            "label_offset_x": peak.label_offset_x,
            "label_offset_y": peak.label_offset_y,
            "manual_placement": peak.manual_placement,
            "fwhm": peak.fwhm,
            "db_id": peak.db_id,
            "smiles": peak.smiles,
        }

    @staticmethod
    def _peak_from_dict(data: dict[str, Any]) -> Peak:
        return Peak(
            position=float(data.get("position", 0.0)),
            intensity=float(data.get("intensity", 0.0)),
            label=data.get("label", ""),
            vibration_id=data.get("vibration_id"),
            label_offset_x=float(data.get("label_offset_x", 0.0)),
            label_offset_y=float(data.get("label_offset_y", 0.0)),
            manual_placement=bool(data.get("manual_placement", False)),
            fwhm=data.get("fwhm"),
            db_id=data.get("db_id"),
            smiles=data.get("smiles", ""),
        )

    @staticmethod
    def _datetime_to_iso(dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return dt.isoformat()

    @staticmethod
    def _iso_to_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value)
