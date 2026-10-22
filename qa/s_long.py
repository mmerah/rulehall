"""A long Loner save (122 turns, a party of four) on a desktop, a tablet and a phone: the turn
window, Show earlier turns, the reader's place, Read aloud on an earlier turn, an idle page,
slow-CPU typing, a new turn, the scene card folded and kept. Run on a server started with
`--speech`."""

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import Page

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    DEVICES,
    Session,
    bubbles,
    fits_width,
    open_device,
    run,
    still,
    submit,
    wait_idle,
    wait_until,
)
from long_save import lengthen

from rulehall.ui.game import NEAR_END
from rulehall.ui.transcript import SHOWN_TURNS

GAME = BASE + "/game/whispering-vault/kael"
HALL = BASE + "/rules/loner4e"
WORK = Path(os.environ.get("QA_WORK", "/tmp/rulehall-qa-work"))
SAVE = WORK / "saves" / "whispering-vault--kael.json"
TURNS = 122
PLACE_SLACK = 3
THROTTLE = 6
TYPED = "I search the cellar for the abbot's key!"
SLOW_KEY_MS = 200
DRAWN_TURNS = "() => document.querySelectorAll('.game-transcript .game-turn:has(> div > *)').length"
# The reader sits at the top, where the control is; the first drawn turn is the place to keep.
TO_TOP = """() => {
  const area = document.querySelector('.game-transcript');
  area.releaseEnd?.();
  area.querySelector('.q-scrollarea__container').scrollTop = 0;
}"""
# From the click for 2 s, reads the kept turn's top after each layout (an observer made after
# the page's own) and after each painted frame (a task queued from the frame, skipped when the
# page changed since the frame, as that layout is not painted yet).
WATCH_PLACE = """() => {
  const turn = document.querySelector('.game-transcript .game-turn:has(> div > *)');
  const content = document.querySelector('.game-transcript .q-scrollarea__content');
  const control = document.querySelector('.game-transcript .game-earlier');
  const seen = turn.getBoundingClientRect().top;
  const watch = window.qaPlace = {seen, worst: 0, last: 0, frames: 0, done: false};
  const sample = () => {
    watch.last = turn.getBoundingClientRect().top - seen;
    watch.worst = Math.max(watch.worst, Math.abs(watch.last));
  };
  control.addEventListener('click', () => {
    const started = performance.now();
    let changed = false;
    const changes = new MutationObserver(() => { changed = true; });
    changes.observe(content, {childList: true, subtree: true, attributes: true});
    const sizes = new ResizeObserver(sample);
    sizes.observe(content);
    const frame = () => {
      changed = false;
      setTimeout(() => {
        if (!changed) {
          watch.frames += 1;
          sample();
        }
        if (performance.now() - started < 2000) requestAnimationFrame(frame);
        else { sizes.disconnect(); changes.disconnect(); watch.done = true; }
      });
    };
    requestAnimationFrame(frame);
  }, {once: true});
}"""
COUNT_UPDATES = """() => {
  window.qaUpdates = 0;
  window.socket.on('update', () => { window.qaUpdates += 1; });
}"""
SCENE_CLOSED = "() => document.documentElement.classList.contains('game-scene-closed')"
SCENE_STRIP = 48
TRANSCRIPT_GAP = """() => {
  const box = document.querySelector('.game-transcript .q-scrollarea__container');
  return box.scrollHeight - box.scrollTop - box.clientHeight;
}"""
TIME_KEYS = """() => {
  window.qaKeys = [];
  document.addEventListener('keydown', (event) => {
    const pressed = event.timeStamp;
    requestAnimationFrame(() => setTimeout(() => window.qaKeys.push(performance.now() - pressed)));
  }, true);
}"""


def body(s: Session) -> None:
    install_long_save(s)
    for name, device in DEVICES:
        page = open_device(s, device)
        show_every_turn(s, page, name, touch=device["has_touch"])
        if name == "desktop":
            read_aloud_earlier(s, page)
        if name == "tablet":
            time_typing(s, page)
        new_turn(s, page, name)
        fold_scene(s, page, name, touch=device["has_touch"])
        page.context.close()


def install_long_save(s: Session) -> None:
    """A real opening played here, then the save deleted from the hall and written back long."""
    page = s.page()
    page.goto(GAME)
    wait_idle(page, timeout=40)
    played = json.loads(SAVE.read_text())
    page.goto(HALL)
    page.locator('button[aria-label="Delete"]').first.click()
    page.locator(".q-dialog").get_by_role("button", name="Delete").click()
    s.check(wait_until(page, lambda: not SAVE.exists()), "the hall did not delete the save")
    page.context.close()
    SAVE.write_text(json.dumps(lengthen(played, TURNS)))


