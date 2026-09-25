"""The Tern Isles (Pokemon), the heaviest game page: the Team tab, a row dialog, the map, turns
with their traffic, and a wild battle."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    Session,
    SocketTraffic,
    cards,
    clean,
    drawer_text,
    run,
    submit,
    wait_idle,
)

GAME = BASE + "/game/tern-isles/kael"
SETUP_HINT = "battle simulator is not installed"
TURNS = (
    '!check what="Climb the sea wall" skill=athletics difficulty=easy',
    "!move to_id=tern-harbour",
    "!gain_money amount=200",
    '!check what="Spot the ferry" skill=perception difficulty=easy',
    "!buy item_id=potion count=1",
    "!move to_id=harbour-road",
    "!gain_item item_id=poke-ball count=1",
    '!check what="Calm the Wingull" skill=nature difficulty=hard',
    "I look along the road for tracks.",
    "!heal_team",
)


def body(s: Session) -> None:
    page = s.page()
    traffic = SocketTraffic(page)
    page.goto(GAME)
    wait_idle(page, timeout=40)
    submit(page, "I check my bag.\n!gain_item item_id=potion count=2")
    wait_idle(page)

    # The Team tab: the rail names it, and it holds Team, Box and Bag.
    team_tab = page.locator(".game-rail-btn", has_text="Team")
    s.check(team_tab.count() == 1, "the rail shows no Team tab")
    team_tab.click()
    page.wait_for_timeout(800)
    side = clean(drawer_text(page)).lower()
    for title in ("team", "box", "bag"):
        s.check(title in side, f"the Team tab shows no {title}: {side[:300]}")
    s.shot(page, "team-tab")

    # A Team row opens its dialog; the Potion on a full-HP Pokemon is greyed with its reason.
    page.locator(".game-drawer .game-opens", has_text="Charmander").first.click()
    page.wait_for_timeout(800)
    dialog = page.locator(".q-dialog")
    potion = dialog.locator("button.game-choice", has_text="Use the Potion on Charmander")
    s.check(potion.count() == 1, f"no Potion option: {clean(dialog.inner_text())[:300]}")
    if potion.count() == 1:
        s.check(potion.is_disabled(), "the Potion on a full-HP Pokemon is not greyed")
        s.check(
            "already has full HP" in potion.inner_text(),
            f"the greyed Potion gives no reason: {clean(potion.inner_text())}",
        )
    s.shot(page, "team-row")
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)

    # The map on the Scene tab, which stays open for the turns.
    traffic.mark()
    page.locator(".game-rail-btn", has_text="Scene").click()
    page.wait_for_timeout(800)
    s.note(f"timing pokemon open=scene-tab {traffic.mark().line()}")
    s.check(page.locator(".game-drawer canvas").count() > 0, "the Scene tab draws no map")

    # Marks sit only after an idle page, so frames that land late count toward the next turn.
    for turn, script in enumerate(TURNS, start=1):
        submit(page, f"Turn {turn} of pokemon.\n{script}")
        wait_idle(page, timeout=60)
        s.note(f"timing pokemon turn={turn} {traffic.mark().line()}")
        if turn == 1:
            s.check(
                any("vs DC" in card for card in cards(page)),
                f"the check drew no roll card: {cards(page)[-3:]}",
            )
    s.shot(page, "turns")

    # A wild battle: the banner, then the battle screen or, without the simulator, the hint.
    submit(page, "I step into the tall grass.\n!start_wild_battle")
    banner = page.locator(".game-banner", has_text="A battle waits for you.")
    banner.wait_for(timeout=40000)
    banner.get_by_role("button", name="Battle").click()
    hint = page.locator(".q-notification__message", has_text=SETUP_HINT)
    choice = page.locator(".game-battle .game-choice:visible")
    hint.or_(choice).first.wait_for(timeout=40000)
    hinted = hint.count() > 0
    choices = choice.count()
    s.note(f"battle: {'setup hint' if hinted else f'battle screen, {choices} choices'}")
    s.check(hinted or choices > 0, "Battle showed neither the battle screen nor the setup hint")
    s.shot(page, "battle")


run("pokemon", body)
