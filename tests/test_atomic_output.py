"""Tests for file_io.atomic_output."""

import os
import sys

import pytest

from file_io.atomic_output import atomic_output_path

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX permission bits are not meaningful on Windows"
)


def _expected_default_mode() -> int:
    current = os.umask(0)
    os.umask(current)
    return 0o666 & ~current


def test_written_file_is_readable_like_a_normal_document(tmp_path):
    """mkstemp creates 0600; an exported report must not stay owner-only."""
    destination = tmp_path / "report.pdf"

    with atomic_output_path(destination) as temp_path:
        temp_path.write_bytes(b"pdf")

    assert destination.stat().st_mode & 0o777 == _expected_default_mode()


def test_overwrite_keeps_the_permissions_the_user_already_set(tmp_path):
    destination = tmp_path / "report.pdf"
    destination.write_bytes(b"old")
    os.chmod(destination, 0o640)

    with atomic_output_path(destination) as temp_path:
        temp_path.write_bytes(b"new")

    assert destination.read_bytes() == b"new"
    assert destination.stat().st_mode & 0o777 == 0o640


def _write_then_fail(destination):
    with atomic_output_path(destination) as temp_path:
        temp_path.write_bytes(b"half written")
        raise RuntimeError("writer blew up")


def test_failed_write_leaves_the_previous_file_untouched(tmp_path):
    destination = tmp_path / "report.pdf"
    destination.write_bytes(b"good")

    with pytest.raises(RuntimeError, match="writer blew up"):
        _write_then_fail(destination)

    assert destination.read_bytes() == b"good"
    assert list(tmp_path.iterdir()) == [destination]
