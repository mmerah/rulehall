"""Lobby, engine hall, the taps to a game, bad routes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from drive import BASE, Session, clean, run, still, submit, wait_idle


def body(s: Session) -> None:
    page = s.page()
    page.goto(BASE + "/")
    still(page)
    text = clean(page.inner_text("body"))
    s.check("Choose your rules" in text, "lobby rules heading missing")
    s.check(page.locator(".game-hero").count() == 0, "a Continue hero with no save")
    doors = [clean(t) for t in page.locator(".game-door .game-door-title").all_inner_texts()]
    s.check(len(doors) == 4, f"expected 4 rule doors, saw {doors}")
    s.shot(page, "lobby-empty")

    # First game: a door, then Start.
    page.locator(".game-door", has_text="LONER 4E").click()
    page.wait_for_url("**/rules/loner4e")
    hall = clean(page.inner_text("body"))
    s.check("Play as" in hall and "Kael" in hall, f"hall cast: {hall[:300]}")
    s.check("The Whispering Vault" in hall, "the hall does not list its adventure")
    s.check("TUNNEL GOONS" not in hall, "the hall lists another engine's content")
    s.shot(page, "hall-loner")
    page.get_by_role("button", name="Start").first.click()
    page.wait_for_url("**/game/whispering-vault/kael")
    wait_idle(page, timeout=40)
    submit(page, "I look around.")
    wait_idle(page)

    # Continue: one tap on the lobby hero.
    page.goto(BASE + "/")
    still(page)
    hero = clean(page.inner_text(".game-hero"))
    s.check("The Whispering Vault" in hero and "Kael" in hero, f"hero: {hero}")
    s.shot(page, "lobby-continue")
    page.locator(".game-hero").get_by_role("button", name="Continue").click()
    page.wait_for_url("**/game/whispering-vault/kael")
    page.goto(BASE + "/rules/loner4e")
    s.check(
        page.get_by_role("button", name="Continue · turn").count() == 1,
        "the hall does not continue the started game",
    )

    # A bad route: the page function refuses; what does the player see?
    for path in (
        "/game/nope/kael",
        "/game/whispering-vault/nobody",
        "/game/Bad Id/kael",
        "/rules/nope",
        "/rules/nope/character",
    ):
        page.goto(BASE + path)
        still(page)
        body_text = clean(page.inner_text("body"))
        s.note(f"{path}: {body_text[:200]}")
        s.check(
            "500" not in body_text and "Internal Server Error" not in body_text,
            f"{path} shows a server error page: {body_text[:120]}",
        )
        s.shot(page, "bad-route")
    s.check("no rules 'nope'" in clean(page.inner_text("body")), "an unknown engine not refused")

    page.goto(BASE + "/")
    page.get_by_role("button", name="Settings").click()
    page.wait_for_url("**/settings")
    s.check(page.url.endswith("/settings"), "settings button did not navigate")
    page.goto(BASE + "/rules/loner4e")
    page.get_by_role("button", name="New character").click()
    page.wait_for_url("**/rules/loner4e/character")
    page.goto(BASE + "/rules/loner4e")
    page.get_by_text("Write an adventure").click()
    page.wait_for_url("**/rules/loner4e/scenario")
    s.shot(page, "scenario-page")
    page.goto(BASE + "/rules/loner4e")
    page.locator(".game-small-link", has_text="Packs").click()
    page.wait_for_url("**/rules/loner4e/packs")
    s.shot(page, "packs-page")


run("home", body)
