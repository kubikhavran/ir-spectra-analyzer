"""
StructurePreviewService — náhled struktury molekuly pro shodu z knihovny.

Zodpovědnost:
- Ze jména shody najít její uložený `.irproj` a vrátit PNG s molekulou
- Držet cache, aby přejíždění myší po seznamu shod nic nepřepočítávalo

Nic z toho neběží během hledání shod — služba se volá až při přejetí myší nad
konkrétní položkou. Čtení struktury je omezené na začátek souboru
(`core.project_structure`) a vyrenderované PNG se cachuje podle mtime souboru,
takže druhé přejetí přes tutéž shodu je zdarma.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from core.project_structure import ProjectStructureCache

# Hrana náhledu v logických pixelech. Rastruje se na dvojnásobek kvůli HiDPI a
# ani o pixel víc: rasterizace SVG je zdaleka nejdražší část přejetí myší
# (~11 ms na 440 px, ~15 ms na 520 px), kdežto čtení souboru a RDKit dohromady
# stojí pod 0,6 ms.
_PREVIEW_SIZE = 220
_HIDPI_SCALE = 2


class StructurePreviewService:
    """Turns a match name into a PNG of the structure in its saved project."""

    def __init__(
        self,
        *,
        size: int = _PREVIEW_SIZE,
        structure_cache: ProjectStructureCache | None = None,
    ) -> None:
        self._size = size
        self._structures = structure_cache or ProjectStructureCache()
        self._paths: dict[str, Path] = {}
        # name -> (file stamp, PNG bytes); empty bytes remembers "has no structure".
        self._rendered: dict[str, tuple[tuple[int, int], bytes]] = {}

    def set_project_paths(self, paths: Mapping[str, Path] | None) -> None:
        """Point the service at the current annotated-projects folder listing."""
        normalized = {
            str(name).strip().lower(): Path(path)
            for name, path in (paths or {}).items()
            if str(name).strip()
        }
        if normalized == self._paths:
            return
        self._paths = normalized
        self._rendered.clear()

    def preview_png(self, name: str) -> bytes | None:
        """Return PNG bytes of the structure saved for `name`, or None.

        None covers every "nothing to show" case: no saved project, no structure
        in it, or a structure the renderer could not draw.
        """
        key = str(name).strip().lower()
        path = self._paths.get(key)
        if path is None:
            return None

        try:
            stat = path.stat()
        except OSError:
            self._rendered.pop(key, None)
            return None
        stamp = (stat.st_mtime_ns, stat.st_size)

        cached = self._rendered.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1] or None

        png = self._render(path)
        self._rendered[key] = (stamp, png)
        return png or None

    def clear(self) -> None:
        """Drop every cached structure and rendered preview."""
        self._structures.clear()
        self._rendered.clear()

    def _render(self, path: Path) -> bytes:
        """Read the structure out of one project and draw it, or return b""."""
        from chemistry.structure_renderer import render_to_svg, svg_to_png_bytes  # noqa: PLC0415

        structure = self._structures.get(path)
        if not structure:
            return b""

        svg = render_to_svg(
            smiles=structure.smiles,
            mol_block=structure.mol_block,
            size=(self._size, self._size),
        )
        if not svg:
            return b""
        pixels = self._size * _HIDPI_SCALE
        return svg_to_png_bytes(svg, pixels, pixels) or b""
