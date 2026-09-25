from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal, Self

import httpx
from dotenv import set_key, unset_key
from pydantic import (
    AnyHttpUrl,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from rulehall.core.validation import Frozen, parse

type ProviderName = Literal["openrouter", "local"]
type Role = Literal["master", "narrator", "worldsmith", "opponent"]
type CliProvider = Literal["claude", "codex"]
# Spelled flat, not as a union of the two: the settings page renders one `Literal` as a select.
type RoleProvider = Literal["claude", "codex", "openrouter", "local"]
type Effort = Literal["low", "medium", "high"]
ENV_FILE = ".env"
LOOPBACK_HOST = "127.0.0.1"


class Configured(Frozen):
    """Settings arrive as env strings, so these read them lax; every other model is strict."""

    model_config = ConfigDict(strict=False)


class ProviderConfig(Configured):
    base_url: Annotated[str, StringConstraints(strip_whitespace=True)]
    api_key: SecretStr

    @field_validator("base_url")
    @classmethod
    def _valid_base_url(cls, base_url: str) -> str:
        """Kept as a plain string, not `AnyHttpUrl`: that type would double a bare host's slash."""
        if any(not char.isprintable() or char.isspace() for char in base_url):
            raise ValueError("a base url holds no spaces or control characters")
        AnyHttpUrl(base_url)
        try:
            httpx.URL(base_url)
        except httpx.InvalidURL as bad:
            raise ValueError("a base url holds an ascii host name") from bad
        return base_url.rstrip("/")


class RoleConfig(Configured):
    provider: RoleProvider = "claude"
    # A string, not a `Literal`: model aliases move faster than this file.
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    effort: Effort = "medium"
    timeout: float = Field(
        default=300.0,
        gt=0.0,
        description="the time limit for the whole run: the CLI process, or the API rounds",
    )
    max_rounds: int = Field(default=30, gt=0, description="used only with a completion API")


class MediaConfig(Configured):
    enabled: bool = False
    provider: ProviderName = "openrouter"
    model: str = "google/gemini-3.1-flash-lite-image"
    timeout: float = Field(default=180.0, gt=0.0)


class BattleConfig(Configured):
    sprites: Literal["2d", "3d"] = Field(
        default="2d",
        description="The battle sprites: 2d is the gen 5 pixel art, 3d the animated models.",
    )
    music: bool = Field(default=True, description="Battle music and the cry of each Pokemon.")
    opponent: Literal["random", "model"] = Field(
        default="random",
        description="Who plays a trainer's side: random picks any legal choice, model asks the "
        "opponent role with every damage range.",
    )


class TranscriptConfig(Configured):
    refusals: bool = Field(
        default=False,
        description="Show each game master move the rules refused, as a card in the story. "
        "A refusal can name something the story has not revealed yet.",
    )


class ServerConfig(Configured):
    # `0.0.0.0` opens the game to the LAN; `/mcp` stays loopback-only on its own.
    host: str = LOOPBACK_HOST
    port: int = Field(default=8080, gt=0, lt=65536)


class RoleSettings(Configured):
    master: RoleConfig = RoleConfig(model="opus", effort="high")
    narrator: RoleConfig = RoleConfig(model="sonnet", effort="low", timeout=120.0)
    # A whole scene from the source, the cast and the history: measured at 335 seconds.
    worldsmith: RoleConfig = RoleConfig(model="sonnet", timeout=900.0)
    # One choice from a short, exact prompt: the smallest model, and a battle turn waits on it.
    opponent: RoleConfig = RoleConfig(model="haiku", effort="low", timeout=120.0)

    def for_name(self, name: Role) -> RoleConfig:
        return {
            "master": self.master,
            "narrator": self.narrator,
            "worldsmith": self.worldsmith,
            "opponent": self.opponent,
        }[name]


class Providers(Configured):
    openrouter: ProviderConfig = ProviderConfig(
        base_url="https://openrouter.ai/api/v1",
        api_key=SecretStr(""),
    )
    local: ProviderConfig = ProviderConfig(
        base_url="http://localhost:11434/v1",
        api_key=SecretStr("none"),
    )

    def for_name(self, name: ProviderName) -> ProviderConfig:
        return {"openrouter": self.openrouter, "local": self.local}[name]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        extra="ignore",
        env_nested_delimiter="__",
        nested_model_default_partial_update=True,
        frozen=True,
    )

    providers: Providers = Providers()
    roles: RoleSettings = RoleSettings()
    media: MediaConfig = MediaConfig()
    battle: BattleConfig = BattleConfig()
    transcript: TranscriptConfig = TranscriptConfig()
    server: ServerConfig = ServerConfig()
    saves_dir: Path = Path("saves")
    scenarios_dir: Path = Path("user/scenarios")
    characters_dir: Path = Path("user/characters")
    packs_dir: Path = Path("packs")

    @model_validator(mode="after")
    def _keys_present(self) -> Self:
        posting: list[tuple[str, ProviderName]] = (
            [("media", self.media.provider)] if self.media.enabled else []
        )
        roles: tuple[Role, ...] = ("master", "narrator", "worldsmith", "opponent")
        for role in roles:
            config = self.roles.for_name(role)
            if config.provider in ("openrouter", "local"):
                posting.append((role, config.provider))
        for what, name in posting:
            if not self.providers.for_name(name).api_key:
                raise ValueError(f"{what} uses provider {name!r}, which has no api_key")
        return self


def read_settings() -> Settings:
    return parse(Settings, {})


def env_key(path: tuple[str, ...]) -> str:
    return "__".join(path).upper()


def save_settings(changed: Mapping[tuple[str, ...], str | None]) -> None:
    """`set_key` rewrites one line in place, so comments and untouched keys survive."""
    for path, value in changed.items():
        if value is None:
            unset_key(ENV_FILE, env_key(path))
        else:
            set_key(ENV_FILE, env_key(path), value)
