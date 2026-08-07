"""Tests for NIST WebBook reference import backend."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


def _make_nist_html() -> str:
    return """<!DOCTYPE html>
<html>
<head><title>Triethanolamine</title></head>
<body>
<table>
<tr><th scope="row">State</th><td>LIQUID (NEAT)</td></tr>
<tr><th scope="row">Path length</th><td>CAPILLARY</td></tr>
<tr><th scope="row">Resolution</th><td>2</td></tr>
<tr><th scope="row">Sampling procedure</th><td>TRANSMISSION</td></tr>
<tr><th scope="row">Origin</th><td>Sadtler Research Labs Under US-EPA Contract</td></tr>
<tr><th scope="row">Owner</th><td>NIST Standard Reference Data Program</td></tr>
</table>
<a href="/cgi/cbook.cgi?JCAMP=C102716&amp;Index=0&amp;Type=IR">JCAMP</a>
</body>
</html>
"""


def _make_nist_jcamp() -> bytes:
    return b"""##TITLE=Triethanolamine
##JCAMP-DX=4.24
##DATA TYPE=INFRARED SPECTRUM
##STATE=LIQUID (NEAT)
##XUNITS=1/CM
##YUNITS=ABSORBANCE
##XYPOINTS=(XY..XY)
1000 0.1 1200 0.2 1400 0.3
##END=
"""


def test_nist_webbook_client_fetches_metadata_and_jcamp():
    from app.providers.nist_webbook import NISTWebBookClient

    responses = {
        "https://webbook.nist.gov/cgi/cbook.cgi?ID=C102716&Index=0&Type=IR-SPEC": _make_nist_html().encode(
            "utf-8"
        ),
        "https://webbook.nist.gov/cgi/cbook.cgi?JCAMP=C102716&Index=0&Type=IR": _make_nist_jcamp(),
    }

    client = NISTWebBookClient(fetcher=lambda url: responses[url])
    reference = client.fetch_reference(
        "https://webbook.nist.gov/cgi/cbook.cgi?ID=C102716&Index=0&Type=IR-SPEC"
    )

    assert reference.name == "Triethanolamine"
    assert reference.metadata["state"] == "LIQUID (NEAT)"
    assert reference.metadata["sampling_procedure"] == "TRANSMISSION"
    assert reference.jcamp_url.endswith("JCAMP=C102716&Index=0&Type=IR")
    assert np.allclose(reference.spectrum.wavenumbers, [1000.0, 1200.0, 1400.0])
    assert np.allclose(reference.spectrum.intensities, [0.1, 0.2, 0.3])


def test_nist_webbook_client_accepts_direct_jcamp_url():
    from app.providers.nist_webbook import NISTWebBookClient

    page_url = "https://webbook.nist.gov/cgi/cbook.cgi?ID=C102716&Index=0&Type=IR-SPEC"
    jcamp_url = "https://webbook.nist.gov/cgi/cbook.cgi?JCAMP=C102716&Index=0&Type=IR"
    responses = {
        page_url: _make_nist_html().encode("utf-8"),
        jcamp_url: _make_nist_jcamp(),
    }

    client = NISTWebBookClient(fetcher=lambda url: responses[url])
    reference = client.fetch_reference(jcamp_url)

    assert reference.page_url == page_url
    assert reference.name == "Triethanolamine"


def test_nist_webbook_client_strips_surrounding_url_whitespace():
    from app.providers.nist_webbook import NISTWebBookClient

    page_url = "https://webbook.nist.gov/cgi/cbook.cgi?ID=C102716&Index=0&Type=IR-SPEC"
    jcamp_url = "https://webbook.nist.gov/cgi/cbook.cgi?JCAMP=C102716&Index=0&Type=IR"
    responses = {
        page_url: _make_nist_html().encode("utf-8"),
        jcamp_url: _make_nist_jcamp(),
    }

    reference = NISTWebBookClient(fetcher=lambda url: responses[url]).fetch_reference(
        f"  {page_url}\n"
    )

    assert reference.page_url == page_url


def test_web_reference_import_service_imports_nist_reference(tmp_path: Path):
    from app.providers.nist_webbook import NISTWebBookClient
    from app.web_reference_import import WebReferenceImportService
    from storage.database import Database

    page_url = "https://webbook.nist.gov/cgi/cbook.cgi?ID=C102716&Index=0&Type=IR-SPEC"
    jcamp_url = "https://webbook.nist.gov/cgi/cbook.cgi?JCAMP=C102716&Index=0&Type=IR"
    responses = {
        page_url: _make_nist_html().encode("utf-8"),
        jcamp_url: _make_nist_jcamp(),
    }

    db = Database(db_path=tmp_path / "test.db")
    db.initialize()
    service = WebReferenceImportService(
        db,
        nist_client=NISTWebBookClient(fetcher=lambda url: responses[url]),
    )

    imported = service.import_nist_reference(page_url)
    refs = db.get_reference_spectra()
    stored = next(ref for ref in refs if ref["id"] == imported.ref_id)

    assert imported.provider == "nist_webbook"
    assert stored["name"] == "Triethanolamine"
    assert stored["source"] == page_url
    assert stored["source_provider"] == "nist_webbook"
    assert stored["external_id"] == "C102716"
    assert stored["sample_state"] == "LIQUID (NEAT)"
    assert stored["sampling_procedure"] == "TRANSMISSION"
    assert stored["path_length"] == "CAPILLARY"
    assert stored["resolution"] == "2"
    assert stored["origin"] == "Sadtler Research Labs Under US-EPA Contract"
    assert stored["owner"] == "NIST Standard Reference Data Program"
    assert stored["description"].startswith("NIST WebBook")
    assert stored["y_unit"] == "Absorbance"
    assert np.allclose(stored["wavenumbers"], [1000.0, 1200.0, 1400.0])
    db.close()


@pytest.mark.parametrize(
    "url",
    [
        "http://webbook.nist.gov/cgi/cbook.cgi?ID=C102716",
        "https://webbook.nist.gov.evil.example/cgi/cbook.cgi?ID=C102716",
        "https://webbook.nist.gov@127.0.0.1/cgi/cbook.cgi?ID=C102716",
        "https://user@webbook.nist.gov/cgi/cbook.cgi?ID=C102716",
        "https://webbook.nist.gov:444/cgi/cbook.cgi?ID=C102716",
        "ftp://webbook.nist.gov/cgi/cbook.cgi?ID=C102716",
    ],
)
def test_nist_webbook_client_rejects_non_https_or_non_nist_urls(url: str) -> None:
    from app.providers.nist_webbook import NISTWebBookClient

    fetched: list[str] = []
    client = NISTWebBookClient(fetcher=lambda candidate: fetched.append(candidate) or b"")

    with pytest.raises(ValueError, match="NIST WebBook"):
        client.fetch_reference(url)

    assert fetched == []


def test_nist_webbook_client_rejects_off_site_jcamp_link() -> None:
    from app.providers.nist_webbook import NISTWebBookClient

    page_url = "https://webbook.nist.gov/cgi/cbook.cgi?ID=C102716&Index=0&Type=IR-SPEC"
    html = b'<html><a href="https://evil.example/payload?JCAMP=C102716">JCAMP</a></html>'
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return html

    with pytest.raises(ValueError, match="NIST WebBook"):
        NISTWebBookClient(fetcher=fetch).fetch_reference(page_url)

    assert fetched == [page_url]


def test_nist_redirect_handler_rejects_before_following_offsite_redirect() -> None:
    from app.providers.nist_webbook import _NISTRedirectHandler

    handler = _NISTRedirectHandler()
    with pytest.raises(ValueError, match="NIST WebBook"):
        handler.redirect_request(
            None,
            None,
            302,
            "Found",
            {},
            "https://evil.example/payload.jdx",
        )


def test_nist_response_reader_enforces_size_limit() -> None:
    from app.providers.nist_webbook import _read_limited_response

    class _Response:
        headers = {"Content-Length": "5"}

        @staticmethod
        def read(size: int) -> bytes:
            return b"12345"[:size]

    with pytest.raises(ValueError, match="too large"):
        _read_limited_response(_Response(), max_bytes=4)
