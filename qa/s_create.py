"""Character creation for every engine, scenario creation, and the launcher afterwards."""

import sys
from pathlib import Path

from playwright.sync_api import Page

sys.path.insert(0, str(Path(__file__).parent))
from drive import BASE, Session, clean, notifications, run, wait_idle

SOURCE = Path(__file__).parents[1] / "tests/core/fixtures/source/drowned-road.md"


def select(page: Page, label: str, option: str) -> None:
    field = page.locator(f".q-select:has(.q-field__label:text-is('{label}'))").first
    field.click()
    page.wait_for_timeout(200)
    page.locator(".q-menu .q-item", has_text=option).first.click()
    page.wait_for_timeout(400)


def text(page: Page, label: str, value: str) -> None:
    box = page.locator(".q-field", has_text=label).first.locator("input, textarea").first
    box.fill(value)
    box.blur()
    page.wait_for_timeout(400)


def body(s: Session) -> None:
    page = s.page()
    page.goto(BASE + "/create")
    page.wait_for_timeout(1000)
    s.shot(page, "create")
    s.check("LONER 3E" in clean(page.inner_text("body")), "default rules not shown")

    # Tunnel Goons: the abilities and three items.
    select(page, "Rules", "TUNNEL GOONS")
    s.shot(page, "create-goons")
    if page.get_by_role("button", name="Create").count():
        s.check(False, "Create offered before the form is filled")
    text(page, "Name", "Quinn")
    text(page, "Brief", "A goon.")
    for ability, points in (("Brute", "2"), ("Skulker", "2"), ("Erudite", "0")):
        select(page, f"Points in {ability}", points)
    for n in range(1, 4):
        text(page, f"Item {n}", f"Thing {n}")
    s.shot(page, "goons-filled")
    body_text = clean(page.inner_text("body"))
    s.check(
        "Not ready yet" in body_text and "exactly 3 points" in body_text,
        f"4 points not refused in the preview: {body_text[-300:]}",
    )
    s.check(page.get_by_role("button", name="Create").count() == 0, "Create offered on 4 points")
    select(page, "Points in Brute", "1")
    page.wait_for_timeout(400)
    s.check(page.get_by_role("button", name="Create").count() == 1, "no Create button once legal")
    s.shot(page, "goons-legal")
    page.get_by_role("button", name="Create").click()
    page.wait_for_url("**/")
    s.check(page.url.rstrip("/") == BASE, "not sent home after creating")
    page.locator(".q-select", has_text="Character").click()
    options = [clean(t) for t in page.locator(".q-menu .q-item").all_inner_texts()]
    s.check(any("Quinn" in o for o in options), f"Quinn not offered on the launcher: {options}")
    page.keyboard.press("Escape")
    s.shot(page, "home-quinn")

    # The same name again is refused; an empty name is refused before anything runs.
    page.goto(BASE + "/create")
    page.wait_for_timeout(800)
    select(page, "Rules", "TUNNEL GOONS")
    text(page, "Name", "Quinn")
    for ability, points in (("Brute", "1"), ("Skulker", "1"), ("Erudite", "1")):
        select(page, f"Points in {ability}", points)
    for n in range(1, 4):
        text(page, f"Item {n}", f"Thing {n}")
    page.get_by_role("button", name="Create").click()
    page.wait_for_timeout(800)
    s.check(
        any("already exists" in n for n in notifications(page)),
        f"duplicate not refused: {notifications(page)}",
    )
    text(page, "Name", "")
    page.get_by_role("button", name="Create").click()
    page.wait_for_timeout(600)
    s.check(any("Name the character." in n for n in notifications(page)), "empty name not refused")

    # Loner: a chosen pack, then dependent skill and gear picks pooled over the SRD and it.
    page.goto(BASE + "/create")
    page.wait_for_timeout(800)
    text(page, "Name", "Wren")
    select(page, "Pack", "AP01 Fantasy")
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    s.shot(page, "loner-pack")
    text(page, "Write a one-line concept", "A quiet scout")
    text(page, "What does your character want?", "Out")
    text(page, "Why do they want it?", "Debt")
    select(page, "Choose skill 1", "Quiet Hands")
    page.locator(".q-select", has_text="Choose skill 2").first.click()
    page.wait_for_timeout(200)
    skills2 = [clean(t) for t in page.locator(".q-menu .q-item").all_inner_texts()]
    s.check("Quiet Hands" not in " ".join(skills2), "skill 2 offers skill 1 again")
    page.locator(".q-menu .q-item", has_text="Reads Old Stonework").first.click()
    page.wait_for_timeout(300)
    select(page, "Choose a frailty", "Never Walks Away")
    select(page, "Choose gear 1", "Pry Bar")
    select(page, "Choose gear 2", "Chalk and Wire")
    page.wait_for_timeout(400)
    s.shot(page, "loner-filled")
    preview = clean(page.inner_text("body"))
    s.check(
        "Quiet Hands, Reads Old Stonework" in preview, f"preview missing skills: {preview[-400:]}"
    )
    page.get_by_role("button", name="Create").click()
    page.wait_for_url("**/")

    # 24XX: a specialty with a choice and a weapon, an origin with a body and an increase.
    page.goto(BASE + "/create")
    page.wait_for_timeout(800)
    select(page, "Rules", "24XX")
    text(page, "Name", "Wren")
    select(page, "Specialty", "Muscle")
    select(page, "Specialty skill", "Hand-to-hand")
    select(page, "Weapon", "Sword")
    select(page, "Origin", "Android")
    select(page, "Body", "Case")
    select(page, "Skill increase", "Piloting")
    page.wait_for_timeout(400)
    s.shot(page, "24xx-filled")
    preview = clean(page.inner_text("body"))
    s.check(
        "Hand-to-hand d8" in preview and "Piloting d8" in preview, f"24xx preview: {preview[-500:]}"
    )
    page.get_by_role("button", name="Create").click()
    page.wait_for_url("**/")
    page.wait_for_timeout(600)
    s.check(
        (
            Path(__import__("os").environ.get("QA_WORK", "/tmp/rulehall-qa-work"))
            / "characters/wren"
        ).is_dir(),
        "wren folder missing",
    )

    # Home now pairs Wren with each scenario.
    page.locator(".q-select", has_text="Scenario").click()
    page.locator(".q-menu .q-item", has_text="The Silent Relay").first.click()
    page.wait_for_timeout(400)
    page.locator(".q-select", has_text="Character").click()
    options = [clean(t) for t in page.locator(".q-menu .q-item").all_inner_texts()]
    s.check(
        any("Wren" in o for o in options) and not any("Quinn" in o for o in options),
        f"24xx characters: {options}",
    )
    page.keyboard.press("Escape")

    # A scenario: the guard, then a written opening that lands on the game page.
    page.goto(BASE + "/scenario")
    page.wait_for_timeout(1000)
    s.shot(page, "scenario")
    page.get_by_role("button", name="Write the opening").click()
    page.wait_for_timeout(600)
    s.check(
        any("A title, a backdrop, a scope" in n for n in notifications(page)),
        f"scenario guard: {notifications(page)}",
    )
    select(page, "Rules", "LONER 3E")
    text(page, "Title", "The Sunken Bell")
    text(page, "Backdrop", "A drowned coast of bells and ferries.")
    text(page, "Premise", "The tide took the lower town.")
    text(page, "Scope", "One crossing.")
    text(page, "Art style", "woodcut")
    s.shot(page, "scenario-filled")
    page.get_by_role("button", name="Write the opening").click()
    page.wait_for_url("**/game/the-sunken-bell/**", timeout=60000)
    wait_idle(page, timeout=60)
    s.shot(page, "scenario-game")
    s.check(
        "QA Scene" in clean(page.inner_text(".game-scene")), "the written opening is not the scene"
    )
    s.check(
        "Scene 1, written" in clean(page.inner_text(".game-transcript"))
        or "[narration]" in clean(page.inner_text(".game-transcript")),
        "no opening narration on the new scenario",
    )

    # A scenario from an uploaded document, for a room engine, with the same title (slug -2).
    page.goto(BASE + "/scenario")
    page.wait_for_timeout(1000)
    select(page, "Rules", "TUNNEL GOONS")
    s.check(
        page.locator(".q-select", has_text="Pack").count() == 0,
        "a room engine offers packs",
    )
    text(page, "Title", "The Sunken Bell")
    text(page, "Backdrop", "A drowned coast of bells and ferries.")
    text(page, "Scope", "One crossing.")
    page.locator("input[type=file]").set_input_files(str(SOURCE))
    page.wait_for_timeout(1500)
    s.check(
        any("Read drowned-road.md" in n for n in notifications(page)),
        f"upload not acknowledged: {notifications(page)}",
    )
    s.shot(page, "scenario-upload")
    page.get_by_role("button", name="Write the opening").click()
    page.wait_for_url("**/game/the-sunken-bell-2/**", timeout=60000)
    wait_idle(page, timeout=60)
    s.check("QA Room" in clean(page.inner_text(".game-scene")), "the written map is not the scene")
    s.shot(page, "scenario-map-game")

    # The launcher lists the saves with turn counts and Continue.
    page.goto(BASE + "/")
    page.wait_for_timeout(1000)
    s.shot(page, "home-saves")
    home = clean(page.inner_text("body"))
    s.check("The Sunken Bell" in home and "turn 1" in home, f"saves list: {home[-600:]}")
    select(page, "Scenario", "The Sunken Bell · LONER 3E")
    s.check(
        page.get_by_role("button", name="Continue game").count() == 1,
        "Continue game label missing for a started game",
    )
    page.get_by_role("button", name="Resume").first.click()
    page.wait_for_url("**/game/**")
    s.check("/game/" in page.url, "resume did not open the game")


run("create", body)
