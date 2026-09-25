import re
from collections.abc import Iterator
from pathlib import Path

from pypdf import PdfReader

from rulehall.core.validation import Refusal

MIN_PASSAGE = 24
# The in-play request prompt adds cast and history under the 131072-byte argv cap.
SOURCE_MAX_BYTES = 48_000
BLANK_LINE = re.compile(r"\n\s*\n")
LINE_BREAK_HYPHEN = re.compile(r"(\w)-\s+(\w)")
CAPS_HEADING = re.compile(r"[A-Z][A-Z '-]+:")


def given_text(premise: str, document: Path | None) -> str:
    """A premise next to a document tells the model what to take from the document."""
    if document is None:
        return f"PREMISE:\n{premise}"
    whole = f"SOURCE DOCUMENT:\n{whole_text(document)}"
    return f"PREMISE:\n{premise}\n\n{whole}" if premise else whole


def whole_text(path: Path) -> str:
    try:
        pages = (
            _pdf_pages(path)
            if path.suffix.lower() == ".pdf"
            else (path.read_text(encoding="utf-8"),)
        )
    # pypdf raises whatever it likes on hostile bytes; nothing of ours runs in this block.
    except Exception as broken:
        raise Refusal(f"{path.name} cannot be read: {broken}") from broken
    text = "\n\n".join(passage for page in pages for passage in _passages(page))
    if not text:
        raise Refusal(f"{path.name} holds no readable text")
    size = len(text.encode("utf-8"))
    if size > SOURCE_MAX_BYTES:
        raise Refusal(f"{path.name} is {size} bytes. This is too large to give to a model.")
    return text


def _pdf_pages(path: Path) -> tuple[str, ...]:
    # Layout mode interleaves columns and mangles letter-spaced display text.
    return tuple(page.extract_text() for page in PdfReader(path).pages)


def _passages(body: str) -> Iterator[str]:
    for block in BLANK_LINE.split(body.strip()):
        text = " ".join(LINE_BREAK_HYPHEN.sub(r"\1-\2", _unquoted(block)).split())
        # A page number or a running header is not a passage.
        if len(text) >= MIN_PASSAGE and not CAPS_HEADING.fullmatch(text):
            yield text


def _unquoted(block: str) -> str:
    return "\n".join(line.strip().removeprefix(">").strip() for line in block.splitlines())
