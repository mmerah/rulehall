from collections.abc import Callable
from pathlib import Path

import pytest
from nicegui import Client
from support.table import ScriptedRoles, offline_settings

from rulehall.app.runtime import Runtime
from rulehall.config import read_settings, save_settings
from rulehall.ui.settings import SettingsForm


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


def test_a_stored_secret_is_never_read_back_into_the_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, page: Callable[[], Client]
) -> None:
    _ = (tmp_path / ".env").write_text(
        "PROVIDERS__OPENROUTER__API_KEY=sk-live-123\nPROVIDERS__LOCAL__API_KEY=\n"
    )
    for shadowing in ("PROVIDERS__OPENROUTER__API_KEY", "PROVIDERS__LOCAL__API_KEY"):
        monkeypatch.delenv(shadowing, raising=False)
    monkeypatch.chdir(tmp_path)
    page()
    form = SettingsForm(Runtime(offline_settings(tmp_path), roles=ScriptedRoles()))
    stored = form.boxes["providers", "openrouter", "api_key"]
    blank = form.boxes["providers", "local", "api_key"]

    assert stored.value in (None, "")
    assert stored.props["placeholder"] == "set — type to replace"
    assert blank.props["placeholder"] == "not set"
