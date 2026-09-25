"""The settings page: tabs, no-op save, a real save, validation, and a game that keeps playing."""

import os
import sys
from pathlib import Path

from playwright.sync_api import Locator, Page

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    Session,
    clean,
    notifications,
    placeholder,
    run,
    submit,
    wait_idle,
    working,
)

WORK = Path(os.environ.get("QA_WORK", "/tmp/rulehall-qa-work"))


def switch(page: Page, label: str) -> Locator:
    return page.locator(".q-toggle", has_text=label)


def body(s: Session) -> None:
    page = s.page()
    page.goto(BASE + "/settings")
    page.wait_for_timeout(1200)
    s.shot(page, "settings")
    tabs = [clean(t).lower() for t in page.locator(".q-tab").all_inner_texts()]
    s.note(f"tabs: {tabs}")
    s.check(
        tabs == ["providers", "roles", "media", "battle", "server"],
        f"unexpected tabs: {tabs}",
    )
    page.get_by_role("button", name="Save").click()
    page.wait_for_timeout(600)
    s.check("Nothing changed." in notifications(page), f"no-op save: {notifications(page)}")

    # Roles tab: the nested expansions and the provider select.
    page.get_by_role("tab", name="roles").click()
    page.wait_for_timeout(500)
    s.shot(page, "roles")
    page.locator(".q-expansion-item", has_text="master").first.locator(".q-item").first.click()
    page.wait_for_timeout(500)
    s.shot(page, "roles-master")
    roles = clean(page.locator(".q-tab-panels").inner_text())
    s.check(
        "provider" in roles and "model" in roles and "effort" in roles,
        f"master fields: {roles[:300]}",
    )

    # A number out of range: validation refuses the save.
    timeout_box = page.locator(".q-tab-panel .q-field", has_text="timeout").first.locator("input")
    timeout_box.fill("0")
    page.get_by_role("button", name="Save").click()
    page.wait_for_timeout(800)
    s.shot(page, "invalid-timeout")
    notes = notifications(page)
    s.check(
        any("greater than 0" in n or "validation" in n.lower() for n in notes),
        f"invalid timeout not refused: {notes}",
    )
    s.check(
        not (WORK / ".env").exists() or "TIMEOUT=0" not in (WORK / ".env").read_text(),
        ".env written despite invalid settings",
    )
    page.reload()
    page.wait_for_timeout(1000)

    # Media enabled without a key: the model validator refuses.
    page.get_by_role("tab", name="media").click()
    page.wait_for_timeout(400)
    switch(page, "enabled").click()
    page.get_by_role("button", name="Save").click()
    page.wait_for_timeout(800)
    notes = notifications(page)
    s.check(any("api_key" in n for n in notes), f"media without a key not refused: {notes}")
    s.shot(page, "media-no-key")
    page.reload()
    page.wait_for_timeout(1000)

    # A real change: music off. .env holds the key; the switch still shows it clicked.
    page.get_by_role("tab", name="battle").click()
    page.wait_for_timeout(400)
    switch(page, "music").click()
    page.get_by_role("button", name="Save").click()
    page.wait_for_timeout(800)
    page.wait_for_timeout(2000)
    env = (WORK / ".env").read_text() if (WORK / ".env").exists() else ""
    s.check("BATTLE__MUSIC='false'" in env, f".env after save: {env!r}")
    s.check(
        switch(page, "music").get_attribute("aria-checked") == "false",
        "the switch does not show the saved value after the reload",
    )
    s.shot(page, "music-off")

    # A secret: typed once, stored, never read back.
    page.get_by_role("tab", name="providers").click()
    page.wait_for_timeout(400)
    page.locator(".q-expansion-item", has_text="openrouter").first.locator(".q-item").first.click()
    page.wait_for_timeout(500)
    s.shot(page, "providers-open")
    key_box = page.locator(".q-tab-panel .q-field", has_text="api key").first.locator("input")
    s.check(
        key_box.get_attribute("placeholder") == "not set",
        f"key placeholder: {key_box.get_attribute('placeholder')!r}",
    )
    key_box.fill("sk-test-123")
    page.get_by_role("button", name="Save").click()
    page.wait_for_timeout(2000)
    env = (WORK / ".env").read_text()
    s.check("PROVIDERS__OPENROUTER__API_KEY='sk-test-123'" in env, f".env after key: {env!r}")
    page.get_by_role("tab", name="providers").click()
    page.wait_for_timeout(400)
    page.locator(".q-expansion-item", has_text="openrouter").first.locator(".q-item").first.click()
    page.wait_for_timeout(500)
    s.shot(page, "key-stored")

    # Media can now be enabled (the key is there); its model default appears.
    page.get_by_role("tab", name="media").click()
    page.wait_for_timeout(400)
    switch(page, "enabled").click()
    page.get_by_role("button", name="Save").click()
    page.wait_for_timeout(2500)
    env = (WORK / ".env").read_text()
    s.check("MEDIA__ENABLED='true'" in env, f"media enable: {env!r}")

    # A game mid-turn: a save elsewhere does not disturb it.
    game = s.page()
    game.goto(BASE + "/game/whispering-vault/kael")
    game.wait_for_timeout(4000)
    s.shot(game, "game-after-settings")
    s.note(
        f"game state: placeholder={placeholder(game)!r} "
        f"working={working(game).count()} notes={notifications(game)}"
    )
    wait_idle(game, timeout=60)
    submit(game, "I linger.\n!slow narrator\n!none")
    game.wait_for_timeout(2500)
    s.shot(game, "game-busy")
    page.get_by_role("tab", name="battle").click()
    page.wait_for_timeout(400)
    switch(page, "music").click()
    page.get_by_role("button", name="Save").click()
    page.wait_for_timeout(800)
    s.shot(page, "busy-save")
    wait_idle(game, timeout=60)
    page.reload()
    page.wait_for_timeout(1000)
    page.get_by_role("tab", name="battle").click()
    page.wait_for_timeout(400)

    # A save applies elsewhere while a game is open: the game keeps playing, untouched.
    switch(page, "music").click()
    page.get_by_role("button", name="Save").click()
    page.wait_for_timeout(1500)
    s.shot(game, "stale-game")
    submit(game, "I try to play on.")
    wait_idle(game)
    s.check(
        "I try to play on." in clean(game.inner_text(".game-transcript")),
        "the game did not keep playing after a settings save elsewhere",
    )

    # Illustration enabled: the game page runs the media poll; art requests fail quietly.
    game.wait_for_timeout(3500)
    s.shot(game, "media-on")


run("settings", body)
