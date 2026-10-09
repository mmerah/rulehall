import sys
from pathlib import Path

from playwright.sync_api import Locator, Page

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    DEVICES,
    Session,
    cut_names,
    fits_width,
    open_device,
    open_drawer,
    run,
    still,
    submit,
    wait_idle,
)

CHAMPIONS_GAME = BASE + "/game/coral-circuit/kael"
TEAM_SIZE = 6
PICKED_FOR_BATTLE = 4
LEADS_ON_FIELD = 4
# The Showdown scene draws its sprites with scripts, not CSS animations, so `still` misses them.
PREVIEW_SHOWN = """count => [...document.querySelectorAll(".game-battle-scene img")]
  .filter(sprite => sprite.offsetParent !== null).length >= count"""
FIELD_SHOWN = """count => [...document.querySelectorAll(".game-battle-scene img")]
  .filter(sprite => sprite.style.display === "block").length >= count"""


def body(s: Session) -> None:
    for name, device in DEVICES:
        page = open_device(s, device)
        page.goto(BASE + "/rules/pokemon-champions")
        still(page)
        s.shot(page, f"{name}-champions-hall")
        s.check(fits_width(page), f"{name} champions hall scrolls sideways")
        champions_team_builder(s, page, name)
        page.context.close()
    champions_battle(s)


def champions_team_builder(s: Session, page: Page, name: str) -> None:
    page.goto(CHAMPIONS_GAME)
    wait_idle(page, timeout=40)
    still(page)
    s.shot(page, f"{name}-champions-game")
    s.check(fits_width(page), f"{name} champions game scrolls sideways")
    open_drawer(page)
    page.locator(".game-drawer-head .q-tab", has_text="Team").click()
    season = page.locator(".game-drawer").get_by_text("Season", exact=True)
    season.scroll_into_view_if_needed()
    still(page, ".game-drawer")
    s.shot(page, f"{name}-champions-team-tab")

    page.goto(CHAMPIONS_GAME)
    wait_idle(page, timeout=40)
    page.locator(".game-banner").get_by_role("button", name="Open team builder").click()
    page.locator(".game-builder-card").nth(TEAM_SIZE - 1).wait_for()
    still(page, ".game-builder")
    s.shot(page, f"{name}-champions-builder")
    s.check(fits_width(page), f"{name} team builder scrolls sideways")
    page.locator(".game-builder-card").nth(1).click()
    page.locator(".game-builder-editor-name", has_text="Sneasler").wait_for()
    still(page, ".game-builder")
    s.shot(page, f"{name}-champions-builder-slot")

    page.locator(".game-builder-section-slot .game-builder-pick").first.click()
    shoot_picker(s, page, f"{name}-champions-species-picker")
    show_pane(page, "Moves")
    page.locator(".game-builder-section-moves .game-builder-pick").first.click()
    shoot_picker(s, page, f"{name}-champions-moves-picker")

    expert = page.locator(".game-builder-expert")
    expert.click()
    page.locator(".game-builder-expert-on").wait_for()
    show_pane(page, "Points")
    scroll_to_top(page.locator(".game-builder-section-points"))
    still(page, ".game-builder")
    s.shot(page, f"{name}-champions-builder-points")
    show_pane(page, "Tips")
    advice = page.locator(".game-builder-advice")
    advice.wait_for()
    scroll_to_top(advice)
    still(page, ".game-builder")
    s.shot(page, f"{name}-champions-builder-advice")
    show_pane(page, "Set")
    show_pane(page, "Slot")

    tools = page.locator(".game-builder-tools")
    tools.get_by_role("button", name="Export").click()
    dialog = page.locator(".q-dialog")
    exported = dialog.locator("textarea").input_value()
    dialog.get_by_role("button", name="Close").click()
    dialog.wait_for(state="detached")
    tools.get_by_role("button", name="Import").click()
    dialog.locator("textarea").fill(exported)
    dialog.get_by_role("button", name="Check").click()
    dialog.locator(".game-builder-preview").nth(TEAM_SIZE - 1).wait_for()
    still(page, ".q-dialog")
    s.shot(page, f"{name}-champions-import")
    dialog.get_by_role("button", name="Cancel").click()
    dialog.wait_for(state="detached")
    tools.get_by_role("button", name="Start from").click()
    shoot_picker(s, page, f"{name}-champions-start-from")
    expert.click()
    page.locator(".game-builder-simple").wait_for()


def show_pane(page: Page, label: str) -> None:
    tab = page.locator(".game-builder-panes .q-tab:visible", has_text=label)
    if tab.count():
        tab.click()


def scroll_to_top(target: Locator) -> None:
    target.evaluate("element => element.scrollIntoView({block: 'start'})")


def shoot_picker(s: Session, page: Page, shot: str) -> None:
    picker = page.locator(".game-picker")
    picker.locator(".game-picker-option").first.wait_for()
    still(page, ".q-dialog")
    s.shot(page, shot)
    page.keyboard.press("Escape")
    picker.wait_for(state="detached")


def champions_battle(s: Session) -> None:
    pages = [(name, open_device(s, device)) for name, device in DEVICES]
    _, player = pages[0]
    player.goto(CHAMPIONS_GAME)
    wait_idle(player, timeout=40)
    submit(player, "I sign up and sit down.\n!register_team\n!start_match")
    wait_idle(player, timeout=60)
    for name, page in pages:
        if page is not player:
            page.goto(CHAMPIONS_GAME)
            wait_idle(page, timeout=40)
        open_battle(page)
        page.wait_for_function(PREVIEW_SHOWN, arg=TEAM_SIZE * 2, timeout=40000)
        still(page, ".game-battle")
        s.shot(page, f"{name}-champions-preview")
        s.check(fits_width(page), f"{name} champions team preview scrolls sideways")
        cut = cut_names(page)
        s.check(not cut, f"{name} team preview cuts names: {cut}")
    unpicked = player.locator(".game-battle .game-choice-switch:visible:enabled")
    picked = player.locator(".game-battle .game-choice-switch:visible", has_text="Picked:")
    for count in range(1, PICKED_FOR_BATTLE + 1):
        unpicked.first.click()
        if count < PICKED_FOR_BATTLE:
            picked.nth(count - 1).wait_for()
    for name, page in pages:
        mega = page.locator(".game-battle .game-choice-mega:visible", has_text="Mega Evolve")
        mega.wait_for(timeout=40000)
        page.wait_for_function(FIELD_SHOWN, arg=LEADS_ON_FIELD, timeout=40000)
        still(page, ".game-battle")
        s.shot(page, f"{name}-champions-mega")
        s.check(fits_width(page), f"{name} champions battle scrolls sideways")
        cut = cut_names(page)
        s.check(not cut, f"{name} battle cuts names: {cut}")
        page.context.close()


def open_battle(page: Page) -> None:
    banner = page.locator(".game-banner", has_text="A battle waits for you.")
    banner.wait_for(timeout=40000)
    banner.get_by_role("button", name="Battle").click()
    page.locator(".game-battle .game-choice:visible").first.wait_for(timeout=40000)


run("champions", body)
