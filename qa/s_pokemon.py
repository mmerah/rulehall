"""The Tern Isles (Pokemon), the heaviest game page: a trainer made with a challenge, the Team
tab, a row dialog, the map and the rival, turns with their traffic, a Center heal, a nickname,
a wild battle, and the evil team: the first operation foiled, the next one lost to a badge, two
more lost to their leaders, and the lair the scripted worldsmith writes."""

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import Page

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    Session,
    SocketTraffic,
    cards,
    clean,
    composer,
    decision,
    drawer_text,
    log,
    notifications,
    run,
    select,
    submit,
    text,
    wait_idle,
    wait_working,
)

GAME = BASE + "/game/tern-isles/kael"
SETUP_HINT = "battle simulator is not installed"
CANDIES = 25
CANDY_ROUNDS = 6
TURNS = (
    '!check what="Climb the sea wall" skill=athletics difficulty=easy',
    "!move to_id=tern-harbour",
    "!gain_money amount=200",
    '!check what="Spot the ferry" skill=perception difficulty=easy',
    "!buy item_id=potion count=1",
    "!move to_id=pokemon-center",
    "!heal_team",
    "!move to_id=tern-harbour",
    "!move to_id=harbour-road",
    "!gain_item item_id=poke-ball count=1",
    '!check what="Calm the Wingull" skill=nature difficulty=hard',
    "I look along the road for tracks.",
)


def create_trainer(s: Session, page: Page) -> None:
    """The challenge is a creation step after the starter; each option says what it changes."""
    page.goto(BASE + "/create")
    page.wait_for_timeout(1000)
    select(page, "Rules", "POKEMON")
    text(page, "Name", "Nuzla")
    text(page, "Brief", "A careful trainer.")
    for number, skill in enumerate(("Athletics", "Nature", "Perception", "Lore"), start=1):
        select(page, f"Skill rank {number}", skill)
    select(page, "Starter", "Squirtle")
    page.locator(".q-select:has(.q-field__label:text-is('Challenge'))").first.click()
    page.wait_for_timeout(200)
    offered = [clean(t) for t in page.locator(".q-menu .q-item").all_inner_texts()]
    s.check(
        any("Nuzlocke" in o and "one catch per place" in o for o in offered)
        and any("Hard" in o and "level caps" in o for o in offered),
        f"the challenge step offers: {offered}",
    )
    page.locator(".q-menu .q-item", has_text="Nuzlocke").first.click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="Ethan").click()
    page.wait_for_timeout(400)
    s.shot(page, "create-challenge")
    page.get_by_role("button", name="Create").click()
    page.wait_for_url("**/")
    s.check(not notifications(page), f"creating a Nuzlocke trainer: {notifications(page)}")


def body(s: Session) -> None:
    page = s.page()
    create_trainer(s, page)
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
    s.check("Tamsin" in drawer_text(page), "the rival Tamsin is not here at the start")

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
    s.check(
        any("Team healed" in card for card in cards(page)),
        f"the Pokemon Center did not heal: {cards(page)[-6:]}",
    )

    # A nickname: the card says it, and the Team tab names the Pokemon by it.
    submit(page, "I call my Charmander Blaze.\n!nickname mon_id=charmander name=Blaze")
    wait_idle(page, timeout=60)
    s.check(
        any("Charmander is now called Blaze" in card for card in cards(page)),
        f"the nickname drew no card: {cards(page)[-3:]}",
    )
    page.locator(".game-rail-btn", has_text="Team").click()
    page.wait_for_timeout(800)
    s.check("Blaze" in drawer_text(page), "the Team tab does not show the nickname")
    s.shot(page, "nickname")
    page.locator(".game-rail-btn", has_text="Scene").click()
    page.wait_for_timeout(400)

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
    if hinted:
        s.note("scheme: skipped, the battle simulator is not installed")
        return
    choice.filter(has_text="Run").first.click()
    wait_idle(page, timeout=60)
    scheme(s, page)


