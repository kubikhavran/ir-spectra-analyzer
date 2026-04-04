"""Named report preset management backed by user settings."""

from __future__ import annotations

from dataclasses import dataclass

from reporting.pdf_generator import ReportOptions
from storage.settings import Settings


@dataclass(frozen=True)
class ReportPreset:
    """A named reusable combination of report options."""

    name: str
    options: ReportOptions


class ReportPresetManager:
    """Manage reusable named report presets stored in user settings."""

    _PRESETS_KEY = "report_presets"
    _LAST_USED_KEY = "report_last_used_preset"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()
        self._settings.load()

    def list_presets(self) -> list[ReportPreset]:
        """Return all saved presets in stored order."""
        raw_presets = self._settings.get(self._PRESETS_KEY, []) or []
        presets: list[ReportPreset] = []
        for item in raw_presets:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            presets.append(ReportPreset(name=name, options=self._options_from_dict(item)))
        return presets

    def get_preset(self, name: str) -> ReportPreset | None:
        """Return one preset by name, or None when it does not exist."""
        normalized = name.strip()
        if not normalized:
            return None
        for preset in self.list_presets():
            if preset.name == normalized:
                return preset
        return None

    def save_preset(self, name: str, options: ReportOptions) -> None:
        """Create or update a named preset."""
        normalized = name.strip()
        if not normalized:
            raise ValueError("Preset name cannot be empty")

        raw_presets = list(self._settings.get(self._PRESETS_KEY, []) or [])
        payload = {"name": normalized, **self._options_to_dict(options)}

        for index, item in enumerate(raw_presets):
            if isinstance(item, dict) and str(item.get("name", "")).strip() == normalized:
                raw_presets[index] = payload
                self._settings.set(self._PRESETS_KEY, raw_presets)
                return

        raw_presets.append(payload)
        self._settings.set(self._PRESETS_KEY, raw_presets)

    def delete_preset(self, name: str) -> None:
        """Delete a preset by name if it exists."""
        normalized = name.strip()
        if not normalized:
            return

        raw_presets = list(self._settings.get(self._PRESETS_KEY, []) or [])
        filtered = [
            item
            for item in raw_presets
            if not (isinstance(item, dict) and str(item.get("name", "")).strip() == normalized)
        ]
        self._settings.set(self._PRESETS_KEY, filtered)

        if self.get_last_used_preset_name() == normalized:
            self.set_last_used_preset_name(None)

    def get_last_used_preset_name(self) -> str | None:
        """Return the last-used preset name when it still exists."""
        value = self._settings.get(self._LAST_USED_KEY)
        if not value:
            return None
        name = str(value).strip()
        if not name:
            return None
        if self.get_preset(name) is None:
            return None
        return name

    def set_last_used_preset_name(self, name: str | None) -> None:
        """Persist the last-used preset name, or clear it."""
        normalized = name.strip() if name is not None else ""
        self._settings.set(self._LAST_USED_KEY, normalized or None)

    @staticmethod
    def _options_to_dict(options: ReportOptions) -> dict[str, object]:
        """Serialize ReportOptions for JSON-backed settings storage."""
        return {
            "include_metadata": options.include_metadata,
            "include_peak_table": options.include_peak_table,
            "include_structures": options.include_structures,
            "dpi": options.dpi,
        }

    @staticmethod
    def _options_from_dict(data: dict[str, object]) -> ReportOptions:
        """Deserialize ReportOptions from stored preset data."""
        dpi = data.get("dpi", ReportOptions().dpi)
        try:
            dpi_value = int(dpi)
        except (TypeError, ValueError):
            dpi_value = ReportOptions().dpi

        return ReportOptions(
            include_metadata=bool(data.get("include_metadata", True)),
            include_peak_table=bool(data.get("include_peak_table", True)),
            include_structures=bool(data.get("include_structures", True)),
            dpi=dpi_value,
        )