def show_every_turn(s: Session, page: Page, name: str, *, touch: bool) -> None:
    total = saved_turns()
    page.goto(GAME)
    wait_idle(page, timeout=40)
    still(page, ".game-transcript")
    s.check(fits_width(page), f"{name}: the game page scrolls sideways")
    drawn = page.evaluate(DRAWN_TURNS)
    s.check(drawn == SHOWN_TURNS, f"{name}: {drawn} turns drawn at load, not {SHOWN_TURNS}")
    control = page.locator(".game-transcript .game-earlier")
    page.evaluate(TO_TOP)
    s.check(control.is_visible(), f"{name}: no Show earlier turns at the top")
    count = page.locator(".game-earlier-count").inner_text()
    s.check(count == f"{total - drawn} more", f"{name}: the control counts {count!r}")
    box = control.bounding_box()
    s.check(box is not None and box["height"] >= 44, f"{name}: the control is too small: {box}")
    still(page, ".game-transcript")
    s.shot(page, f"{name}-top")
    taps = 0
    while control.is_visible() and taps < TURNS:
        taps += 1
        before = page.evaluate(DRAWN_TURNS)
        page.evaluate(TO_TOP)
        page.evaluate(WATCH_PLACE)
        if touch:
            control.tap()
        else:
            control.click()
        wanted = min(total, before + SHOWN_TURNS)
        s.check(
            wait_until(page, lambda wanted=wanted: page.evaluate(DRAWN_TURNS) == wanted),
            f"{name}: tap {taps} drew {page.evaluate(DRAWN_TURNS)} turns, not {wanted}",
        )
        page.wait_for_function("() => window.qaPlace.done")
        place = page.evaluate("() => window.qaPlace")
        s.check(
            place["worst"] <= PLACE_SLACK,
            f"{name}: tap {taps} moved the reader's turn by {place['worst']:.0f}px "
            f"over {place['frames']} frames (ends {place['last']:.0f}px off)",
        )
        if taps == 1:
            s.shot(page, f"{name}-after-tap")
    s.check(not control.is_visible(), f"{name}: the control stays after {taps} taps")
    focused = page.evaluate("() => document.activeElement.classList.contains('game-turn')")
    s.check(focused, f"{name}: the last tap left the focus off the first turn")
    drawn = page.evaluate(DRAWN_TURNS)
    s.check(drawn == total, f"{name}: {drawn} turns drawn after every tap, not {total}")
    s.note(f"{name}: {taps} taps drew {drawn} turns")
    page.evaluate(TO_TOP)
    still(page, ".game-transcript")
    s.shot(page, f"{name}-first-turns")
    idle(s, page, name)


def idle(s: Session, page: Page, name: str) -> None:
    page.wait_for_timeout(1000)
    page.evaluate(COUNT_UPDATES)
    page.wait_for_timeout(5000)
    updates = page.evaluate("() => window.qaUpdates")
    s.check(updates == 0, f"{name}: an idle page got {updates} updates in 5 s")


def read_aloud_earlier(s: Session, page: Page) -> None:
    """Read aloud on turn 5's first line marks that bubble, and no other."""
    turn = page.locator(".game-transcript .game-turn", has_text="Turn 5: I look")
    bubble = turn.locator(".game-message:has(.game-read-aloud)").first
    if not bubble.count():
        s.note("read aloud skipped: the server runs without --speech")
        return
    bubble.locator(".game-read-aloud").click()
    marked = "() => [...document.querySelectorAll('.game-message[data-voice]')].map(m => m.id)"
    bubble_id = bubble.get_attribute("id")
    s.check(
        wait_until(page, lambda: page.evaluate(marked) == [bubble_id]),
        f"read aloud on an earlier bubble marks {page.evaluate(marked)}, not [{bubble_id!r}]",
    )
    s.note(f"read aloud on turn 5: {bubble.get_attribute('data-voice')}")


