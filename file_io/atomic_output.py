"""Small same-directory atomic-write primitive shared by persisted outputs."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_output_path(output_path: str | Path) -> Iterator[Path]:
    """Yield a temporary sibling and replace ``output_path`` only after success.

    Writers may use any API that accepts a filesystem path.  The temporary file
    lives in the destination directory, which keeps ``os.replace`` atomic on the
    same filesystem and leaves an existing good output untouched on failure.
    """
    destination = Path(output_path)
    fd, raw_temp_path = tempfile.mkstemp(
        prefix=f".{destination.stem}.",
        suffix=f".tmp{destination.suffix}",
        dir=str(destination.parent),
    )
    os.close(fd)
    temp_path = Path(raw_temp_path)
    try:
        yield temp_path
        # Windows requires a writable descriptor for ``fsync``.
        with temp_path.open("rb+") as handle:
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    except BaseException:
        # Cleanup is best-effort: on Windows a third-party writer may still
        # have the temporary file open after failing.  Do not let that mask
        # the original export error or affect the existing destination.
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
