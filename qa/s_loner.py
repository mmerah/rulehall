"""The Whispering Vault (Loner 3e): the full life of one game page."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    Session,
    bubbles,
    cards,
    clean,
    composer,
    drawer_text,
    log,
    open_drawer,
    placeholder,
    run,
    send,
    submit,
    wait_idle,
    wait_working,
    working,
)

GAME = BASE + "/game/whispering-vault/kael"


def body(s: Session) -> None:
    page = s.page()
    page.goto(GAME)
    # Opening: the narrator works, then the story begins.
    s.check(wait_working(page), "no working indicator during the opening")
    s.check(
        "Narrator is working" in placeholder(page),
        f"placeholder during opening: {placeholder(page)!r}",
    )
    s.check(composer(page).is_disabled(), "composer enabled while the opening is narrated")
    s.shot(page, "opening-working")
    wait_idle(page)
    s.shot(page, "opened")
    text = clean(page.inner_text(".game-transcript"))
    s.check("(the story begins)" in text, "opening cause missing")
    s.check("[narration]" in text, "opening narration missing")
    s.check(placeholder(page) == "What do you do?", f"idle placeholder: {placeholder(page)!r}")
    # The drawer is open at 1280px with the sheet.
    side = clean(drawer_text(page))
    s.check("Luck 6/6" in side, f"sheet missing luck: {side[:200]}")
    s.check("Mara" in side and "trail" in side.lower(), "here/trail panels missing")

    # 1. A plain turn: default roll.
    s.check(submit(page, "I search the desk."), "no working indicator after submit")
    s.check(composer(page).is_disabled(), "composer stayed enabled during the turn")
    wait_idle(page)
    s.shot(page, "turn-roll")
    s.check(any("oracle" in c for c in cards(page)), f"no oracle card: {cards(page)}")
    s.check(composer(page).input_value() == "", "composer not cleared after an accepted turn")

    # 2. Reveal + take: cards and sheet.
    submit(
        page,
        "I find the map.\n!reveal target_id=vault-map\n!change_tags actor_id=player kind=gear gained='[\"Vault Map\"]'",  # noqa: E501
    )
    wait_idle(page)
    s.check(
        any(
            "Vault map discovered" in c or "vault map discovered" in c.lower() for c in cards(page)
        ),
        f"reveal card missing: {cards(page)[-3:]}",
    )
    s.check("Vault Map" in clean(drawer_text(page)), "gear not on the sheet")
    s.shot(page, "turn-reveal")

    # 3. A conflict: the rules pause on a text decision.
    submit(
        page,
        'I fight Mara.\n!roll what="Strike at Mara" actor_id=player question="Does he land it?" target_id=mara',  # noqa: E501
    )
    wait_idle(page)
    s.shot(page, "conflict-pending")
    text = clean(page.inner_text("body"))
    s.check(
        page.locator(".game-decision:visible", has_text="conflict").count() == 1,
        "decision panel missing on a conflict",
    )
    s.check(
        placeholder(page) == "The game is waiting on your answer.",
        f"conflict placeholder: {placeholder(page)!r}",
    )
    s.check(not composer(page).is_disabled(), "composer disabled on a text decision")
    # An option answer with none open? Not possible from the page. Answer with words.
    submit(page, "I press the attack.\n!none")
    wait_idle(page)
    s.check(
        page.locator(".game-decision:visible", has_text="conflict").count() == 0,
        "decision panel stayed after the answer",
    )
    s.check(
        "Paused:" in clean(page.inner_text(".game-transcript")),
        "no pause line for the answered decision",
    )
    s.shot(page, "conflict-answered")

    # 4. Refused master calls do not kill the turn; the refusal reaches the log.
    submit(
        page,
        "I do something the rules refuse.\n!reveal target_id=nowhere\n!reveal target_id=elena",
    )
    wait_idle(page)
    last = log()[-2]
    s.check(
        any("REFUSED" in c[2] for c in last["calls"]),
        f"master refusal not surfaced: {last['calls']}",
    )

    # 5. The master crashes before anything lands: the draft is kept and the state unchanged.
    before = len(bubbles(page))
    submit(page, "I try something.\n!crash")
    page.wait_for_timeout(1500)
    wait_idle(page)
    s.shot(page, "crash-notified")
    s.check(
        composer(page).input_value().startswith("I try something."),
        f"draft lost after a crash: {composer(page).input_value()!r}",
    )
    s.check(len(bubbles(page)) == before, "a crashed turn left bubbles")
    composer(page).fill("")

    # 6. A narrator that fails does not cost the turn: it lands with no prose.
    submit(page, 'I look around.\n!fail narrator\n!drive actor_id=player goal="Get out"')
    page.wait_for_timeout(1500)
    wait_idle(page)
    s.check("I look around." in clean(page.inner_text(".game-transcript")), "the turn was lost")
    s.check(not composer(page).is_disabled(), "composer stuck after a narrator failure")
    s.shot(page, "narrator-failed")
    composer(page).fill("")

    # 7. A narrator answering garbage once is re-prompted and the turn lands.
    submit(page, "I look again.\n!bad narrator")
    wait_idle(page)
    s.check(len(bubbles(page)) > before, "a re-prompted narrator did not land the turn")
    spoken = [entry for entry in log() if entry["role"] == "narrator"]
    s.check("refused" in spoken[-1]["prompt"], "the retry prompt did not carry the refusal")

    # 8. Enter sends on a fine pointer; Shift+Enter is a newline.
    composer(page).fill("line one")
    composer(page).press("Shift+Enter")
    composer(page).type("line two")
    s.check("\n" in composer(page).input_value(), "shift+enter did not add a newline")
    composer(page).press("Enter")
    started = False
    for _ in range(50):
        if working(page).count() > 0 or composer(page).is_disabled():
            started = True
            break
        page.wait_for_timeout(50)
    s.check(started, "enter did not send")
    wait_idle(page)
    s.check("line one\nline two" in "\n".join(bubbles(page)), "multi-line prompt not shown whole")

    # 9. The journal and the scene tab.
    open_drawer(page)
    page.get_by_role("tab", name="journal").click()
    page.wait_for_timeout(400)
    s.shot(page, "journal")
    journal = clean(drawer_text(page))
    s.check(
        "chronicle" in journal.lower() and "turn 1:" in journal,
        f"journal missing turns: {journal[:200]}",
    )
    page.locator(".q-expansion-item").first.click()
    page.wait_for_timeout(400)
    s.shot(page, "journal-open")
    page.get_by_role("tab", name="scene").click()

    # 10. Offer the way on: banner and action button.
    submit(page, "I have what I came for.\n!next_scene")
    wait_idle(page)
    s.shot(page, "way-offered")
    text = clean(page.inner_text("body"))
    s.check(
        page.locator(".game-banner:visible", has_text="way on").count() == 1,
        "way-on banner missing",
    )
    action = page.locator(".game-banner button", has_text="Move on")
    s.check(action.count() == 1 and action.is_visible(), "Move on button missing")
    # Move on: take_way_on -> master calls next_scene pursuit -> worldsmith -> arrival.
    composer(page).fill('Down the stair.\n!next_scene pursuit="Down the stair."')
    action.click()
    s.check(wait_working(page), "move on did not start a turn")
    seen_phases: set[str] = set()
    for _ in range(60):
        seen_phases.add(placeholder(page))
        if not composer(page).is_disabled():
            break
        page.wait_for_timeout(200)
    wait_idle(page)
    s.note(f"phases during the crossing: {seen_phases}")
    s.check(any("Worldsmith" in p for p in seen_phases), "worldsmith phase never shown")
    s.shot(page, "crossed")
    s.check("QA Scene 1" in clean(page.inner_text(".game-scene")), "scene header did not change")
    s.check("QA Scene 1" in clean(drawer_text(page)), "trail did not grow")
    s.check(
        "New scene: QA Scene 1" in " ".join(cards(page)), f"scene card missing: {cards(page)[-3:]}"
    )
    s.check(
        page.locator(".game-banner:visible", has_text="way on").count() == 0,
        "banner stayed after the crossing",
    )
    s.check(
        "(the story goes on)" in clean(page.inner_text(".game-transcript")), "story cause missing"
    )
    s.check("Luck" in clean(drawer_text(page)), "sheet gone after the crossing")

    # 11. A complication at the same place.
    submit(page, 'I wait.\n!next_scene complication="A second crew breaks in."')
    wait_idle(page)
    s.shot(page, "complicated")
    s.check("QA Scene 2" in clean(page.inner_text(".game-scene")), "complication did not install")

    # 12. The worldsmith fails: the way is unwritten, the game goes on.
    submit(page, 'I leave.\n!fail worldsmith\n!next_scene pursuit="Out."')
    wait_idle(page)
    s.shot(page, "unwritten")
    s.check(
        "could not be written" in " ".join(cards(page)),
        f"unwritten card missing: {cards(page)[-2:]}",
    )
    s.check(not composer(page).is_disabled(), "composer stuck after an unwritten way")

    # 13. Reload mid-turn: the live turn shows; the draft survives.
    submit(page, 'I take my time.\n!slow narrator\n!drive actor_id=player goal="Get out"')
    page.wait_for_timeout(800)
    composer(page).fill("a draft typed mid-turn") if not composer(page).is_disabled() else None
    page.reload()
    page.wait_for_timeout(1500)
    s.shot(page, "reload-mid-turn")
    body_text = clean(page.inner_text("body"))
    s.check(
        "is working" in placeholder(page) or working(page).count() > 0,
        "no live turn after a reload mid-turn",
    )
    s.check("I take my time." in body_text, "the live prompt bubble missing after reload")
    wait_idle(page, timeout=60)
    s.shot(page, "reload-settled")

    # 14. Draft survives a reload.
    composer(page).fill("a saved draft")
    page.wait_for_timeout(500)
    page.reload()
    page.wait_for_timeout(1500)
    wait_idle(page)
    s.check(
        composer(page).input_value() == "a saved draft",
        f"draft after reload: {composer(page).input_value()!r}",
    )
    composer(page).fill("")

    # 15. Scroll up, then another tab's turn lands: New activity button.
    page.locator(".game-transcript .q-scrollarea__container").evaluate("el => el.scrollTop = 0")
    page.wait_for_timeout(600)
    other = page.context.new_page()
    other.goto(GAME)
    other.wait_for_timeout(1200)
    submit(other, "I look about.")
    wait_idle(other)
    page.wait_for_timeout(1500)
    s.check(
        "I look about." in " ".join(bubbles(page)), "the other tab's turn did not reach this tab"
    )
    other.close()
    s.shot(page, "new-activity")
    new_activity = page.get_by_role("button", name="New activity")
    s.check(
        new_activity.is_visible(), "New activity button did not appear after a scrolled-up turn"
    )
    if new_activity.is_visible():
        new_activity.click()
        page.wait_for_timeout(500)
        s.check(not new_activity.is_visible(), "New activity button stayed after catching up")

    # 16. Sound toggle.
    sound = page.get_by_role("button", name="Sound")
    icon_before = sound.locator("i").inner_text()
    sound.click()
    page.wait_for_timeout(300)
    icon_after = sound.locator("i").inner_text()
    s.check(icon_before != icon_after, f"sound icon did not toggle: {icon_before} -> {icon_after}")
    sound.click()

    # 17. The narrator speaks for someone here, guessing an id from the name.
    submit(page, 'I ask the npc a question. [say qa-npc-2 "I answer you."]\n!none')
    wait_idle(page)
    s.check("I answer you." in bubbles(page), "spoken line missing")
    s.check(
        "QA Npc 2" in clean(page.inner_text(".game-transcript")),
        "speaker name missing on the bubble",
    )
    s.shot(page, "spoken")
    # A wrong id: what the narrator is shown holds no ids at all.
    prompt = [e for e in log() if e["role"] == "narrator" and "WHO IS HERE" in e["prompt"]][-1]
    here = prompt["prompt"].split("# WHO IS HERE\n")[1].split("\n\n")[0]
    s.check(
        all(re.match(r"- .+\[[a-z0-9-]+\]", line) for line in here.strip().splitlines()),
        f"the narrator prompt shows no speaker ids: {here!r}",
    )

    # 18. Restart: dialog, keep playing, then confirm.
    page.locator(".q-header button").last.click()
    page.get_by_text("Restart this game").click()
    page.wait_for_timeout(400)
    s.shot(page, "restart-dialog")
    dialog = clean(page.locator(".q-dialog").inner_text())
    s.check("turns are erased" in dialog, f"restart dialog text: {dialog}")
    page.get_by_role("button", name="Keep playing").click()
    page.wait_for_timeout(600)
    s.check(not page.locator(".q-dialog").is_visible(), "dialog stayed after keep playing")
    page.locator(".q-header button").last.click()
    page.get_by_text("Restart this game").click()
    page.get_by_role("button", name="Restart", exact=True).click()
    s.check(wait_working(page), "restart did not re-open the game")
    wait_idle(page)
    s.shot(page, "restarted")
    text = clean(page.inner_text(".game-transcript"))
    s.check(
        text.count("(the story begins)") == 1 and "QA Scene" not in text,
        "restart did not reset the transcript",
    )
    s.check("The Abbot's Study" in clean(page.inner_text(".game-scene")), "scene header not reset")

    # 19. Death: the game is over, the composer closes, the only way on is restart.
    submit(page, "I die.\n!kill target_id=player")
    wait_idle(page) if False else page.wait_for_timeout(3000)
    s.shot(page, "dead")
    text = clean(page.inner_text("body"))
    s.check("You died." in text, "over label missing")
    s.check(composer(page).is_disabled() and send(page).is_disabled(), "composer open after death")
    s.check("You are dead" in " ".join(cards(page)), "death card missing")
    page.reload()
    page.wait_for_timeout(1500)
    s.check(composer(page).is_disabled(), "composer open after death and a reload")
    page.locator(".q-header button").last.click()
    page.get_by_text("Restart this game").click()
    page.get_by_role("button", name="Restart", exact=True).click()
    wait_idle(page, timeout=30)
    s.check(not composer(page).is_disabled(), "composer closed after a restart from death")

    # 20. Prose with markdown and html: the chat shows it verbatim, the journal renders markdown.
    submit(page, "I say **bold** and *soft* and <b>tag</b> and <script>alert(1)</script>.\n!none")
    wait_idle(page)
    chat = bubbles(page)[-2]
    s.note(f"chat bubble: {chat!r}")
    s.check("**bold**" in chat and "<b>tag</b>" in chat, "chat did not show the text verbatim")
    open_drawer(page)
    page.get_by_role("tab", name="journal").click()
    page.wait_for_timeout(400)
    page.locator(".q-expansion-item").first.click()
    page.wait_for_timeout(400)
    s.shot(page, "journal-markdown")
    journal_html = page.locator(".q-expansion-item").first.inner_html()
    s.note(
        f"journal html sample: {journal_html[journal_html.find('bold') - 60 : journal_html.find('bold') + 60]!r}"  # noqa: E501
    )
    s.check(
        "<strong>bold</strong>" not in journal_html,
        "the journal renders the narrator's text as markdown",
    )
    s.check("<script>" not in journal_html, "the journal lets script tags through")
    page.get_by_role("tab", name="scene").click()

    # 21. A long unbroken word: the bubble must not overflow the page.
    long_word = "x" * 300
    submit(page, f"I shout {long_word}.\n!none")
    wait_idle(page)
    s.shot(page, "long-word")
    s.check(
        page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"),
        "a long word makes the page scroll sideways",
    )
    overflow = page.evaluate(
        "Array.from(document.querySelectorAll('.q-message-text-content')).some(e => e.scrollWidth > e.clientWidth + 2)"  # noqa: E501
    )
    s.check(not overflow, "a long word overflows its bubble")


run("loner", body)
