"""NIST Chemistry WebBook IR reference importer backend."""

from __future__ import annotations

import re
import ssl
from dataclasses import dataclass
from html import unescape
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from app.config import APP_VERSION
from core.spectrum import Spectrum
from file_io.jcamp_reader import JCAMPReader

_TITLE_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.IGNORECASE | re.DOTALL)
_ROW_RE = re.compile(
    r"<tr[^>]*>\s*<th[^>]*>\s*(.*?)\s*</th>\s*<td[^>]*>\s*(.*?)\s*</td>\s*</tr>",
    re.IGNORECASE | re.DOTALL,
)
_JCAMP_RE = re.compile(r'href="([^"]*?\bJCAMP=[^"]+)"', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_NIST_HOST = "webbook.nist.gov"
_MAX_RESPONSE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class NISTWebBookReference:
    """Fetched and parsed NIST WebBook IR reference."""

    name: str
    page_url: str
    jcamp_url: str
    spectrum: Spectrum
    metadata: dict[str, str]

    @property
    def description(self) -> str:
        parts = ["NIST WebBook"]
        for label, key in (
            ("State", "state"),
            ("Sampling", "sampling_procedure"),
            ("Path length", "path_length"),
            ("Resolution", "resolution"),
            ("Origin", "origin"),
        ):
            value = self.metadata.get(key, "").strip()
            if value:
                parts.append(f"{label}: {value}")
        return " | ".join(parts)


class NISTWebBookClient:
    """User-driven fetcher for NIST Chemistry WebBook IR references."""

    def __init__(self, fetcher=None) -> None:
        self._fetcher = fetcher or self._default_fetch
        self._jcamp_reader = JCAMPReader()

    def fetch_reference(self, url: str) -> NISTWebBookReference:
        """Fetch a NIST WebBook IR reference page and parse its JCAMP payload."""
        page_url = self._normalize_page_url(url)
        html = self._fetcher(page_url).decode("utf-8", errors="replace")
        metadata = self._extract_metadata(html)
        metadata.setdefault("external_id", self._extract_external_id(page_url))
        jcamp_url = self._extract_jcamp_url(html, page_url)
        jcamp_bytes = self._fetcher(jcamp_url)
        spectrum = self._jcamp_reader.read_bytes(
            jcamp_bytes,
            source_path=None,
            title_hint=metadata.get("title", ""),
        )
        spectrum.extra_metadata.update(
            {
                "web_provider": "nist_webbook",
                "source_url": page_url,
                "jcamp_url": jcamp_url,
                "state": metadata.get("state", ""),
                "sampling_procedure": metadata.get("sampling_procedure", ""),
                "path_length": metadata.get("path_length", ""),
                "resolution": metadata.get("resolution", ""),
                "origin": metadata.get("origin", ""),
                "owner": metadata.get("owner", ""),
            }
        )
        if metadata.get("title"):
            spectrum.title = metadata["title"]
        return NISTWebBookReference(
            name=metadata.get("title", spectrum.title),
            page_url=page_url,
            jcamp_url=jcamp_url,
            spectrum=spectrum,
            metadata=metadata,
        )

    def _normalize_page_url(self, url: str) -> str:
        parsed = urlparse(url.strip())
        _validate_nist_url(url)

        query = parse_qs(parsed.query, keep_blank_values=True)
        if "JCAMP" in query:
            identifier = query["JCAMP"][0]
            index = query.get("Index", ["0"])[0]
            query = {"ID": [identifier], "Index": [index], "Type": ["IR-SPEC"]}
            return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

        if query.get("Type", [""])[0] != "IR-SPEC":
            query["Type"] = ["IR-SPEC"]
            return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
        return urlunparse(parsed)

    def _extract_metadata(self, html: str) -> dict[str, str]:
        metadata: dict[str, str] = {}
        title_match = _TITLE_RE.search(html)
        if title_match:
            metadata["title"] = self._clean_html(title_match.group(1))

        for raw_key, raw_value in _ROW_RE.findall(html):
            key = self._slugify(self._clean_html(raw_key))
            metadata[key] = self._clean_html(raw_value)
        return metadata

    def _extract_jcamp_url(self, html: str, page_url: str) -> str:
        match = _JCAMP_RE.search(html)
        if match is None:
            raise ValueError("NIST page does not expose a JCAMP download link.")
        jcamp_url = urljoin(page_url, unescape(match.group(1)))
        _validate_nist_url(jcamp_url)
        return jcamp_url

    @staticmethod
    def _extract_external_id(page_url: str) -> str:
        parsed = urlparse(page_url)
        return parse_qs(parsed.query).get("ID", [""])[0]

    @staticmethod
    def _clean_html(value: str) -> str:
        return " ".join(unescape(_TAG_RE.sub(" ", value)).split())

    @staticmethod
    def _slugify(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")

    @staticmethod
    def _default_fetch(url: str) -> bytes:
        _validate_nist_url(url)
        request = Request(
            url,
            headers={
                "User-Agent": (
                    f"Mozilla/5.0 (compatible; IR-Spectra-Analyzer/{APP_VERSION}; "
                    "+https://github.com/kubikhavran/ir-spectra-analyzer)"
                )
            },
        )
        opener = build_opener(_NISTRedirectHandler(), HTTPSHandler(context=_ssl_context()))
        with opener.open(request, timeout=20) as response:  # noqa: S310
            _validate_nist_url(response.geturl())
            return _read_limited_response(response, max_bytes=_MAX_RESPONSE_BYTES)


class _NISTRedirectHandler(HTTPRedirectHandler):
    """Reject redirects before urllib can contact a non-NIST destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_nist_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_nist_url(url: str) -> None:
    """Require an exact, credential-free HTTPS NIST WebBook origin."""
    parsed = urlparse(url.strip())
    if parsed.scheme.casefold() != "https":
        raise ValueError("NIST WebBook URL must use HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("NIST WebBook URL must not contain credentials.")
    if (parsed.hostname or "").casefold() != _NIST_HOST:
        raise ValueError("Only NIST WebBook URLs are supported.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("NIST WebBook URL contains an invalid port.") from exc
    if port not in {None, 443}:
        raise ValueError("NIST WebBook URL must use the standard HTTPS port.")


def _read_limited_response(response, *, max_bytes: int) -> bytes:
    """Read at most ``max_bytes`` and reject oversized network responses."""
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            declared_size = int(content_length)
        except (TypeError, ValueError):
            declared_size = None
        if declared_size is not None and declared_size > max_bytes:
            raise ValueError(f"NIST WebBook response is too large ({declared_size} bytes).")

    payload = bytes(response.read(max_bytes + 1))
    if len(payload) > max_bytes:
        raise ValueError(f"NIST WebBook response is too large (limit {max_bytes} bytes).")
    return payload


def _ssl_context() -> ssl.SSLContext:
    """Prefer a bundled CA bundle when available, otherwise use urllib defaults."""
    try:
        import certifi  # noqa: PLC0415
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())
