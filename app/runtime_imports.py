"""Runtime import helpers (no-op after io/ → file_io/ rename)."""

from __future__ import annotations


def install_project_imports() -> None:
    """No-op: stdlib collision with io/ package has been eliminated by renaming to file_io/."""
