import pydantic
import pytest
from support.table import EnvFileFreeSettings

from rulehall.config import ProviderConfig, RoleConfig, RoleSettings


def test_a_role_carries_its_own_model_and_inherits_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROLES__MASTER__MODEL", "fable")
    settings = EnvFileFreeSettings()
    assert settings.roles.for_name("master").model == "fable"
    assert settings.roles.for_name("narrator").model == "sonnet"


def test_a_role_on_a_provider_without_a_key_is_refused() -> None:
    with pytest.raises(ValueError, match="master uses provider 'openrouter', which has no api_key"):
        _ = EnvFileFreeSettings(
            roles=RoleSettings(master=RoleConfig(provider="openrouter", model="m"))
        )
    local = EnvFileFreeSettings(roles=RoleSettings(master=RoleConfig(provider="local", model="m")))
    assert local.roles.master.provider == "local"


REFUSAL_PATTERNS = ("base_url", "ascii host name")


@pytest.mark.parametrize(
    ("given", "expected"),
    (
        ("not a url", "base_url"),
        ("http://☃.example/v1", "ascii host name"),
        ("https://open\nrouter.ai/v1", "base_url"),
        ("http://localhost:1234", "http://localhost:1234"),
        (" https://openrouter.ai/api/v1\n", "https://openrouter.ai/api/v1"),
        ("http://localhost:11434/v1/", "http://localhost:11434/v1"),
    ),
    ids=(
        "not-a-url",
        "idn-host",
        "interior-newline",
        "kept-as-given",
        "padded",
        "trailing-slash",
    ),
)
def test_a_base_url_is_stored_as_given_or_refused(given: str, expected: str) -> None:
    """`expected` is the stored url, or the message a refused url must carry."""
    if expected in REFUSAL_PATTERNS:
        with pytest.raises(pydantic.ValidationError, match=expected):
            _ = ProviderConfig(base_url=given, api_key=pydantic.SecretStr(""))
        return

    assert ProviderConfig(base_url=given, api_key=pydantic.SecretStr("")).base_url == expected
