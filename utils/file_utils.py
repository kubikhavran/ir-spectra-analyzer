"""
FileUtils — Utility pro práci se soubory.

Zodpovědnost:
- Validace přípon souborů
- Bezpečné zajištění přípony výstupního souboru
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SUPPORTED_SPECTRAL_EXTENSIONS = {".spa", ".spc", ".jdx", ".dx", ".csv"}


def is_supported_spectral_file(path: Path) -> bool:
    """Return True if the file extension is a supported spectral format."""
    return path.suffix.lower() in SUPPORTED_SPECTRAL_EXTENSIONS


def ensure_extension(path: Path, extension: str) -> Path:
    """Return path with the given extension, adding it if missing.

    Args:
        path: Input file path.
        extension: Desired extension (with dot, e.g., ".pdf").

    Returns:
        Path with correct extension.
    """
    if path.suffix.lower() != extension.lower():
        return path.with_suffix(extension)
    return path


def normalize_source_path(path: Path | str) -> str:
    """Return a stable, case-insensitive normalized file path string.

    HTTP(S) sources are canonicalized as URLs instead of being resolved against
    the process working directory.  This function is used for reference-library
    duplicate detection and folder-scoped queries.
    """
    raw = str(path).strip()
    parsed = urlsplit(raw)
    if parsed.scheme.casefold() in {"http", "https"}:
        return normalize_source_url(raw)

    path_obj = Path(raw).expanduser()
    try:
        normalized = path_obj.resolve(strict=False)
    except OSError:
        normalized = path_obj
    return str(normalized).replace("\\", "/").casefold()


def normalize_source_url(url: str) -> str:
    """Return a stable canonical form for an HTTP(S) source URL."""
    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Source URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Source URL must not contain credentials")

    hostname = parsed.hostname.casefold()
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Source URL contains an invalid port") from exc
    default_port = 443 if scheme == "https" else 80
    host_for_netloc = f"[{hostname}]" if ":" in hostname else hostname
    netloc = host_for_netloc if port in {None, default_port} else f"{host_for_netloc}:{port}"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((scheme, netloc, parsed.path or "/", query, ""))
