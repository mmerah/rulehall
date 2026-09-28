"""The Whispering Vault (Loner 4e): the full life of one game page."""

import json
import os
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
    close_until,
    composer,
    decision,
    drawer_text,
    log,
    open_drawer,
    placeholder,
    reach_breather,
    run,
    send,
    submit,
    take_breather,
    use_row_option,
    wait_idle,
    wait_working,
    working,
)

GAME = BASE + "/game/whispering-vault/kael"
WORK = Path(os.environ.get("QA_WORK", "/tmp/rulehall-qa-work"))


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

    s.check("Twist Counter" in side, f"sheet missing the twist counter: {side[:300]}")

    # 1. A plain turn: the default question to the oracle.
    s.check(submit(page, "I search the desk."), "no working indicator after submit")
    s.check(composer(page).is_disabled(), "composer stayed enabled during the turn")
    wait_idle(page)
    s.shot(page, "turn-ask")
    s.check(
        any("Does the player get what they want?" in c for c in cards(page)),
        f"no oracle card: {cards(page)}",
    )
    s.check(composer(page).input_value() == "", "composer not cleared after an accepted turn")

    # 1b. The player asks the oracle: the card shows their own words, rolled as they wrote them.
    ask = page.locator(".game-banner button", has_text="Ask the oracle")
    s.check(ask.is_visible(), "no Ask the oracle button in an open scene")
    s.check(send(page).is_visible(), "the send button hides beside Ask the oracle")
    composer(page).fill("Is the abbot's desk unlocked?")
    ask.click()
    s.check(wait_working(page), "Ask the oracle did not start a turn")
    wait_idle(page)
    s.shot(page, "player-asks")
    s.check(
        any("Is the abbot's desk unlocked?" in c for c in cards(page)),
        f"the player's question is not on the card: {cards(page)[-2:]}",
    )
    master = [e for e in log() if e["role"] == "master"][-1]
    s.check("# THE PLAYER ASKS" in master["prompt"], "the master prompt shows no THE PLAYER ASKS")
    s.check(
        any(c[0] == "ask" and c[1].get("question") is None for c in master["calls"]),
        f"the master did not pass a null question: {master['calls']}",
    )
    s.check(composer(page).input_value() == "", "composer not cleared after asking")

    # 2. Someone who may turn up arrives, and the player takes something: cards and sheet.
    s.check("Learn what the abbey sealed below" in side, f"scene goal missing: {side[:300]}")
    submit(
        page,
        "Tomas shuffles in.\n!enter target_id=tomas\n!change_tags actor_id=player kind=gear gained='[\"Old Key\"]'",  # noqa: E501
    )
    wait_idle(page)
    s.check(
        any("Brother Tomas arrives" in c for c in cards(page)),
        f"arrival card missing: {cards(page)[-3:]}",
    )
    s.check("Old Key" in clean(drawer_text(page)), "gear not on the sheet")
    s.shot(page, "turn-enter")

    # 3. A Harm & Luck exchange: cited tags on the card, luck moves, and no pause follows.
    submit(
        page,
        'I fight Mara.\n!ask question="Do I force her back?" opponent_id=mara'
        " helps='[\"Pry Bar\"]' hinders='[\"Knows the Catalogue\"]'",
    )
    wait_idle(page)
    s.shot(page, "conflict")
    exchange = [c for c in cards(page) if "Do I force her back?" in c]
    s.check(bool(exchange), f"no exchange card: {cards(page)[-3:]}")
    s.check(
        bool(exchange) and "+Pry Bar, -Knows the Catalogue" in exchange[-1],
        f"cited tags missing: {exchange}",
    )
    s.check(bool(exchange) and "Luck" in exchange[-1], f"no luck line: {exchange}")
    decisions = page.locator(".game-decision:visible")
    s.check(decisions.count() == 0, "a conflict opened a decision")
    s.check(placeholder(page) == "What do you do?", f"conflict placeholder: {placeholder(page)!r}")
    # With one opponent, an ask that names none is the next exchange.
    submit(page, 'I press on.\n!ask question="Do I drive her to the wall?"')
    wait_idle(page)
    master = [e for e in log() if e["role"] == "master"][-1]
    s.check("# CONFLICT" in master["prompt"], "the master prompt in a conflict shows no CONFLICT")
    lone = [c for c in cards(page) if "Do I drive her to the wall?" in c]
    s.check(bool(lone) and "Luck" in lone[-1], f"the lone opponent got no exchange: {lone}")
    open_drawer(page)
    goal_opens = page.locator(".game-drawer .game-opens", has_text="Goal").count()
    s.check(goal_opens == 0, "Move on is offered during a conflict")
    use_row_option(page, "Conflict", "Break away")
    s.shot(page, "broke-away")
    s.check(
        any("Breaks away" in c for c in cards(page)),
        f"break away card missing: {cards(page)[-3:]}",
    )
    submit(page, "I catch my breath.\n!none")
    wait_idle(page)
    master = [e for e in log() if e["role"] == "master"][-1]
    s.check("name the cost" in master["prompt"], "the master was not told to name the cost")
    # A closed path: the dead end is one ask of the SRD's question, and it is settled.
    submit(
        page,
        'The trail is cold.\n!ask question="Does something or someone point toward a new way '
        'forward?"',
    )
    wait_idle(page)
    s.shot(page, "dead-end")
    s.check(
        any("point toward a new way forward?" in c for c in cards(page)),
        f"dead end card missing: {cards(page)[-3:]}",
    )
    master = [e for e in log() if e["role"] == "master"][-1]
    s.check("# SETTLED THIS SCENE" in master["prompt"], "the master prompt shows no SETTLED")

    # 4. A refused call does not kill the turn; the refusal reaches the log.
    submit(
        page,
        "I do something the rules refuse.\n!enter target_id=nowhere"
        "\n!close_scene reason=turning_point",
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

    # 9b. The Status Track: a protagonist defeat opens the player's pick, and the pick fills a
    # box with the SRD's tag for its column.
    marked = False
    for attempt in range(30):
        submit(
            page,
            f'I fight on.\n!ask question="Do I hold Mara off ({attempt})?" opponent_id=mara '
            'hinders=\'["Untrained", "Never Walks Away"]\'',
        )
        wait_idle(page)
        pick = decision(page).filter(has_text="lasting mark")
        if pick.count():
            s.shot(page, "status-pick")
            pick.locator("button", has_text="Physical").click()
            wait_working(page)
            wait_idle(page)
            marked = True
            break
    s.check(marked, "no protagonist defeat in 30 exchanges")
    side = clean(drawer_text(page))
    s.check("Status" in side and "Hurt" in side, f"no status on the sheet: {side[:400]}")
    narrator = [e for e in log() if e["role"] == "narrator"][-1]
    s.check("Hurt (1/3)" in narrator["prompt"], "the narrator's sheet shows no status")

    # 9c. Move on: the player leaves the scene from its panel; the transition rolls.
    use_row_option(page, "Goal", "Move on")
    s.shot(page, "moved-on")
    s.check(
        any("Scene closes: moved on" in c for c in cards(page)),
        f"no move-on close card: {cards(page)[-3:]}",
    )

    # 10. Close the scene: the engine rolls the transition and hands over. A dramatic scene is
    # written at once; the dice are seeded per game, so close until a quiet one opens the breather.
    before = clean(page.inner_text(".game-scene"))
    submit(page, 'I have what I came for.\n!close_scene reason=resolved\n!direct text="He has it."')
    seen_phases: set[str] = set()
    for _ in range(60):
        seen_phases.add(placeholder(page))
        if not composer(page).is_disabled():
            break
        page.wait_for_timeout(200)
    wait_idle(page, timeout=60)
    s.shot(page, "closed")
    closes = [c for c in cards(page) if "Scene closes: resolved" in c]
    s.check(bool(closes), f"close card missing: {cards(page)[-3:]}")
    if "Next: dramatic" in closes[-1]:
        s.check(any("Worldsmith" in p for p in seen_phases), "worldsmith phase never shown")
        after = clean(page.inner_text(".game-scene"))
        s.check("QA Scene" in after and after != before, "no dramatic scene")
        s.check(
            "(the story goes on)" in clean(page.inner_text(".game-transcript")),
            "story cause missing",
        )
    s.check(reach_breather(page), "no breather after eight closes")
    s.shot(page, "breather")
    s.check(page.locator(".game-composer-option:visible").count() == 1, "composer banner missing")
    s.check(not send(page).is_visible(), "the send button shows beside the breather")
    s.check(
        page.locator(".game-banner button", has_text="Take the breather").count() == 1,
        "no Take the breather banner",
    )
    # Recover: the Status row frames the quiet scene around rest; it clears a box.
    use_row_option(page, "Status", "Recover")
    s.shot(page, "quiet")
    scene = clean(page.inner_text(".game-scene"))
    side = clean(drawer_text(page))
    s.check("quiet scene" in side.lower(), f"no quiet scene panel: {side[:300]}")
    s.check("Luck 6/6" in side, f"luck not refilled: {side[:300]}")
    s.check("Hurt" not in side, f"the quiet scene cleared no status box: {side[:300]}")
    s.check(
        any("New scene: QA Scene" in c for c in cards(page)), f"quiet card missing: {cards(page)}"
    )
    s.check(send(page).is_visible(), "the send button did not come back after the breather")

    # 11. A turning point closes the quiet scene into a dramatic one, with no die, once the
    # player has acted there (Recover is a pick, not an action).
    submit(page, 'I bind the wound.\n!direct text="He rests."')
    wait_idle(page, timeout=60)
    submit(page, 'Trouble finds me.\n!close_scene reason=turning_point\n!direct text="Boots."')
    wait_idle(page, timeout=60)
    s.shot(page, "turning-point")
    s.check(
        any("Scene closes: turning point. Next: dramatic" in c for c in cards(page)),
        f"turning point card missing: {cards(page)[-3:]}",
    )
    s.check(clean(page.inner_text(".game-scene")) != scene, "the turning point installed nothing")

    # 12. The worldsmith fails: the next scene is unwritten, the game goes on, and the next
    # played turn asks again with no new die (or, after a quiet roll, the breather is retried).
    submit(page, 'I leave.\n!fail worldsmith\n!close_scene reason=blocked\n!direct text="Out."')
    wait_idle(page, timeout=60)
    if page.locator(".game-banner button", has_text="Take the breather").count():
        take_breather(page, 'I hide.\n!direct text="He hides."')
    s.shot(page, "unwritten")
    s.check(
        "could not be written" in " ".join(cards(page)),
        f"unwritten card missing: {cards(page)[-2:]}",
    )
    s.check(not composer(page).is_disabled(), "composer stuck after an unwritten scene")
    if page.locator(".game-banner button", has_text="Take the breather").count():
        take_breather(page, 'I hide again.\n!direct text="He hides."')
    else:
        submit(page, "I wait.\n!none")
        wait_idle(page, timeout=60)
    s.check(
        len([c for c in cards(page) if "Scene closes: blocked" in c]) == 1,
        "the retried write rolled the transition again",
    )
    s.shot(page, "rewritten")

    # 12b. A Meanwhile: the world's turn off screen, told on one cutaway card of who moved;
    # the dice are seeded per game, so close until each follow-up has played.
    for follow_up in ("quiet", "dramatic"):
        closed = close_until(page, f"Next: meanwhile, then {follow_up}", tries=24)
        s.check(bool(closed), f"no meanwhile, then {follow_up} in 24 closes")
        if not closed:
            continue
        s.shot(page, f"meanwhile-{follow_up}")
        s.check(
            any("Does an ally or wildcard act independently?" in c for c in cards(page)),
            f"no ally question card: {cards(page)[-4:]}",
        )
        s.check(
            any("Meanwhile:" in c for c in cards(page)),
            f"no cutaway card: {cards(page)[-4:]}",
        )
        narrated = " ".join(e["prompt"] for e in log() if e["role"] == "narrator")
        s.check("act independently" not in narrated, "the narrator read the ally question")
        if follow_up == "quiet":
            s.check(
                page.locator(".game-banner button", has_text="Take the breather").count() == 1,
                "no breather after a quiet meanwhile",
            )
            take_breather(page, 'I lie low.\n!direct text="He lies low."')
            quiet = [e for e in log() if e["role"] == "worldsmith"][-1]
            s.check("Off screen:" in quiet["prompt"], "the quiet scene was not told what moved")
        else:
            s.check(
                any("New scene: QA Scene" in c for c in cards(page)[-3:]),
                f"no dramatic scene after the meanwhile: {cards(page)[-3:]}",
            )

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
    npc = re.search(r"QA Scene (\d+)", clean(page.inner_text(".game-scene")))
    speaker = f"qa-npc-{npc.group(1) if npc else 0}"
    submit(page, f'I ask the npc a question. [say {speaker} "I answer you."]\n!none')
    wait_idle(page)
    s.check("I answer you." in bubbles(page), "spoken line missing")
    s.check(
        f"QA Npc {npc.group(1) if npc else 0}" in clean(page.inner_text(".game-transcript")),
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

    # 22. The end of the adventure, with a player-made character: Play on, then a confirmed end,
    # the growth, the Living World card, the game over, and the grown sheet on disk.
    sheet = WORK / "characters" / "mira" / "loner4e.json"
    kael = json.loads((WORK / "characters" / "kael" / "loner4e.json").read_text())
    kael["id"] = "mira"
    kael["person"]["name"] = "Mira"
    sheet.parent.mkdir(parents=True, exist_ok=True)
    sheet.write_text(json.dumps(kael))
    page.goto(BASE + "/game/whispering-vault/mira")
    wait_idle(page)
    ending = 'It is done.\n!end_adventure why="The vault is found."'
    submit(page, ending)
    wait_idle(page)
    s.shot(page, "ending-decision")
    s.check(
        "end here: The vault is found. End it, or play on?" in clean(page.inner_text("body")),
        "no ending decision",
    )
    s.check(composer(page).is_disabled(), "words can answer the ending decision")
    page.locator(".game-decision button:visible", has_text="Play on").click()
    s.check(wait_working(page), "Play on did not start a turn")
    wait_idle(page)
    s.shot(page, "played-on")
    played_on = page.locator(".game-decision:visible").count() == 0
    s.check(played_on, "Play on left the decision")
    use_row_option(page, "The adventure", "End the adventure")
    s.shot(page, "ending-by-player")
    s.check(
        "What did Mira learn?" in clean(page.inner_text("body")),
        "the sheet's End the adventure asked no growth",
    )
    submit(
        page,
        "Yes. Mira learned patience.\n!change_tags actor_id=player kind=skill"
        ' gained=\'["Patient Watcher"]\'\n!direct text="She has grown."',
    )
    for _ in range(150):
        if "The adventure is over." in clean(page.inner_text("body")) and not working(page).count():
            break
        page.wait_for_timeout(200)
    s.shot(page, "ended")
    s.check(
        any("The Living World" in c for c in cards(page)),
        f"no Living World card: {cards(page)[-2:]}",
    )
    s.check("The adventure is over." in clean(page.inner_text("body")), "no game-over label")
    s.check(composer(page).is_disabled(), "composer open after the end")
    grown = json.loads(sheet.read_text())["person"]
    s.check("Patient Watcher" in grown["tags"]["skill"], f"the growth is not on disk: {grown}")
    s.check(len(grown["living_world"]) == 3, f"no Living World lines on disk: {grown}")
    # A restart plays the grown sheet: the next scene's worldsmith reads what it carries forward.
    page.locator(".q-header button").last.click()
    page.get_by_text("Restart this game").click()
    page.get_by_role("button", name="Restart", exact=True).click()
    wait_idle(page, timeout=30)
    s.check("Patient Watcher" in clean(drawer_text(page)), "the restart forgot the growth")
    close_until(page, "Next:", tries=1)
    if page.locator(".game-banner button", has_text="Take the breather").count():
        take_breather(page, 'I rest.\n!direct text="She rests."')
    carried = [e for e in log() if e["role"] == "worldsmith"][-1]["prompt"]
    s.check(
        "# WHAT THE PROTAGONIST CARRIES FORWARD" in carried,
        "the next game's worldsmith does not see the Living World",
    )


run("loner", body)
