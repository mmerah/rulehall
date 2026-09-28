"""Playwright helpers for driving the QA server. Run scenario scripts with the `qa` group."""

import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import NotRequired, TypedDict

from playwright.sync_api import Browser, Locator, Page, ViewportSize, WebSocket, sync_playwright

BASE = f"http://localhost:{os.environ.get('QA_PORT', '8123')}"
# A socket.io event frame starts with its packet digits: `42[...]`.
SOCKET_EVENT = re.compile(r"^\d+(?=\[)")
SCROLLED_DOWN = "box => box.scrollTop + box.clientHeight >= box.scrollHeight - 2"
# Loops such as the working dots never end, so they do not count.
ANIMATIONS_DONE = """selector => document.querySelector(selector)
  .getAnimations({subtree: true})
  .every(animation => animation.playState !== "running"
    || animation.effect.getComputedTiming().iterations === Infinity)"""
# The game page redraws from its session on a 0.25 s timer.
PAGE_TICK_SECONDS = 0.3
# Not innerText: it reads empty for a turn the browser skips off screen (content-visibility).
READ_TEXTS = """elements => elements.map(element => {
  const copy = element.cloneNode(true);
  copy.querySelectorAll("br").forEach(line => line.replaceWith("\\n"));
  copy.querySelectorAll("div").forEach(block => block.append("\\n"));
  return copy.textContent;
})"""


class Spoken(TypedDict):
    """One role's spawn as `/qa/log` serves it; the shape `agents.Spoken` is dumped from."""

    role: str
    prompt: str
    answer: str
    error: str
    calls: list[tuple[str, dict[str, object], str]]


class GateStatus(TypedDict):
    busy: bool
    idle_seconds: float


class Device(TypedDict):
    """The `new_context` keywords a scenario emulates a phone or a tablet with."""

    viewport: ViewportSize
    device_scale_factor: float
    is_mobile: bool
    has_touch: bool
    user_agent: NotRequired[str]


@dataclass
class Session:
    browser: Browser
    shots: Path
    issues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    counter: int = 0

    def page(self) -> Page:
        context = self.browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.set_default_timeout(15000)
        page.on(
            "console",
            lambda m: (
                self.notes.append(f"console[{m.type}]: {m.text}")
                if m.type in ("error", "warning")
                else None
            ),
        )
        page.on("pageerror", lambda e: self.issues.append(f"pageerror: {e}"))
        return page

    def shot(self, page: Page, name: str) -> None:
        self.counter += 1
        page.screenshot(path=str(self.shots / f"{self.counter:03d}-{name}.png"), full_page=False)

    def check(self, condition: bool, message: str, /) -> bool:
        if not condition:
            self.issues.append(message)
            print("ISSUE:", message)
        return condition

    def note(self, message: str) -> None:
        self.notes.append(message)
        print("NOTE:", message)


@dataclass(frozen=True)
class Sample:
    frames: int
    kilobytes: float
    elements: int

    def line(self) -> str:
        return f"frames={self.frames} kb={self.kilobytes:.1f} elements={self.elements}"


class SocketTraffic:
    """What the server sends one page over its websockets, counted from the page's side.

    Sync Playwright hands over frames only inside its own calls, so a caller waits with
    `page.wait_for_timeout`, never `time.sleep`, before it marks.
    """

    def __init__(self, page: Page) -> None:
        self.total = Sample(frames=0, kilobytes=0, elements=0)
        self.marked = self.total
        page.on("websocket", self.attach)

    def attach(self, socket: WebSocket) -> None:
        socket.on("framereceived", self.count)

    def count(self, payload: str | bytes) -> None:
        binary = isinstance(payload, bytes)
        self.total = Sample(
            frames=self.total.frames + 1,
            kilobytes=self.total.kilobytes + len(payload if binary else payload.encode()) / 1024,
            elements=self.total.elements + (0 if binary else updated_elements(payload)),
        )

    def mark(self) -> Sample:
        """The traffic since the last mark."""
        total, marked = self.total, self.marked
        self.marked = total
        return Sample(
            frames=total.frames - marked.frames,
            kilobytes=total.kilobytes - marked.kilobytes,
            elements=total.elements - marked.elements,
        )


