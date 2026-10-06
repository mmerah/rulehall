"""The Tern Isles (Pokemon), the heaviest game page: a trainer made with a challenge, the Team tab,
a row dialog, the map and the rival, who blocks the road until a lost battle, turns with their
traffic, a town heal, a nickname, a wild battle, and the evil team: the first operation foiled,
two badges before the next one, which a badge makes succeed, two more lost to their leaders two
badges apart, and the lair the scripted worldsmith writes."""

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import Page

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    PAGE_TICK_SECONDS,
    Session,
    SocketTraffic,
    cards,
    clean,
    decision,
    drawer_text,
    log,
    move,
    notifications,
    run,
    select,
    send_move,
    start_turn,
    submit,
    text,
    wait_idle,
    wait_server,
)

GAME = BASE + "/game/tern-isles/kael"
SETUP_HINT = "battle simulator is not installed"
CANDIES = 60
CANDY_ROUNDS = 16
TURNS = (
    '!check what="Climb the sea wall" skill=athletics difficulty=easy',
    "!move to_id=tern-harbour",
    "!gain_money amount=200",
    '!check what="Spot the ferry" skill=perception difficulty=easy',
    "!buy item_id=potion count=1",
    "!heal_team",
    "!move to_id=harbour-road",
    "!gain_item item_id=poke-ball count=1",
    '!check what="Calm the Wingull" skill=nature difficulty=hard',
    "I look along the road for tracks.",
)


def create_trainer(s: Session, page: Page) -> None:
    """The challenge is a creation step after the starter; each option says what it changes."""
    page.goto(BASE + "/rules/pokemon/character")
    text(page, "Name", "Nuzla")
    text(page, "Brief", "A careful trainer.")
    for number, skill in enumerate(("Athletics", "Nature", "Perception", "Lore"), start=1):
        select(page, f"Skill rank {number}", skill)
    select(page, "Starter", "Squirtle")
    page.locator(".q-select:has(.q-field__label:text-is('Challenge'))").first.click()
    page.locator(".q-menu .q-item").first.wait_for()
    offered = [clean(t) for t in page.locator(".q-menu .q-item").all_inner_texts()]
    s.check(
        any("Nuzlocke" in o and "one catch per place" in o for o in offered)
        and any("Hard" in o and "level caps" in o for o in offered),
        f"the challenge step offers: {offered}",
    )
    page.locator(".q-menu .q-item", has_text="Nuzlocke").first.click()
    page.locator(".q-menu").wait_for(state="detached")
    page.get_by_role("button", name="Ethan").click()
    s.shot(page, "create-challenge")
    page.get_by_role("button", name="Create").click()
    page.wait_for_url("**/rules/pokemon?character=nuzla")
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
    page.locator(".game-drawer", has_text="Bag").wait_for()
    side = clean(drawer_text(page)).lower()
    for title in ("team", "box", "bag"):
        s.check(title in side, f"the Team tab shows no {title}: {side[:300]}")
    s.shot(page, "team-tab")

    # A Team row opens its dialog; the Potion on a full-HP Pokemon is greyed with its reason.
    page.locator(".game-drawer .game-opens", has_text="Charmander").first.click()
    dialog = page.locator(".q-dialog")
    dialog.locator("button.game-choice").first.wait_for()
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
    dialog.wait_for(state="detached")

    # The map on the Scene tab, which stays open for the turns.
    traffic.mark()
    page.locator(".game-rail-btn", has_text="Scene").click()
    page.locator(".game-drawer canvas").first.wait_for()
    page.wait_for_timeout(PAGE_TICK_SECONDS * 1000)
    s.note(f"timing pokemon open=scene-tab {traffic.mark().line()}")
    s.check(page.locator(".game-drawer canvas").count() > 0, "the Scene tab draws no map")
    s.check("Tamsin" in drawer_text(page), "the rival Tamsin is not here at the start")

    # Before the first move the rival blocks every way, so a forfeit to Tamsin opens the road.
    submit(page, "Tamsin blocks the road.\n!start_battle trainer_id=tamsin")
    wait_idle(page, timeout=60)
    if not open_battle(page):
        s.shot(page, "battle")
        s.note("battle: setup hint; the rest is skipped, the battle simulator is not installed")
        return
    play_battle(s, page, "Forfeit", "rival")

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
        f"the town did not heal: {cards(page)[-6:]}",
    )

    # A nickname: the card says it, and the Team tab names the Pokemon by it.
    submit(page, "I call my Charmander Blaze.\n!nickname mon_id=charmander name=Blaze")
    wait_idle(page, timeout=60)
    s.check(
        any("Charmander is now called Blaze" in card for card in cards(page)),
        f"the nickname drew no card: {cards(page)[-3:]}",
    )
    page.locator(".game-rail-btn", has_text="Team").click()
    page.locator(".game-drawer", has_text="Bag").wait_for()
    s.check("Blaze" in drawer_text(page), "the Team tab does not show the nickname")
    s.shot(page, "nickname")
    page.locator(".game-rail-btn", has_text="Scene").click()
    page.locator(".game-drawer canvas").first.wait_for()

    # A wild battle: the banner, then the battle screen.
    submit(page, "I step into the tall grass.\n!start_wild_battle")
    s.check(open_battle(page), "the wild battle showed the setup hint")
    choice = page.locator(".game-battle .game-choice:visible")
    s.note(f"battle: battle screen, {choice.count()} choices")
    s.shot(page, "battle")
    choice.filter(has_text="Run").first.click()
    wait_idle(page, timeout=60)
    scheme(s, page)