def time_typing(s: Session, page: Page) -> None:
    page.reload()
    wait_idle(page, timeout=40)
    page.evaluate(TIME_KEYS)
    box = page.locator(".game-composer textarea")
    box.tap()
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": THROTTLE})
    page.wait_for_timeout(1000)
    page.keyboard.type(TYPED, delay=120)
    page.wait_for_timeout(2000)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
    keys = sorted(page.evaluate("() => window.qaKeys"))
    p90 = keys[int(len(keys) * 0.9)]
    s.note(f"tablet at {THROTTLE}x CPU: {len(keys)} keys, p90 {p90:.0f} ms, max {keys[-1]:.0f} ms")
    s.check(p90 <= SLOW_KEY_MS, f"tablet: p90 keystroke latency {p90:.0f} ms at {THROTTLE}x CPU")
    s.check(box.input_value() == TYPED, f"tablet: the composer holds {box.input_value()!r}")
    box.fill("")


def new_turn(s: Session, page: Page, name: str) -> None:
    total = saved_turns()
    drawn = page.evaluate(DRAWN_TURNS)
    words = f"I wait by the door ({name})."
    s.check(submit(page, words), f"{name}: the turn did not start")
    wait_idle(page, timeout=40)
    s.check(
        wait_until(page, lambda: any(f"[narration] {words}" in bubble for bubble in bubbles(page))),
        f"{name}: the new turn's narration did not land",
    )
    s.check(saved_turns() == total + 1, f"{name}: the save holds {saved_turns()} turns")
    s.check(
        page.evaluate(DRAWN_TURNS) == drawn + 1,
        f"{name}: {page.evaluate(DRAWN_TURNS)} turns drawn after a new turn, not {drawn + 1}",
    )
    still(page, ".game-transcript")
    s.shot(page, f"{name}-new-turn")


def fold_scene(s: Session, page: Page, name: str, *, touch: bool) -> None:
    page.goto(GAME)
    wait_idle(page, timeout=40)
    still(page, ".game-transcript")
    scene = page.locator(".game-scene")
    chevron = scene.locator("button.game-scene-chevron")
    phone = name == "phone"
    s.check(page.evaluate(SCENE_CLOSED) == phone, f"{name}: the scene starts folded wrong")

    def fold(how: str) -> None:
        closed = page.evaluate(SCENE_CLOSED)
        if how == "tap" and touch:
            scene.tap()
        elif how == "tap":
            scene.click()
        else:
            chevron.focus()
            page.keyboard.press(how)
        s.check(page.evaluate(SCENE_CLOSED) != closed, f"{name}: {how} did not fold the scene")
        expanded = chevron.get_attribute("aria-expanded")
        s.check(expanded == str(closed).lower(), f"{name}: aria-expanded reads {expanded}")
        still(page, ".game-scene")
        page.wait_for_timeout(300)
        gap = page.evaluate(TRANSCRIPT_GAP)
        s.check(gap <= NEAR_END, f"{name}: the fold left the transcript {gap:.0f}px off its end")

    if phone:
        s.shot(page, f"{name}-scene-closed")
        fold("tap")
        s.shot(page, f"{name}-scene-open")
        page.reload()
        page.wait_for_selector(".game-scene")
        s.check(page.evaluate(SCENE_CLOSED), f"{name}: the phone remembered the open scene")
        return
    transcript = page.locator(".game-transcript")
    tall = transcript.bounding_box()
    fold("tap")
    strip = scene.bounding_box()
    s.check(
        strip is not None and strip["height"] <= SCENE_STRIP,
        f"{name}: the folded scene is {strip} tall",
    )
    taller = transcript.bounding_box()
    s.check(
        tall is not None and taller is not None and taller["height"] > tall["height"],
        f"{name}: folding the scene gave the transcript nothing ({tall} -> {taller})",
    )
    s.shot(page, f"{name}-scene-closed")
    page.reload()
    page.wait_for_selector(".game-scene")
    s.check(page.evaluate(SCENE_CLOSED), f"{name}: the fold did not survive a reload")
    wait_idle(page, timeout=40)
    expanded = chevron.get_attribute("aria-expanded")
    s.check(expanded == "false", f"{name}: aria-expanded reads {expanded} after a reload")
    s.shot(page, f"{name}-scene-reloaded")
    fold("tap")
    fold("Space")
    fold("Enter")
    s.check(not page.evaluate(SCENE_CLOSED), f"{name}: the scene ends folded")
    s.shot(page, f"{name}-scene-open")


def saved_turns() -> int:
    chapters = json.loads(SAVE.read_text())["chapters"]
    return sum(len(chapter["entries"]) for chapter in chapters)


run("long", body)
