from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_distribution_and_runtime_versions_match() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    config_text = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    runtime_version = re.search(r'^APP_VERSION = "([^"]+)"$', config_text, re.MULTILINE)

    assert runtime_version is not None
    assert project["version"] == runtime_version.group(1) == "0.26.0"
    assert project["gui-scripts"]["ir-spectra"] == "main:main"


def test_wheel_explicitly_includes_entry_module_and_assets() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    force_include = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]

    assert force_include["main.py"] == "main.py"
    assert force_include["assets"] == "assets"


def test_static_analysis_pins_match_the_verified_pre_commit_hooks() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev_dependencies = config["project"]["optional-dependencies"]["dev"]
    pre_commit = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    assert "ruff==0.16.1" in dev_dependencies
    assert "mypy==1.10.0" in dev_dependencies
    assert "rev: v0.16.1" in pre_commit
    assert "- id: ruff-check" in pre_commit
    assert "https://github.com/pre-commit/mirrors-mypy" in pre_commit
    assert "rev: v1.10.0" in pre_commit
    assert "- id: mypy" in pre_commit


def test_application_open_path_routes_through_controller_api() -> None:
    from app.application import Application

    opened: list[str] = []

    class _Window:
        _project = None  # an empty window is reused instead of spawning another

        @staticmethod
        def _open_recent_path(path: str) -> None:
            opened.append(path)

    controller = Application()
    controller._windows.append(_Window())
    controller.open_path(ROOT / "sample.irproj")

    assert opened == [str(ROOT / "sample.irproj")]


def test_startup_argument_parser_selects_supported_existing_file(tmp_path: Path) -> None:
    from main import _startup_file_from_args

    project = tmp_path / "sample.irproj"
    project.write_text("{}", encoding="utf-8")

    assert _startup_file_from_args(["--style", "Fusion", str(project)]) == project


def test_source_url_normalization_is_not_relative_to_working_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from utils.file_utils import normalize_source_path

    monkeypatch.chdir(tmp_path)

    assert (
        normalize_source_path("HTTPS://WebBook.NIST.GOV:443/cgi/cbook.cgi?Mask=80&ID=C64175#chart")
        == "https://webbook.nist.gov/cgi/cbook.cgi?ID=C64175&Mask=80"
    )


def test_malformed_http_source_is_not_treated_as_a_local_path() -> None:
    import pytest

    from utils.file_utils import normalize_source_path

    with pytest.raises(ValueError, match="absolute HTTP"):
        normalize_source_path("https://")


def test_ipv6_source_url_keeps_required_address_brackets() -> None:
    from utils.file_utils import normalize_source_url

    assert normalize_source_url("https://[2001:DB8::1]:443/a#fragment") == (
        "https://[2001:db8::1]/a"
    )


def test_release_workflow_rejects_version_drift_and_non_bundle_versions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert 'VERSION="$SOURCE_VERSION"' in workflow
    assert '"$VERSION" != "$SOURCE_VERSION"' in workflow
    assert '"$SOURCE_VERSION" != "$RUNTIME_VERSION"' in workflow
    assert "^[0-9]+\\.[0-9]+\\.[0-9]+$" in workflow
    assert "python -m ruff check ." in workflow
    assert "python -m ruff format --check" in workflow
    assert "python -m pre_commit run mypy --all-files" in workflow


def test_installer_registers_spa_open_with_without_replacing_omnic() -> None:
    installer = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")

    assert (
        'Root: HKA; Subkey: "Software\\Classes\\.spa\\OpenWithProgids"; '
        'ValueType: string; ValueName: "IRSpectraAnalyzer.spa"; ValueData: ""'
    ) in installer
    assert 'Subkey: "Software\\Classes\\.spa"; ValueType: string; ValueName: ""' not in installer
    assert "ValueType: none" not in installer
