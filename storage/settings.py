"""
Settings — Uživatelské nastavení aplikace (JSON).

Zodpovědnost:
- Načítání a ukládání uživatelských předvoleb
- JSON serializace do ~/.ir-spectra-analyzer/settings.json
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import SETTINGS_PATH


class Settings:
    """User preferences stored as JSON file."""

    _DEFAULTS: dict = {
        "recent_files": [],
        "window_width": 1400,
        "window_height": 900,
        "theme": "dark",
        "auto_detect_peaks": True,
        "peak_prominence": 0.01,
        "report_presets": [],
        "report_last_used_preset": None,
        "reference_library_folder": None,
    }

    def __init__(self, settings_path: Path = SETTINGS_PATH) -> None:
        self._path = settings_path
        self._data: dict = dict(self._DEFAULTS)

    def load(self) -> None:
        """Load settings from JSON file, falling back to defaults."""
        if self._path.exists():
            try:
                with self._path.open(encoding="utf-8") as f:
                    loaded = json.load(f)
                self._data.update(loaded)
            except (json.JSONDecodeError, OSError):
                pass

    def save(self) -> None:
        """Persist current settings to JSON file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def get(self, key: str, default=None):
        """Get a settings value by key."""
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        """Set a settings value and auto-save."""
        self._data[key] = value
        self.save()
