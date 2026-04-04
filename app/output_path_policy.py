"""Helpers for explicit overwrite behavior in batch output workflows."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path


class OverwriteMode(StrEnum):
    """Supported policies for output-file collisions."""

    SKIP = "skip"
    OVERWRITE = "overwrite"
    RENAME = "rename"


OVERWRITE_MODE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Skip existing", OverwriteMode.SKIP.value),
    ("Overwrite existing", OverwriteMode.OVERWRITE.value),
    ("Rename automatically", OverwriteMode.RENAME.value),
)


def resolve_output_path(target_path: Path, overwrite_mode: str) -> tuple[str, Path | None]:
    """Resolve how a batch workflow should handle a target-path collision.

    Returns:
        A tuple of:
        - ``"write"`` and the resolved destination path when the caller should write output
        - ``"skip"`` and ``None`` when the caller should skip this item
    """
    mode = OverwriteMode(overwrite_mode)

    if not target_path.exists():
        return "write", target_path

    if mode == OverwriteMode.SKIP:
        return "skip", None

    if mode == OverwriteMode.OVERWRITE:
        return "write", target_path

    candidate = target_path
    index = 1
    while candidate.exists():
        candidate = target_path.with_name(f"{target_path.stem} ({index}){target_path.suffix}")
        index += 1
    return "write", candidate
