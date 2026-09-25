"""Home page, launcher pairing, bad routes."""

import sys
from pathlib import Path

from playwright.sync_api import Page

sys.path.insert(0, str(Path(__file__).parent))
from drive import BASE, Session, clean, run


def pick(page: Page, label: str, option: str) -> None:
    page.locator(f".q-select:has(.q-field__label:text-is('{label}'))").click()
    page.locator(".q-menu .q-item", has_text=option).first.click()
    page.wait_for_timeout(300)


def body(s: Session) -> None:
    page = s.page()
    page.goto(BASE + "/")
    page.wait_for_timeout(1000)
    text = clean(page.inner_text("body"))
    s.check("Begin an adventure" in text, "home heading missing")
    s.check("No saved games yet." in text, "empty saves line missing")
    page.locator(".q-select").first.click()
    options = [clean(t) for t in page.locator(".q-menu .q-item").all_inner_texts()]
    s.note(f"scenario options: {options}")
    s.check(len(options) == 4, f"expected 4 scenarios, saw {options}")
    page.keyboard.press("Escape")
    pick(page, "Scenario", "The Whispering Vault")
    text = clean(page.inner_text("body"))
    s.check("LONER 3E" in text, "rules badge did not follow the scenario")
    s.check("Kael — A scarred" in text, "character not re-paired for the new rules")
    s.shot(page, "home-loner")
    # A bad route: the page function raises a Refusal; what does the player see?
    for path in ("/game/nope/kael", "/game/whispering-vault/nobody", "/game/Bad Id/kael"):
        page.goto(BASE + path)
        page.wait_for_timeout(800)
        body_text = clean(page.inner_text("body"))
        s.note(f"{path}: {body_text[:200]}")
        s.check(
            "500" not in body_text and "Internal Server Error" not in body_text,
            f"{path} shows a server error page: {body_text[:120]}",
        )
        s.shot(page, "bad-route")
    page.goto(BASE + "/")
    page.get_by_role("button", name="Settings").click()
    page.wait_for_url("**/settings")
    s.check(page.url.endswith("/settings"), "settings button did not navigate")
    page.goto(BASE + "/")
    page.get_by_role("button", name="New character").click()
    page.wait_for_url("**/create")
    page.goto(BASE + "/")
    page.get_by_role("button", name="New scenario").click()
    page.wait_for_url("**/scenario")
    s.shot(page, "scenario-page")


run("home", body)
