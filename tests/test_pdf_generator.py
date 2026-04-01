"""Tests for PDF report generation (stub until v0.1.0 implementation)."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_pdf_generator_raises_not_implemented() -> None:
    """PDFGenerator.generate() should raise NotImplementedError until implemented."""
    from reporting.pdf_generator import PDFGenerator
    from core.project import Project

    gen = PDFGenerator()
    project = Project(name="test")
    with pytest.raises(NotImplementedError):
        gen.generate(project, Path("/tmp/test.pdf"))
