"""Root conftest.py — registers project packages that shadow stdlib names.

The project has a local ``io/`` package that conflicts with Python's stdlib
``io`` module. This conftest installs a custom meta path finder so that
pytest imports of ``io.spa_binary`` (and siblings) resolve to the project's
own package, not the stdlib.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from types import ModuleType

_PROJECT_ROOT = os.path.dirname(__file__)

# These top-level package names are handled by the project-local finder.
# Only add names that actually exist as directories with __init__.py here.
_PROJECT_PACKAGES = {"io", "core", "processing", "reporting", "storage", "ui"}


class _ProjectPackageFinder:
    """Meta path finder that resolves project-local packages before stdlib."""

    def find_spec(
        self,
        fullname: str,
        path: object,
        target: object = None,
    ) -> importlib.util.ModuleSpec | None:  # type: ignore[type-arg]
        top = fullname.split(".")[0]
        if top not in _PROJECT_PACKAGES:
            return None

        parts = fullname.split(".")
        candidate_dir = os.path.join(_PROJECT_ROOT, *parts)
        candidate_file = os.path.join(_PROJECT_ROOT, *parts[:-1], parts[-1] + ".py")

        if os.path.isdir(candidate_dir):
            init = os.path.join(candidate_dir, "__init__.py")
            if os.path.isfile(init):
                return importlib.util.spec_from_file_location(
                    fullname,
                    init,
                    submodule_search_locations=[candidate_dir],
                )
        elif os.path.isfile(candidate_file):
            return importlib.util.spec_from_file_location(fullname, candidate_file)

        return None


# Install our finder at the very front of meta_path so it wins over stdlib.
_finder = _ProjectPackageFinder()
if _finder not in sys.meta_path:
    sys.meta_path.insert(0, _finder)

# Eagerly evict any already-cached stdlib entry for names we own,
# so the next import goes through our finder.
for _pkg in list(_PROJECT_PACKAGES):
    cached: ModuleType | None = sys.modules.get(_pkg)
    if cached is not None and not getattr(cached, "__path__", None):
        # Cached module has no __path__ → it is not a package (stdlib scalar module).
        # Remove it so our finder can supply the real package.
        del sys.modules[_pkg]
