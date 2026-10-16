"""The Ford Watch (5e Lite): a point-buy hero, the map tools, the panels and one battle."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    PHONE,
    Session,
    cards,
    clean,
    drawer_text,
    fits_width,
    log,
    open_device,
    run,
    select,
    shows,
    still,
    submit,
    text,
    wait_idle,
)
from playwright.sync_api import Page

GAME = BASE + "/game/ford-watch/hesper"
TRAP = '{"kind":"trap","hazard_id":"snare"}'
# A foe's or a person's HP, AC, CR, XP, DC and passive Perception never reach the narrator.
HIDDEN_NUMBER = re.compile(r"\b(?:DC|AC|CR|XP) \d|\bHP \d+/\d|passive Perception \d", re.I)
# A save or a check on a difficulty word is the player's own, and its DC is told.
OWN_TEST = re.compile(r"\d+ vs DC \d+")
PALADIN = (
    ("Class", "Paladin"),
    ("Species", "Tiefling"),
    ("Lineage", "Abyssal"),
    ("Species spellcasting", "Charisma"),
    ("Background", "Acolyte"),
    ("Ability scores", "Point buy"),
    ("Ability increases", "Charisma +2, Wisdom +1"),
    ("Strength", "15"),
    ("Dexterity", "8"),
    ("Constitution", "14"),
    ("Intelligence", "8"),
    ("Wisdom", "10"),
    ("Charisma", "15"),
    ("Class skill 1", "Athletics"),
    ("Class skill 2", "Persuasion"),
    ("Magic Initiate spellcasting", "Wisdom"),
    ("Magic Initiate cantrip 1", "Guidance"),
    ("Magic Initiate cantrip 2", "Light"),
    ("Magic Initiate spell", "Bless"),
    ("Prepared spell 1", "Cure Wounds"),
    ("Prepared spell 2", "Command"),
)


def body(s: Session) -> None:
    page = s.page()
    create_paladin(s, page)

    # The shipped hero on the shipped scenario.
    page.goto(BASE + "/rules/lite5e?character=hesper")
    still(page)
    page.get_by_role("button", name="Start").first.click()
    page.wait_for_url("**/game/ford-watch/hesper")
    wait_idle(page, timeout=60)
    s.shot(page, "opening")

    play(page, "!move to_id=mill")
    play(page, f"!check what=Search actor_id=player skill=perception dc='{target('snare')}'")
    s.check(any("Hidden snare found" in c for c in cards(page)), "the search found no snare")
    play(page, f"!harm actor_ids='[\"player\"]' danger='{TRAP}'")
    play(
        page,
        '!harm actor_ids=\'["player"]\' danger=\'{"kind":"save","ability":"constitution",'
        '"difficulty":"hard","damage":"moderate","damage_type":"poison"}\'',
    )
    play(page, "!cast spell_id=bless")
    s.check(refused("Bless is a battle spell"), "a buff was cast outside a battle")
    play(page, "!cast spell_id=cure-wounds target_ids='[\"player\"]'")
    s.check(not refused(), "a healing spell was refused outside a battle")
    play(page, "!rest kind=short")
    play(page, '!reward reward=\'{"kind":"goal","goal_id":"scout-mill"}\'')
    s.check("XP 100 of 300" in clean(drawer_text(page)), "the goal paid no XP")

    # Hire a class companion at the ford, then open the cellar and fight.
    play(page, "!move to_id=ford")
    play(page, "!join_party target_id=watchman terms='Guards the party for a share.'")
    s.check(shows(page, "Fighter 1, Human, Soldier"), "the watchman signed on with no sheet")
    play(page, "!move to_id=mill")
    play(
        page,
        '!make_item holder_id=player name="Cellar key" note="It opens the cellar." '
        'opens=\'{"from_id":"mill","to_id":"cellar"}\'',
    )
    play(page, "!unlock_way to_id=cellar")
    play(page, "!rest kind=short")
    s.check(refused("no rest while a hostile person is near"), "a rest next to raiders")
    play(page, "!move to_id=cellar")
    play(page, "!start_battle foe_ids='[\"raiders\"]' opening=foe_ambush")
    s.shot(page, "battle-waits")
    gear_refused(s, page)
    battle(s, page)

    for spoken in log():
        if spoken["role"] == "narrator":
            told = spoken["answer"]
            if '"difficulty":' in spoken["prompt"]:
                told = OWN_TEST.sub("", told)
            leaked = HIDDEN_NUMBER.search(told)
            s.check(leaked is None, f"the narrator was told a number: {spoken['answer'][:300]}")

    phone = open_device(s, PHONE)
    phone.goto(GAME)
    wait_idle(phone)
    s.check(fits_width(phone), "the game page is wider than a phone")
    s.shot(phone, "phone")


def create_paladin(s: Session, page: Page) -> None:
    page.goto(BASE + "/rules/lite5e/character")
    still(page)
    text(page, "Name", "Pell")
    text(page, "Brief", "A test paladin.")
    for label, choice in PALADIN:
        s.check(shows(page, label), f"creation never asked for {label}")
        select(page, label, choice)
    s.check(shows(page, "Create"), f"the paladin is not ready: {clean(page.inner_text('body'))}")
    preview = clean(page.inner_text("body"))
    # Chain Mail 16 and a Shield 2: heavy armor takes no Dexterity, even a penalty.
    armor_class = re.search(r"Defense (\d+) AC", preview)
    s.check(
        armor_class is not None and armor_class.group(1) == "18",
        f"the paladin's AC is {armor_class and armor_class.group(1)}, not 18",
    )
    s.shot(page, "paladin")
    page.get_by_role("button", name="Create").click()
    page.wait_for_url("**/rules/lite5e?character=pell")


def gear_refused(s: Session, page: Page) -> None:
    page.locator(".q-tab:has-text('Gear')").first.click()
    page.locator(".game-drawer .game-opens", has_text="Javelin").first.locator(
        ".game-stat-value"
    ).click()
    dialog = page.locator(".q-dialog")
    dialog.locator("button.game-choice").first.wait_for()
    s.check(
        all(choice.is_disabled() for choice in dialog.locator("button.game-choice").all()),
        "the Gear panel offers an edit during a battle",
    )
    page.keyboard.press("Escape")
    dialog.wait_for(state="detached")


def battle(s: Session, page: Page) -> None:
    page.locator(".game-banner button", has_text="Battle").first.click()
    page.locator(".game-lite5e-menu").wait_for()
    s.shot(page, "battle")
    for _ in range(30):
        if not page.locator(".game-lite5e").is_visible():
            break
        menu = page.locator(".game-lite5e-menu")
        attack = menu.locator("button", has_text="Greatsword").first
        if attack.count() == 0:
            attack = menu.locator("button", has_text="Longsword").first
        if attack.count() and attack.is_enabled():
            attack.click()
            menu.locator("button", has_text="Mill raiders").first.click()
        elif menu.locator("button", has_text="End the turn").count():
            menu.locator("button", has_text="End the turn").click()
        page.wait_for_timeout(800)
    wait_idle(page, timeout=60)
    told = " ".join(cards(page))
    s.check("Victory" in told or "Defeat" in told, f"the battle never ended: {told[-400:]}")
    s.check("XP each" in told, "the battle paid no XP")
    s.shot(page, "aftermath")


def play(page: Page, words: str) -> None:
    submit(page, words)
    wait_idle(page, timeout=60)


def refused(words: str = "") -> bool:
    calls = [call for spoken in log() if spoken["role"] == "master" for call in spoken["calls"]]
    answer = calls[-1][2]
    return answer.startswith("REFUSED") and words in answer


def target(target_id: str) -> str:
    return f'{{"kind":"target","target_id":"{target_id}"}}'


run("lite5e", body)
