from pathlib import Path

import pytest
from pydantic import SecretStr

from rulehall.config import (
    ProviderConfig,
    read_settings,
    save_settings,
)
from rulehall.ui.settings import (
    _widget,  # pyright: ignore[reportPrivateUsage]
)


def test_a_saved_key_reads_back_and_the_rest_of_the_file_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    _ = env.write_text("# keep me\nPROVIDERS__OPENROUTER__API_KEY=test\nMEDIA__ENABLED=true\n")
    for shadowing in ("ROLES__NARRATOR__TIMEOUT", "MEDIA__MODEL", "MEDIA__ENABLED"):
        monkeypatch.delenv(shadowing, raising=False)
    monkeypatch.chdir(tmp_path)
    save_settings(
        {
            ("roles", "narrator", "timeout"): "90",
            ("media", "model"): 'it is "grim"',
            ("media", "enabled"): None,
        }
    )
    reread = read_settings()
    assert reread.roles.narrator.timeout == 90
    assert reread.media.model == 'it is "grim"'
    assert reread.media.enabled is False
    assert "# keep me" in env.read_text(encoding="utf-8")


def test_a_stored_secret_is_never_read_back_into_the_page() -> None:
    field = ProviderConfig.model_fields["api_key"]
    stored = _widget("api key", field, SecretStr("sk-live-123"))
    blank = _widget("api key", field, SecretStr(""))

    assert stored.value in (None, "")
    assert stored.props["placeholder"] == "set — type to replace"
    assert blank.props["placeholder"] == "not set"
