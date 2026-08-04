"""
Čtení samotné struktury molekuly z uloženého `.irproj` projektu.

Zodpovědnost:
- Vytáhnout SMILES / mol block z projektového souboru bez načtení celého spektra
- Cachovat výsledek podle mtime souboru

Proč ne prostě `ProjectSerializer.load()`: uložený projekt v sobě nese celé
spektrum, takže laboratorní soubor (55 587 bodů) má ~2,4 MB a `json.load` nad ním
stojí ~28 ms. To je moc na akci, která se spouští při přejetí myší přes seznam
shod. Strukturní pole zapisuje serializer hned za jméno projektu, takže se dají
vyzobat z omezeného čtení začátku souboru (~0,1 ms); plný parse zůstává jako
pojistka, kdyby je tam někdo posunul dál.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Pokryje jméno + SMILES + mol block i u ručně nakreslené molekuly.
_HEAD_CHARS = 65_536


@dataclass(frozen=True)
class ProjectStructure:
    """Molecular structure stored in a project file."""

    smiles: str = ""
    mol_block: str = ""

    def __bool__(self) -> bool:
        """True when the project actually carries a structure."""
        return bool(self.smiles or self.mol_block)


def read_project_structure(path: Path | str, *, head_chars: int = _HEAD_CHARS) -> ProjectStructure:
    """Return the structure stored in a `.irproj`, without parsing the spectrum.

    Args:
        path: Project file to read.
        head_chars: How much of the file to scan before falling back to a full parse.

    Returns:
        The structure, or an empty one when the file has none or cannot be read.
    """
    project_path = Path(path)
    try:
        with project_path.open("r", encoding="utf-8") as handle:
            head = handle.read(head_chars)
    except OSError:
        return ProjectStructure()

    smiles = _scan_string_value(head, "smiles")
    mol_block = _scan_string_value(head, "mol_block")
    if smiles is not None or mol_block is not None:
        return ProjectStructure(smiles=smiles or "", mol_block=mol_block or "")

    # Neither key landed inside the head window — pay for the full parse rather
    # than reporting "no structure" for a project that has one.
    return _read_by_full_parse(project_path)


def _read_by_full_parse(path: Path) -> ProjectStructure:
    """Fallback that reads the structure through a complete JSON parse."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return ProjectStructure()
    project = data.get("project") if isinstance(data, dict) else None
    if not isinstance(project, dict):
        return ProjectStructure()
    return ProjectStructure(
        smiles=str(project.get("smiles") or ""),
        mol_block=str(project.get("mol_block") or ""),
    )


def _scan_string_value(text: str, key: str) -> str | None:
    """Return the first string value stored under `key`, or None when absent.

    The project-level fields are written before the peak list, so the first hit
    is the project's own value and never a peak's.
    """
    needle = f'"{key}"'
    search_from = 0
    while True:
        index = text.find(needle, search_from)
        if index < 0:
            return None
        cursor = _skip_space(text, index + len(needle))
        if cursor < len(text) and text[cursor] == ":":
            cursor = _skip_space(text, cursor + 1)
            if cursor < len(text) and text[cursor] == '"':
                return _read_json_string(text, cursor)
            return None  # present but not a string (e.g. null)
        search_from = index + len(needle)


def _skip_space(text: str, cursor: int) -> int:
    """Return the next non-whitespace offset at or after `cursor`."""
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    return cursor


def _read_json_string(text: str, start: int) -> str | None:
    """Decode the JSON string literal starting at `start`, or None if truncated."""
    cursor = start + 1
    while cursor < len(text):
        char = text[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == '"':
            try:
                decoded = json.loads(text[start : cursor + 1])
            except ValueError:
                return None
            return decoded if isinstance(decoded, str) else None
        cursor += 1
    return None  # the head window cut the value in half


class ProjectStructureCache:
    """Remembers structures per file and re-reads only when the file changes."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[tuple[int, int], ProjectStructure]] = {}

    def get(self, path: Path | str) -> ProjectStructure:
        """Return the cached structure for a project file, reading it if needed."""
        project_path = Path(path)
        key = str(project_path)
        try:
            stat = project_path.stat()
        except OSError:
            self._entries.pop(key, None)
            return ProjectStructure()

        stamp = (stat.st_mtime_ns, stat.st_size)
        cached = self._entries.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1]

        structure = read_project_structure(project_path)
        self._entries[key] = (stamp, structure)
        return structure

    def clear(self) -> None:
        """Forget everything read so far."""
        self._entries.clear()