def scheme(s: Session, page: Page) -> None:
    # Candies make Charmander strong enough to beat Vesper and every gym. A new move to learn
    # pauses every tool, so the candies go in rounds with the answers between.
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
        any("before they open the old sea caves" in card for card in cards(page)),
        f"beating Vesper told no stage: {cards(page)[-6:]}",
    )
    s.check(
        "team undertow" in drawer_text(page).lower(), "the Scene tab shows no Team Undertow panel"
    )

    # The gym is open, and no operation is owed before the player holds two badges.
    submit(
        page,
        "I head for the gym.\n!move to_id=tern-harbour\n!move to_id=tern-gym\n"
        "!reveal target_id=ines\n!start_battle trainer_id=ines",
    )
    wait_idle(page, timeout=60)
    fight(s, page, "Dragon Breath", "badge-1")
    earn_badge(s, page, "Out past the gym.")

    # The second operation opens at two badges; the next badge makes it succeed.
    _ = enter_operation(s, page, "On to operation 2.")
    earn_badge(s, page, "To the next gym.")
    s.check(
        any("frozen shrine" in card for card in cards(page)),
        f"the badge made no operation succeed: {cards(page)[-8:]}",
    )

    # Two more operations succeed as the player loses to their leaders, two badges apart: the
    # third opens at four badges, the fourth at six.
    for number, gyms in ((3, 1), (4, 2)):
        for gym in range(gyms):
            earn_badge(s, page, f"Gym {gym + 1} before operation {number}.")
        leader_id = enter_operation(s, page, f"On to operation {number}.")
        submit(page, f"I face the chief.\n!start_battle trainer_id={leader_id}")
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


def earn_badge(s: Session, page: Page, words: str) -> None:
    """A region that is owed nothing holds a gym; its leader gives the next badge."""
    room_id, leader_id = more_map(s, page, words, "")
    smith = [entry for entry in log() if entry["role"] == "worldsmith"][-1]
    s.check("write `operation`" not in smith["prompt"], f"an operation was owed too soon: {words}")
    submit(
        page,
        f"I take on the gym.\n!move to_id={room_id}\n!reveal target_id={leader_id}\n"
        f"!start_battle trainer_id={leader_id}",
    )
    wait_idle(page, timeout=60)
    fight(s, page, "Dragon Breath", f"gym-{room_id}")


def enter_operation(s: Session, page: Page, words: str) -> str:
    room_id, leader_id = more_map(s, page, words, "write `operation`")
    submit(page, f"I find the team.\n!move to_id={room_id}\n!reveal target_id={leader_id}")
    wait_idle(page, timeout=60)
    return leader_id


def answer_decisions(page: Page) -> None:
    for _ in range(12):
        pending = decision(page)
        if not pending.count():
            return
        for wanted in ("Forget Growl", "Skip", ""):
            button = pending.locator("button", has_text=wanted)
            if button.count():
                start_turn(button.first)
                break
        wait_idle(page, timeout=60)


def open_battle(page: Page) -> bool:
    """The banner opens the battle screen or, without the simulator, the setup hint."""
    banner = page.locator(".game-banner", has_text="A battle waits for you.")
    banner.wait_for(timeout=40000)
    banner.get_by_role("button", name="Battle").click()
    hint = page.locator(".q-notification__message", has_text=SETUP_HINT)
    choice = page.locator(".game-battle .game-choice:visible")
    hint.or_(choice).first.wait_for(timeout=40000)
    return hint.count() == 0


def fight(s: Session, page: Page, pick: str, shot: str) -> None:
    s.check(open_battle(page), f"the {shot} battle showed the setup hint")
    play_battle(s, page, pick, shot)


def play_battle(s: Session, page: Page, pick: str, shot: str) -> None:
    screen = page.locator(".game-battle:visible")
    choices = page.locator(".game-battle .game-choice:visible:enabled")
    choices.first.wait_for(timeout=40000)
    deadline = time.time() + 240
    while screen.count() and time.time() < deadline:
        wanted = choices.filter(has_text=pick)
        if choices.count():
            started = time.monotonic()
            (wanted if wanted.count() else choices).first.click()
            wait_server(started)
        page.wait_for_timeout(PAGE_TICK_SECONDS * 1000)
    s.check(not screen.count(), f"the {shot} battle never ended")
    wait_idle(page, timeout=60)
    s.shot(page, shot)
    answer_decisions(page)


def more_map(s: Session, page: Page, words: str, asked: str) -> tuple[str, str]:
    s.check(move(page, "More map").count() == 1, f"no More map offered before: {words}")
    send_move(page, "More map", words)
    wait_idle(page, timeout=60)
    smith = [entry for entry in log() if entry["role"] == "worldsmith"][-1]
    s.check(asked in smith["prompt"], f"the region request did not ask: {asked}")
    region = json.loads(smith["answer"])
    return str(region["start_id"]), str(next(iter(region["npcs"])))


run("pokemon", body)
