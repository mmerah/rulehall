"""Character creation for every engine, scenario creation, and the lobby and hall afterwards."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    Session,
    clean,
    notifications,
    notified,
    run,
    select,
    shows,
    still,
    text,
    wait_idle,
    wait_until,
)

SOURCE = Path(__file__).parents[1] / "tests/core/fixtures/source/drowned-road.md"


def body(s: Session) -> None:
    page = s.page()
    page.goto(BASE + "/rules/loner4e/character")
    still(page)
    s.shot(page, "create")
    s.check("LONER 4E" in clean(page.inner_text("body")), "the route's rules not shown")

    # Tunnel Goons: the abilities and three items.
    page.goto(BASE + "/rules/tunnelgoons/character")
    still(page)
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
    shows(page, "exactly 3 points")
    body_text = clean(page.inner_text("body"))
    s.check(
        "Not ready yet" in body_text and "exactly 3 points" in body_text,
        f"4 points not refused in the preview: {body_text[-300:]}",
    )
    s.check(page.get_by_role("button", name="Create").count() == 0, "Create offered on 4 points")
    select(page, "Points in Brute", "1")
    s.check(
        wait_until(page, lambda: page.get_by_role("button", name="Create").count() == 1),
        "no Create button once legal",
    )
    s.shot(page, "goons-legal")
    page.get_by_role("button", name="Create").click()
    page.wait_for_url("**/rules/tunnelgoons?character=quinn")
    s.check("Quinn" in clean(page.inner_text(".game-chip-on")), "the hall did not select Quinn")
    s.shot(page, "hall-quinn")

    # The same name again is refused; an empty name is refused before anything runs.
    page.goto(BASE + "/rules/tunnelgoons/character")
    text(page, "Name", "Quinn")
    for ability, points in (("Brute", "1"), ("Skulker", "1"), ("Erudite", "1")):
        select(page, f"Points in {ability}", points)
    for n in range(1, 4):
        text(page, f"Item {n}", f"Thing {n}")
    page.get_by_role("button", name="Create").click()
    s.check(notified(page, "already exists"), f"duplicate not refused: {notifications(page)}")
    text(page, "Name", "")
    page.get_by_role("button", name="Create").click()
    s.check(notified(page, "Name the character."), "empty name not refused")

    # Loner: a chosen pack, then dependent skill and gear picks pooled over the SRD and it.
    page.goto(BASE + "/rules/loner4e/character")
    text(page, "Name", "Wren")
    select(page, "Pack", "AP01 Fantasy")
    page.keyboard.press("Escape")
    s.shot(page, "loner-pack")
    text(page, "Write a one-line concept", "A quiet scout")
    text(page, "What does your character want?", "Out")
    s.check(
        page.get_by_placeholder("Leave empty to let play decide").count() == 3,
        "goal, motive and nemesis do not say they may stay empty",
    )
    select(page, "Choose skill 1", "Quiet Hands")
    page.locator(".q-select", has_text="Choose skill 2").first.click()
    page.locator(".q-menu .q-item").first.wait_for()
    skills2 = [clean(t) for t in page.locator(".q-menu .q-item").all_inner_texts()]
    s.check("Quiet Hands" not in " ".join(skills2), "skill 2 offers skill 1 again")
    page.locator(".q-menu .q-item", has_text="Reads Old Stonework").first.click()
    page.locator(".q-menu").wait_for(state="detached")
    select(page, "Choose a frailty", "Never Walks Away")
    select(page, "Choose gear 1", "Pry Bar")
    select(page, "Choose gear 2", "Chalk and Wire")
    shows(page, "Quiet Hands, Reads Old Stonework")
    s.shot(page, "loner-filled")
    preview = clean(page.inner_text("body"))
    s.check(
        "Quiet Hands, Reads Old Stonework" in preview, f"preview missing skills: {preview[-400:]}"
    )
    page.get_by_role("button", name="Create").click()
    page.wait_for_url("**/rules/loner4e?character=wren")

    # 24XX: a specialty with a choice and a weapon, an origin with a body and an increase.
    page.goto(BASE + "/rules/twentyfourxx/character")
    text(page, "Name", "Wren")
    select(page, "Specialty", "Muscle")
    select(page, "Specialty skill", "Hand-to-hand")
    select(page, "Weapon", "Sword")
    select(page, "Origin", "Android")
    select(page, "Body", "Case")
    select(page, "Skill increase", "Piloting")
    shows(page, "Piloting d8")
    s.shot(page, "24xx-filled")
    preview = clean(page.inner_text("body"))
    s.check(
        "Hand-to-hand d8" in preview and "Piloting d8" in preview, f"24xx preview: {preview[-500:]}"
    )
    page.get_by_role("button", name="Create").click()
    page.wait_for_url("**/rules/twentyfourxx?character=wren")
    s.check(
        (
            Path(__import__("os").environ.get("QA_WORK", "/tmp/rulehall-qa-work"))
            / "characters/wren"
        ).is_dir(),
        "wren folder missing",
    )

    # The 24XX hall offers Wren beside Kael, and never the Tunnel Goons Quinn.
    cast = [clean(t) for t in page.locator(".game-chip").all_inner_texts()]
    s.check(
        any("Wren" in c for c in cast) and not any("Quinn" in c for c in cast),
        f"24xx characters: {cast}",
    )
    s.check("The Silent Relay" in clean(page.inner_text("body")), "24xx hall lacks its adventure")

    # A scenario: the guard, then a written opening that lands on the game page.
    page.goto(BASE + "/rules/loner4e/scenario")
    still(page)
    s.shot(page, "scenario")
    page.get_by_role("button", name="Write the opening").click()
    s.check(
        notified(page, "A title, a backdrop, a scope"), f"scenario guard: {notifications(page)}"
    )
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
    page.goto(BASE + "/rules/tunnelgoons/scenario")
    s.check(
        page.locator(".q-select", has_text="Pack").count() == 0,
        "a room engine offers packs",
    )
    text(page, "Title", "The Sunken Bell")
    text(page, "Backdrop", "A drowned coast of bells and ferries.")
    text(page, "Scope", "One crossing.")
    page.locator("input[type=file]").set_input_files(str(SOURCE))
    s.check(
        notified(page, "Read drowned-road.md"), f"upload not acknowledged: {notifications(page)}"
    )
    s.shot(page, "scenario-upload")
    page.get_by_role("button", name="Write the opening").click()
    page.wait_for_url("**/game/the-sunken-bell-2/**", timeout=60000)
    wait_idle(page, timeout=60)
    s.check("QA Room" in clean(page.inner_text(".game-scene")), "the written map is not the scene")
    s.shot(page, "scenario-map-game")

    # The lobby continues the newest save; the hall continues a started game by its turn.
    page.goto(BASE + "/")
    still(page)
    s.shot(page, "home-saves")
    home = clean(page.inner_text("body"))
    s.check("The Sunken Bell" in home and "turn 1" in home, f"saves: {home[:600]}")
    page.goto(BASE + "/rules/loner4e")
    s.check(
        page.get_by_role("button", name="Continue · turn 1").count() == 1,
        "the hall offers no Continue for the started game",
    )
    page.goto(BASE + "/")
    page.locator(".game-hero").get_by_role("button", name="Continue").click()
    page.wait_for_url("**/game/**")
    s.check("/game/" in page.url, "the lobby's Continue did not open the game")


run("create", body)
