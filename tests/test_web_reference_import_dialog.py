"""Tests for the one-shot web reference import dialog."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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


def test_web_reference_import_dialog_previews_and_imports(qtbot, tmp_path: Path):
    from app.providers.nist_webbook import NISTWebBookClient
    from app.web_reference_import import WebReferenceImportService
    from storage.database import Database
    from ui.dialogs.web_reference_import_dialog import WebReferenceImportDialog

    page_url = "https://webbook.nist.gov/cgi/cbook.cgi?ID=C102716&Index=0&Type=IR-SPEC"
    jcamp_url = "https://webbook.nist.gov/cgi/cbook.cgi?JCAMP=C102716&Index=0&Type=IR"
    responses = {
        page_url: _make_nist_html().encode("utf-8"),
        jcamp_url: _make_nist_jcamp(),
    }

    def fetcher(url: str) -> bytes:
        return responses[url]

    db = Database(db_path=tmp_path / "test.db")
    db.initialize()
    service = WebReferenceImportService(
        db,
        nist_client=NISTWebBookClient(fetcher=fetcher),
    )
    dlg = WebReferenceImportDialog(
        service,
        preview_client=NISTWebBookClient(fetcher=fetcher),
    )
    qtbot.addWidget(dlg)

    imported_ids: list[int] = []
    dlg.reference_imported.connect(imported_ids.append)

    dlg._url_edit.setText(page_url)
    qtbot.mouseClick(dlg._preview_btn, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "Triethanolamine" in dlg._preview_label.text())

    assert "State: LIQUID (NEAT)" in dlg._preview_label.text()
    assert "Sampling: TRANSMISSION" in dlg._preview_label.text()
    assert dlg._import_btn.isEnabled()

    qtbot.mouseClick(dlg._import_btn, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(imported_ids))

    rows = db.get_reference_metadata()
    assert imported_ids == [rows[0]["id"]]
    assert rows[0]["name"] == "Triethanolamine"
    assert rows[0]["source_provider"] == "nist_webbook"
    assert rows[0]["sample_state"] == "LIQUID (NEAT)"
    assert rows[0]["sampling_procedure"] == "TRANSMISSION"
    db.close()
