"""NIST Chemistry WebBook IR reference importer backend."""

from __future__ import annotations

import re
import ssl
from dataclasses import dataclass
from html import unescape
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from core.spectrum import Spectrum
from file_io.jcamp_reader import JCAMPReader

_TITLE_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.IGNORECASE | re.DOTALL)
_ROW_RE = re.compile(
    r"<tr[^>]*>\s*<th[^>]*>\s*(.*?)\s*</th>\s*<td[^>]*>\s*(.*?)\s*</td>\s*</tr>",
    re.IGNORECASE | re.DOTALL,
)
_JCAMP_RE = re.compile(r'href="([^"]*?\bJCAMP=[^"]+)"', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


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
        if not parsed.scheme:
            raise ValueError("NIST WebBook URL must include http:// or https://")
        if "webbook.nist.gov" not in parsed.netloc:
            raise ValueError("Only NIST WebBook URLs are supported.")

        query = parse_qs(parsed.query, keep_blank_values=True)
        if "JCAMP" in query:
            identifier = query["JCAMP"][0]
            index = query.get("Index", ["0"])[0]
            query = {"ID": [identifier], "Index": [index], "Type": ["IR-SPEC"]}
            return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

        if query.get("Type", [""])[0] != "IR-SPEC":
            query["Type"] = ["IR-SPEC"]
            return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
        return url

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
        return urljoin(page_url, unescape(match.group(1)))

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
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; IR-Spectra-Analyzer/0.6; "
                    "+https://github.com/kubikhavran/ir-spectra-analyzer)"
                )
            },
        )
        with urlopen(request, timeout=20, context=_ssl_context()) as response:  # noqa: S310
            return response.read()


def _ssl_context() -> ssl.SSLContext | None:
    """Prefer a bundled CA bundle when available, otherwise use urllib defaults."""
    try:
        import certifi  # noqa: PLC0415
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())
