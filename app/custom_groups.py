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
_RING_TEMPLATES_KEY = "molecule_ring_templates"
_GROUP_TEMPLATES_KEY = "molecule_group_templates"
FILE_FORMAT = "ir-spectra-analyzer/custom-groups"


class CustomGroupStore:
    """Named groups as SMILES with ``*`` at the attachment point, plus template overrides.

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

    def ring_templates(self) -> dict[str, dict[str, str]]:
        """Customized ring templates: ``ring_type -> {"smiles": ..., "mol_block": ...}``."""
        raw = self._settings.get(_RING_TEMPLATES_KEY, {}) or {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, dict[str, str]] = {}
        for k, v in raw.items():
            key = str(k).strip()
            if not key or not isinstance(v, dict):
                continue
            smiles = str(v.get("smiles", "")).strip()
            mol_block = str(v.get("mol_block", ""))
            if smiles or mol_block.strip():
                out[key] = {"smiles": smiles, "mol_block": mol_block}
        return out

    def save_ring_template(self, ring_type: str, smiles: str, mol_block: str = "") -> None:
        ring_type = ring_type.strip()
        smiles = smiles.strip()
        if not ring_type or (not smiles and not mol_block.strip()):
            raise ValueError("A ring template needs a key and a structure")
        templates = self.ring_templates()
        templates[ring_type] = {"smiles": smiles, "mol_block": mol_block}
        self._settings.set(_RING_TEMPLATES_KEY, templates)

    def remove_ring_template(self, ring_type: str) -> bool:
        templates = self.ring_templates()
        if ring_type not in templates:
            return False
        del templates[ring_type]
        self._settings.set(_RING_TEMPLATES_KEY, templates)
        return True

    def group_templates(self) -> dict[str, str]:
        """Customized functional-group templates: ``group_key -> smiles``."""
        raw = self._settings.get(_GROUP_TEMPLATES_KEY, {}) or {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items() if str(k).strip() and str(v).strip()}

    def save_group_template(self, group_key: str, smiles: str) -> None:
        group_key = group_key.strip()
        smiles = smiles.strip()
        if not group_key or not smiles:
            raise ValueError("A group template needs a key and a SMILES")
        templates = self.group_templates()
        templates[group_key] = smiles
        self._settings.set(_GROUP_TEMPLATES_KEY, templates)

    def remove_group_template(self, group_key: str) -> bool:
        templates = self.group_templates()
        if group_key not in templates:
            return False
        del templates[group_key]
        self._settings.set(_GROUP_TEMPLATES_KEY, templates)
        return True

    def clear_templates(self) -> None:
        """Remove all ring and functional-group template overrides."""
        self._settings.set(_RING_TEMPLATES_KEY, {})
        self._settings.set(_GROUP_TEMPLATES_KEY, {})

    def export_to(self, path: str | Path) -> int:
        """Write every group to *path* as JSON; returns how many were written."""
        groups = self.groups()
        payload: dict[str, object] = {"format": FILE_FORMAT, "version": 1, "groups": groups}
        ring_overrides = self.ring_templates()
        group_overrides = self.group_templates()
        if ring_overrides:
            payload["ring_templates"] = ring_overrides
        if group_overrides:
            payload["group_templates"] = group_overrides
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
