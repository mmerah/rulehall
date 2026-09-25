from pathlib import Path

import pytest

from rulehall.core.source import SOURCE_MAX_BYTES, whole_text
from rulehall.core.validation import Refusal

FIXTURES = Path(__file__).parent / "fixtures" / "source"


def test_a_markdown_document_reads_to_text_without_its_furniture() -> None:
    text = whole_text(FIXTURES / "drowned-road.md")

    assert "p. 3" not in text
    assert ">" not in text
    assert "chapel lamp is still a mile off" in text


def test_a_pdf_reads_to_text() -> None:
    text = whole_text(FIXTURES / "drowned-road.pdf")

    assert "chapel" in text.lower()
    assert "Bell House" in text


def test_whole_text_refuses_a_document_too_large_to_hand_to_a_model_whole(tmp_path: Path) -> None:
    text = "a short adventure about a bell and a tide"
    small = tmp_path / "small.md"
    small.write_text(text, encoding="utf-8")
    assert whole_text(small) == text

    big = tmp_path / "big.md"
    big.write_text("a" * (SOURCE_MAX_BYTES + 1), encoding="utf-8")
    with pytest.raises(Refusal, match="too large"):
        _ = whole_text(big)


def test_whole_text_refuses_a_pdf_that_is_not_readable(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 broken")
    with pytest.raises(Refusal, match="cannot be read"):
        _ = whole_text(broken)
