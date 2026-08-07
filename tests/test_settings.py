"""Focused persistence tests for JSON-backed user settings."""

from __future__ import annotations

import json

import pytest

from storage.settings import Settings


def test_settings_failed_save_preserves_existing_file(tmp_path, monkeypatch) -> None:
    path = tmp_path / "settings.json"
    settings = Settings(path)
    settings.set("theme", "light")
    original = path.read_bytes()

    def _failing_dump(_payload, fp, **_kwargs) -> None:
        fp.write('{"partial":')
        raise OSError("simulated disk failure")

    monkeypatch.setattr("storage.settings.json.dump", _failing_dump)

    with pytest.raises(OSError, match="simulated disk failure"):
        settings.save()

    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp*"))


def test_settings_ignores_non_object_json(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    settings = Settings(path)
    settings.load()

    assert settings.get("theme") == "dark"


def test_settings_instances_do_not_share_mutable_defaults(tmp_path) -> None:
    first = Settings(tmp_path / "first.json")
    second = Settings(tmp_path / "second.json")

    first.get("recent_files").append("sample.spa")

    assert second.get("recent_files") == []
