from pathlib import Path

from rulehall.core.io import ENCODING


def install_engine_dir(tmp_path: Path) -> None:
    """The three files a test engine's directory must hold before it is read."""
    (tmp_path / "rules.md").write_text("Roll high.", encoding=ENCODING)
    (tmp_path / "look.json").write_text(
        '{"palette": {"game-die-body": "#000", "game-die-ink": "#fff", "game-die-glow": "#fff"}}',
        encoding=ENCODING,
    )
    (tmp_path / "packs").mkdir()
    (tmp_path / "packs" / "srd.json").write_text(
        '{"name": "The SRD", "source": "the test", "license": "CC0"}', encoding=ENCODING
    )