def run(name: str, body: Callable[[Session], None]) -> None:
    shots = Path(__file__).parent / "shots" / name
    shots.mkdir(parents=True, exist_ok=True)
    for old in shots.glob("*.png"):
        old.unlink()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        session = Session(browser=browser, shots=shots)
        try:
            body(session)
        except Exception as crashed:
            session.issues.append(f"crash: {type(crashed).__name__}: {crashed}")
            raise
        finally:
            release()
            browser.close()
            report = shots / "report.json"
            report.write_text(
                json.dumps({"issues": session.issues, "notes": session.notes}, indent=1)
            )
            print(f"\n== {name}: {len(session.issues)} issues")
            for issue in session.issues:
                print(" -", issue)


def log() -> list[Spoken]:
    with urllib.request.urlopen(f"{BASE}/qa/log") as reply:
        spoken: list[Spoken] = json.load(reply)
    # JSON hands the call triples back as lists; the declared shape is restored here.
    for entry in spoken:
        entry["calls"] = [(name, args, answer) for name, args, answer in entry["calls"]]
    return spoken


def arm(role: str, fault: str) -> None:
    _post("/qa/faults", role=role, fault=fault)


def release(role: str | None = None) -> None:
    _post("/qa/release", **({} if role is None else {"role": role}))


@contextmanager
def held(role: str) -> Generator[None]:
    """The role's next ask waits inside the block, so the page shows it working."""
    arm(role, "hold")
    try:
        yield
    finally:
        release(role)


def gate_status() -> GateStatus:
    with urllib.request.urlopen(f"{BASE}/status") as reply:
        status: GateStatus = json.load(reply)
    return status


def active_since(started: float) -> bool:
    """The server is busy, or went idle after `started` (a `time.monotonic()`)."""
    elapsed = time.monotonic() - started
    status = gate_status()
    return status["busy"] or status["idle_seconds"] < elapsed


