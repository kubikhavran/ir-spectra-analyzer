"""Small same-directory atomic-write primitive shared by persisted outputs."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _default_file_mode() -> int:
    """Permissions a normally created file would get under the process umask.

    ``tempfile.mkstemp`` deliberately creates its file as 0600, and
    ``os.replace`` carries that mode onto the destination.  Exports are meant to
    be opened and shared like any other document, so the umask default is
    restored rather than silently narrowed.  Read once at import: querying the
    umask means temporarily clearing it, which must not race with file creation
    on the worker threads that run exports.
    """
    current = os.umask(0)
    os.umask(current)
    return 0o666 & ~current


_DEFAULT_FILE_MODE = _default_file_mode()


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
    # Overwriting keeps whatever the user set on the existing file; a new file
    # gets the usual umask default instead of mkstemp's private 0600.
    try:
        replacement_mode = destination.stat().st_mode & 0o777
    except OSError:
        replacement_mode = _DEFAULT_FILE_MODE
    try:
        os.chmod(temp_path, replacement_mode)
    except OSError:
        # Windows exposes only the read-only bit; a failure here must not stop
        # the export.
        pass
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
