"""The settings page: tabs, no-op save, the speech voices, a real save, validation, and a game
that keeps playing."""

import os
import sys
from pathlib import Path

from playwright.sync_api import Locator, Page

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    Session,
    clean,
    held,
    notifications,
    notified,
    placeholder,
    run,
    still,
    submit,
    wait_idle,
    wait_until,
    wait_working,
    working,
)

WORK = Path(os.environ.get("QA_WORK", "/tmp/rulehall-qa-work"))
# The game page looks for scene art every 3 s.
ART_POLL_MS = 3200


def switch(page: Page, label: str) -> Locator:
    return page.locator(".q-toggle", has_text=label)


def env() -> str:
    return (WORK / ".env").read_text() if (WORK / ".env").exists() else ""


def save(page: Page) -> bool:
    """Press Save; returns whether `.env` changed."""
    before = env()
    page.get_by_role("button", name="Save").click()
    return wait_until(page, lambda: env() != before)


def field(page: Page, label: str) -> Locator:
    return page.locator(".q-tab-panel .q-field", has_text=label).first.locator("input")


def body(s: Session) -> None:
    page = s.page()
    page.goto(BASE + "/settings")
    still(page)
    s.shot(page, "settings")
    tabs = [clean(t).lower() for t in page.locator(".q-tab").all_inner_texts()]
    s.note(f"tabs: {tabs}")
    s.check(
        tabs == ["providers", "roles", "media", "speech", "pokemon", "server"],
        f"unexpected tabs: {tabs}",
    )
    page.get_by_role("button", name="Save").click()
    s.check(notified(page, "Nothing changed."), f"no-op save: {notifications(page)}")

    # Speech tab: the model select shows the chosen model's voices from the catalogue.
    page.get_by_role("tab", name="speech").click()
    voices = page.locator(".q-tab-panel", has_text="Narrator:")
    voices.wait_for()
    s.check("Narrator: bm_george" in clean(voices.inner_text()), "the Kokoro voices are missing")
    page.locator(".q-tab-panel .q-field", has_text="speech model").first.click()
    page.get_by_role("option", name="minimax/speech-2.8-turbo").click()
    s.check(
        wait_until(page, lambda: "English_radiant_girl" in clean(voices.inner_text())),
        "picking MiniMax did not show its voices",
    )
    still(page)
    s.shot(page, "speech-voices")
    page.reload()

    # Roles tab: the nested expansions and the provider select.
    page.get_by_role("tab", name="roles").click()
    master = page.locator(".q-expansion-item", has_text="master").first
    master.wait_for()
    s.shot(page, "roles")
    master.locator(".q-item").first.click()
    field(page, "timeout").wait_for()
    still(page)
    s.shot(page, "roles-master")
    roles = clean(page.locator(".q-tab-panels").inner_text())
    s.check(
        "provider" in roles and "model" in roles and "effort" in roles,
        f"master fields: {roles[:300]}",
    )

    # A number out of range: validation refuses the save.
    field(page, "timeout").fill("0")
    page.get_by_role("button", name="Save").click()
    refused = notified(page, "greater than 0")
    s.shot(page, "invalid-timeout")
    s.check(refused, f"invalid timeout not refused: {notifications(page)}")
    s.check(
        not (WORK / ".env").exists() or "TIMEOUT=0" not in (WORK / ".env").read_text(),
        ".env written despite invalid settings",
    )
    page.reload()

    # Media enabled without a key: the model validator refuses.
    page.get_by_role("tab", name="media").click()
    switch(page, "enabled").click()
    page.get_by_role("button", name="Save").click()
    s.check(notified(page, "api_key"), f"media without a key not refused: {notifications(page)}")
    s.shot(page, "media-no-key")
    page.reload()

    # A real change: music off. .env holds the key; the switch still shows it clicked.
    page.get_by_role("tab", name="pokemon").click()
    switch(page, "music").click()
    save(page)
    s.check("POKEMON__MUSIC='false'" in env(), f".env after save: {env()!r}")
    s.check(
        switch(page, "music").get_attribute("aria-checked") == "false",
        "the switch does not show the saved value after the reload",
    )
    s.shot(page, "music-off")

    # A secret: typed once, stored, never read back.
    page.get_by_role("tab", name="providers").click()
    page.locator(".q-expansion-item", has_text="openrouter").first.locator(".q-item").first.click()
    key_box = field(page, "api key")
    key_box.wait_for()
    still(page)
    s.shot(page, "providers-open")
    s.check(
        key_box.get_attribute("placeholder") == "not set",
        f"key placeholder: {key_box.get_attribute('placeholder')!r}",
    )
    key_box.fill("sk-test-123")
    save(page)
    s.check("PROVIDERS__OPENROUTER__API_KEY='sk-test-123'" in env(), f".env after key: {env()!r}")
    page.get_by_role("tab", name="providers").click()
    page.locator(".q-expansion-item", has_text="openrouter").first.locator(".q-item").first.click()
    still(page)
    s.shot(page, "key-stored")

    # Media can now be enabled (the key is there); its model default appears.
    page.get_by_role("tab", name="media").click()
    switch(page, "enabled").click()
    save(page)
    s.check("MEDIA__ENABLED='true'" in env(), f"media enable: {env()!r}")

    # A game mid-turn: a save elsewhere does not disturb it.
    game = s.page()
    game.goto(BASE + "/game/whispering-vault/kael")
    wait_idle(game, timeout=60)
    s.shot(game, "game-after-settings")
    s.note(
        f"game state: placeholder={placeholder(game)!r} "
        f"working={working(game).count()} notes={notifications(game)}"
    )
    with held("narrator"):
        submit(game, "I linger.\n!none")
        s.check(wait_working(game), "the game shows no turn under way")
        s.shot(game, "game-busy")
        page.get_by_role("tab", name="pokemon").click()
        switch(page, "music").click()
        s.check(save(page), "a save during a turn wrote nothing")
        s.shot(page, "busy-save")
    wait_idle(game, timeout=60)
    page.reload()
    page.get_by_role("tab", name="pokemon").click()

    # A save applies elsewhere while a game is open: the game keeps playing, untouched.
    switch(page, "music").click()
    save(page)
    s.shot(game, "stale-game")
    submit(game, "I try to play on.")
    wait_idle(game)
    s.check(
        "I try to play on." in clean(game.inner_text(".game-transcript")),
        "the game did not keep playing after a settings save elsewhere",
    )

    # Illustration enabled: the game page runs the media poll; art requests fail quietly.
    game.wait_for_timeout(ART_POLL_MS)
    s.shot(game, "media-on")


run("settings", body)
