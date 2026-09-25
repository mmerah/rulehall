# QA harness

Runs the real app with the three AI roles replaced by scripts, then drives it in Chromium with Playwright. It is not a test suite: it starts processes, takes screenshots, and writes a report per scenario to `qa/shots/<scenario>/` (ignored by git).

## Run it

```bash
export QA_WORK=/tmp/rulehall-qa-work
qa/run_all.sh                 # every scenario, a fresh server each
qa/run_all.sh loner mobile    # some of them
qa/serve.sh                   # only the server, at http://localhost:8123 (/qa/log lists spawns)
qa/serve.sh --art             # the same, with placeholder 16:9 scene art drawn offline
```

`--art` turns media on and swaps the provider call for a gradient keyed off the prompt, so the scene header can be looked at with a picture in it without a key or a network.

The harness runs offline, so every page logs a `console[error]` for the `fonts.googleapis.com` stylesheet. It is expected and harmless: the palette names a local fallback for each face.

Playwright comes from the project venv (the `qa` dependency group). Chromium comes from the Playwright install; point `PLAYWRIGHT_BROWSERS_PATH` at another one if this machine needs it.

Scenarios: `home`, `loner`, `goons`, `24xx`, `settings`, `create`, `mobile`, `burst` (double sends, huge text, reload storms, two tabs), `requests` (a world-growth request ends the turn, on every engine), `endure` (eight turns and reloads on each of the three games, then a `long` run of 30), `pokemon` (the Team tab, a row dialog, the map, ten turns and a wild battle), and `gallery` (every page on a desktop, a tablet and a phone, for a look at the design).

`endure` and `pokemon` note each turn's websocket traffic from the page's side (`SocketTraffic` in `drive.py`): `timing <run> turn=<n> frames=… kb=… elements=…`, where `elements` counts the element entries of each outbox flush (NiceGUI's `update` message), deletions included, so it varies with `QA_DELAY`. `endure` ends with `idle kb=… frames=…`, five quiet seconds after the last turn. Read them from the output or from `qa/shots/<scenario>/report.json`:

```bash
qa/run_all.sh endure pokemon
jq -r '.notes[] | select(startswith("timing") or startswith("idle"))' qa/shots/{endure,pokemon}/report.json
```

## The scripted roles

The master reads PLAYER ACTION from its prompt. Lines starting with `!` are scripts:

| Script | Effect |
| --- | --- |
| `!roll what="Try the door" actor_id=player question="Does it give?"` | calls that tool (values parse as JSON, else strings; quote lists: `item_ids='["torch"]'`) |
| `!none` | no tool call |
| `!crash` / `!refuse` | the master fails with `OSError` / `Refusal` |
| `!fail narrator`, `!bad worldsmith`, `!slow narrator` | that role's next ask fails (its retry too), answers garbage once so the retry lands, or stalls 6 s |

Plain words with no script get one roll. The narrator echoes its prompt as `[narration]` and `[happened]` lines, so a screenshot shows what the page was told; `[say <id> "words"]` adds a spoken line. The worldsmith answers every request with a small valid draft.

Each role reads its prompt by section, and a section is a `# NAME` heading in the prompt the app renders. A prompt that stops naming its sections that way drops every script silently.
