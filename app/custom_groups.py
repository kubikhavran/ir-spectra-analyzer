"""User-defined substituent groups for the structure editor, kept in settings.

Groups can be exported to and imported from a small JSON file, so a set of
groups (for example a laboratory's recurring building blocks) can be shared
between computers without being part of the application itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from storage.settings import Settings

_KEY = "molecule_custom_groups"
FILE_FORMAT = "ir-spectra-analyzer/custom-groups"


class CustomGroupStore:
    """Named groups as SMILES with ``*`` at the attachment point.

    A group without ``*`` is a whole building block (a scaffold): the editor
    places it as a separate molecule.
    """

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

    def export_to(self, path: str | Path) -> int:
        """Write every group to *path* as JSON; returns how many were written."""
        groups = self.groups()
        payload = {"format": FILE_FORMAT, "version": 1, "groups": groups}
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(groups)

    def import_from(self, path: str | Path) -> tuple[int, list[str]]:
        """Add the groups in *path* (same names are replaced).

        Returns the number imported and the names that were skipped because
        their SMILES is not a valid group. Raises ``ValueError`` for a file
        that is not a group file.
        """
        from chemistry.mol_fragments import fragment_from_smiles

        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Not a custom-group file") from exc
        raw = payload.get("groups") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            raise ValueError("Not a custom-group file")
        groups = self.groups()
        imported = 0
        skipped: list[str] = []
        for name, smiles in raw.items():
            name, smiles = str(name).strip(), str(smiles).strip()
            if not name or not smiles or fragment_from_smiles(smiles) is None:
                skipped.append(name or "?")
                continue
            groups[name] = smiles
            imported += 1
        if imported:
            self._settings.set(_KEY, groups)
        return imported, skipped