def wait_started(started: float, timeout: float = 5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if active_since(started):
            return True
        time.sleep(0.02)
    return False


def wait_server(started: float, timeout: float = 60) -> bool:
    """The server took work after `started` and finished it."""
    if not wait_started(started):
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not gate_status()["busy"]:
            return True
        time.sleep(0.02)
    return False


def composer(page: Page) -> Locator:
    return page.locator(".game-composer textarea")


def send(page: Page) -> Locator:
    return page.locator('button[aria-label="Send"]')


def working(page: Page) -> Locator:
    """The bubble a role writes in while it works; its dots are CSS, not a Quasar spinner."""
    return page.locator(".game-working:visible")


def wait_idle(page: Page, timeout: float = 30) -> None:
    """For a whole page tick: the server is idle, no role works, and the composer is enabled
    again or a decision waits on the player."""
    deadline = time.time() + timeout
    idle_since: float | None = None
    while time.time() < deadline:
        spinning = working(page).count() > 0
        disabled = composer(page).is_disabled() if composer(page).count() else True
        idle = not spinning and (not disabled or waiting_on_player(page).count() > 0)
        if not idle or gate_status()["busy"]:
            idle_since = None
        elif idle_since is None:
            idle_since = time.time()
        elif time.time() - idle_since >= PAGE_TICK_SECONDS:
            return
        page.wait_for_timeout(50)
    raise TimeoutError("the page never went idle")


def decision(page: Page) -> Locator:
    return page.locator(".game-asking:visible")


def waiting_on_player(page: Page) -> Locator:
    return page.locator(".game-asking:visible, .game-banner:visible")


def move(page: Page, name: str) -> Locator:
    return page.locator(".game-moves button.game-choice", has_text=name)


def wait_working(page: Page, timeout: float = 5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if working(page).count() > 0:
            return True
        page.wait_for_timeout(50)
    return False


def submit(page: Page, text: str, *, enter: bool = False, wait: bool = True) -> bool:
    """Type and send; returns whether the server took a turn."""
    box = composer(page)
    box.fill(text)
    started = time.monotonic()
    if enter:
        box.press("Enter")
    else:
        send(page).click()
    return wait_started(started) if wait else True


def start_turn(target: Locator) -> bool:
    """Click a move or an option; returns whether the server took a turn."""
    started = time.monotonic()
    target.click()
    return wait_started(started)


def scrolled_down(page: Page) -> bool:
    return page.locator(".game-transcript .q-scrollarea__container").evaluate(SCROLLED_DOWN)


def bubbles(page: Page) -> list[str]:
    return transcript_texts(page, ".q-message-text-content")


def reach_breather(page: Page, tries: int = 8) -> bool:
    """Close Loner scenes until the transition rolls a quiet one; the dice are seeded per game."""
    if move(page, "Take the breather").count():
        return True
    return bool(close_until(page, "quiet", tries))


def close_until(page: Page, wanted: str, tries: int = 12) -> str:
    """Close Loner scenes until the close card names `wanted`, taking each breather on the way."""
    for attempt in range(tries):
        if move(page, "Take the breather").count():
            take_breather(page, f'I rest ({attempt}).\n!direct text="He rests."')
        submit(page, f'Onward ({attempt}).\n!close_scene reason=resolved\n!direct text="On."')
        wait_idle(page, timeout=60)
        closed = [c for c in cards(page) if "Scene closes:" in c][-1]
        if wanted in closed:
            return closed
    return ""


def select(page: Page, label: str, option: str) -> None:
    page.locator(f".q-select:has(.q-field__label:text-is('{label}'))").first.click()
    page.locator(".q-menu .q-item", has_text=option).first.click()
    page.locator(".q-menu").wait_for(state="detached")


def text(page: Page, label: str, value: str) -> None:
    box = page.locator(".q-field", has_text=label).first.locator("input, textarea").first
    box.fill(value)
    box.blur()


def use_move(page: Page, name: str) -> None:
    start_turn(move(page, name))
    wait_idle(page, timeout=60)


def send_move(page: Page, name: str, words: str) -> bool:
    if name not in send(page).inner_text():
        move(page, name).click()
        send(page).filter(has_text=name).wait_for()
    return submit(page, words)


def take_breather(page: Page, words: str) -> None:
    send_move(page, "Take the breather", words)
    # The quiet scene's write and the aim's own turn run back to back: wait for the aim's turn.
    aim = words.splitlines()[0]
    deadline = time.time() + 60
    while (
        not any(f"[narration] {aim}" in bubble for bubble in bubbles(page))
        and time.time() < deadline
    ):
        page.wait_for_timeout(50)
    wait_idle(page, timeout=60)


def cards(page: Page) -> list[str]:
    return transcript_texts(page, ".game-card")


def transcript_texts(page: Page, selector: str) -> list[str]:
    texts: list[str] = page.locator(f".game-transcript {selector}").evaluate_all(READ_TEXTS)
    return [re.sub(r"\n+", "\n", text).strip() for text in texts]


def notifications(page: Page) -> list[str]:
    return [t.strip() for t in page.locator(".q-notification__message").all_inner_texts()]


def placeholder(page: Page) -> str:
    return composer(page).get_attribute("placeholder") or ""


def drawer_text(page: Page) -> str:
    return page.locator(".game-drawer").inner_text()


def open_drawer(page: Page) -> None:
    if not page.locator(".game-drawer").is_visible():
        page.locator('button:has(i:text("menu_book"))').click()
        page.locator(".game-drawer").wait_for()


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def wait_until(page: Page, condition: Callable[[], bool], timeout: float = 5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        page.wait_for_timeout(50)
    return False


def shows(page: Page, words: str, timeout: float = 5) -> bool:
    return wait_until(page, lambda: words in clean(page.inner_text("body")), timeout)


def notified(page: Page, words: str, timeout: float = 5) -> bool:
    return wait_until(page, lambda: any(words in n for n in notifications(page)), timeout)


def still(page: Page, selector: str = "body") -> None:
    """Every finite animation in `selector` has ended, for a screenshot worth looking at."""
    page.wait_for_function(ANIMATIONS_DONE, arg=selector)


def updated_elements(frame: str) -> int:
    """The element entries of a NiceGUI `update` event: `42["update",{"<id>":{…},"_id":7}]`."""
    head = SOCKET_EVENT.match(frame)
    if head is None:
        return 0
    event = json.loads(frame[head.end() :])
    if event[0] != "update":
        return 0
    return sum(1 for key in event[1] if key != "_id")


def _post(path: str, **query: str) -> None:
    request = urllib.request.Request(f"{BASE}{path}?{urllib.parse.urlencode(query)}", method="POST")
    with urllib.request.urlopen(request):
        pass