def scheme(s: Session, page: Page) -> None:
    # Candies make Charmander strong enough to beat Vesper and Ines with Dragon Breath. A new
    # move to learn pauses every tool, so the candies go in rounds with the answers between.
    submit(page, f"Mira hands me candies.\n!gain_item item_id=rare-candy count={CANDIES}")
    wait_idle(page, timeout=60)
    candies = "\n".join(["!use_item item_id=rare-candy mon_id=charmander"] * CANDIES)
    for feeding in range(CANDY_ROUNDS):
        submit(page, f"I feed Blaze candies ({feeding}).\n{candies}")
        wait_idle(page, timeout=120)
        answer_decisions(page)

    # The first operation: beating its leader foils it and tells the first stage.
    submit(
        page,
        "I follow the grunts to the cove.\n!move to_id=gull-cove\n!reveal target_id=vesper\n"
        "!start_battle trainer_id=vesper",
    )
    wait_idle(page, timeout=60)
    fight(s, page, "Dragon Breath", "foiled")
    s.check(
        any("opens the old sea caves" in card for card in cards(page)),
        f"beating Vesper told no stage: {cards(page)[-6:]}",
    )
    s.check("Team Undertow" in drawer_text(page), "the Scene tab shows no Team Undertow panel")

    # The next region carries the owed operation; a badge earned while it is open makes it succeed.
    first_id, _ = more_map(s, page, "Out past the cove.", "write `operation`")
    submit(
        page,
        "I head for the gym.\n!move to_id=tern-harbour\n!unlock_way to_id=tern-gym\n"
        "!move to_id=tern-gym\n!reveal target_id=ines\n!start_battle trainer_id=ines",
    )
    wait_idle(page, timeout=60)
    fight(s, page, "Dragon Breath", "badge")
    s.check(
        any("frozen shrine" in card for card in cards(page)),
        f"the badge made no operation succeed: {cards(page)[-8:]}",
    )
    walk = "\n".join(
        f"!move to_id={place_id}" for place_id in ("tern-harbour", "gull-cove", first_id)
    )
    submit(page, f"Back to the cove.\n{walk}")
    wait_idle(page, timeout=60)

    # Two more operations succeed as the player loses to their leaders; then the lair is written.
    for number in (3, 4):
        room_id, leader_id = more_map(s, page, f"On to operation {number}.", "write `operation`")
        submit(
            page,
            f"I face the chief.\n!move to_id={room_id}\n!reveal target_id={leader_id}\n"
            f"!start_battle trainer_id={leader_id}",
        )
        wait_idle(page, timeout=60)
        fight(s, page, "Forfeit", f"lost-{number}")
    lair_id, _ = more_map(s, page, "To the lair.", "holds the team's lair")
    submit(page, f"Into the lair.\n!move to_id={lair_id}")
    wait_idle(page, timeout=60)
    master = [entry for entry in log() if entry["role"] == "master"][-1]["prompt"]
    s.check(
        "stage 4/4, foiled 1, succeeded 3" in master and "the boss is" in master,
        "THE SCHEME does not show the lair",
    )
    s.shot(page, "lair")


def answer_decisions(page: Page) -> None:
    for _ in range(12):
        pending = decision(page)
        if not pending.count():
            return
        for wanted in ("Forget Growl", "Skip", ""):
            button = pending.locator("button", has_text=wanted)
            if button.count():
                button.first.click()
                break
        wait_working(page, timeout=2)
        wait_idle(page, timeout=60)


def fight(s: Session, page: Page, pick: str, shot: str) -> None:
    banner = page.locator(".game-banner", has_text="A battle waits for you.")
    banner.wait_for(timeout=40000)
    banner.get_by_role("button", name="Battle").click()
    screen = page.locator(".game-battle:visible")
    choices = page.locator(".game-battle .game-choice:visible:enabled")
    choices.first.wait_for(timeout=40000)
    deadline = time.time() + 240
    while screen.count() and time.time() < deadline:
        wanted = choices.filter(has_text=pick)
        if choices.count():
            (wanted if wanted.count() else choices).first.click()
        page.wait_for_timeout(700)
    s.check(not screen.count(), f"the {shot} battle never ended")
    wait_idle(page, timeout=60)
    s.shot(page, shot)
    answer_decisions(page)


def more_map(s: Session, page: Page, words: str, asked: str) -> tuple[str, str]:
    offered = page.locator(".game-banner button", has_text="More map")
    s.check(offered.count() == 1, f"no More map offered before: {words}")
    composer(page).fill(words)
    offered.click()
    wait_working(page)
    wait_idle(page, timeout=60)
    smith = [entry for entry in log() if entry["role"] == "worldsmith"][-1]
    s.check(asked in smith["prompt"], f"the region request did not ask: {asked}")
    region = json.loads(smith["answer"])
    return str(region["start_id"]), str(next(iter(region["npcs"])))


run("pokemon", body)
