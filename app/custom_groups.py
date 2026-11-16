"""User-defined substituent groups for the structure editor, kept in settings."""

from __future__ import annotations

from storage.settings import Settings

_KEY = "molecule_custom_groups"


class CustomGroupStore:
    """Named groups as SMILES with ``*`` at the attachment point."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()
        self._settings.load()

    def groups(self) -> dict[str, str]:
        raw = self._settings.get(_KEY, {}) or {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items() if str(k).strip() and str(v).strip()}

    def save(self, name: str, smiles: str) -> None:
        name = name.strip()
        smiles = smiles.strip()
        if not name or not smiles:
            raise ValueError("A custom group needs a name and a SMILES")
        groups = self.groups()
        groups[name] = smiles
        self._settings.set(_KEY, groups)

    def remove(self, name: str) -> bool:
        groups = self.groups()
        if name not in groups:
            return False
        del groups[name]
        self._settings.set(_KEY, groups)
        return True
