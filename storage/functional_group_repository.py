"""Load the functional-group knowledge base from JSON."""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

from core.functional_groups import (
    FunctionalGroupBand,
    FunctionalGroupCoherenceRule,
    FunctionalGroupDefinition,
    FunctionalGroupKnowledgeBase,
)

_DATA_RELATIVE = Path("storage") / "data" / "functional_groups.v1.json"


def _default_data_path() -> Path:
    # PyInstaller unpacks bundled data next to the exe under sys._MEIPASS
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        candidate = Path(meipass) / _DATA_RELATIVE
        if candidate.exists():
            return candidate
    # Normal (source / editable install) path
    return Path(__file__).resolve().parent / "data" / "functional_groups.v1.json"


class FunctionalGroupRepository:
    """Repository for sourced functional-group diagnostics."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_data_path()

    def load(self) -> FunctionalGroupKnowledgeBase:
        return _load_knowledge_base(self._path)


@lru_cache(maxsize=4)
def _load_knowledge_base(path: Path) -> FunctionalGroupKnowledgeBase:
    raw = json.loads(path.read_text(encoding="utf-8"))
    groups: list[FunctionalGroupDefinition] = []

    for group_raw in raw["groups"]:
        bands = tuple(
            FunctionalGroupBand(
                id=band_raw["id"],
                label=band_raw["label"],
                range_min=float(band_raw["range_min"]),
                range_max=float(band_raw["range_max"]),
                expected_intensity=band_raw["expected_intensity"],
                shape=band_raw["shape"],
                role=band_raw.get("role", "supporting"),
                weight=float(band_raw.get("weight", 1.0)),
                reliability=float(band_raw.get("reliability", 1.0)),
                channel=band_raw.get("channel", "sharp_corrected"),
                suggested_preset_names=tuple(band_raw.get("suggested_preset_names", [])),
                source_refs=tuple(band_raw.get("source_refs", [])),
            )
            for band_raw in group_raw["bands"]
        )
        coherence_rules = tuple(
            FunctionalGroupCoherenceRule(
                band_ids=tuple(rule_raw["band_ids"]),
                bonus=float(rule_raw["bonus"]),
                threshold=float(rule_raw.get("threshold", 0.45)),
                label=rule_raw.get("label", ""),
            )
            for rule_raw in group_raw.get("coherence_rules", [])
        )
        groups.append(
            FunctionalGroupDefinition(
                id=group_raw["id"],
                name=group_raw["name"],
                color=group_raw["color"],
                bands=bands,
                coherence_rules=coherence_rules,
                source_refs=tuple(group_raw.get("source_refs", [])),
                summary=group_raw.get("summary", ""),
            )
        )

    return FunctionalGroupKnowledgeBase(
        version=int(raw["version"]),
        sources={key: str(value) for key, value in raw["sources"].items()},
        groups=tuple(groups),
    )
