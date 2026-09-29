# Demo video

These scripts make `docs/demo/demo.mp4` and `demo.gif`. They play the real app and record it in headless Chromium. By default, the master, the narrator and the worldsmith answer from `script.json`, so each take tells the same story. The rules, the dice, the Pokemon simulator and the scene art stay real. Nothing else is staged. `stage.html` draws the frame around the app, the cursor, the captions, the title words, the zoom and the end card.

## You need

- A working `.env` with scene art turned on (`MEDIA__ENABLED=true`). The settings need the provider keys even when the roles are scripted.
- The Pokemon simulator (`npm --prefix src/rulehall/engines/pokemon/showdown run setup`).
- `ffmpeg` with libx264 and `gifski` on your `PATH`.

## Make it

1. Start the app on a fresh copy of the data. The command wipes the folder you give it.

   ```bash
   uv run python qa/demo/serve.py /tmp/rulehall-demo/work
   ```

   Add `--live` to use the real AI roles from `.env` instead of the script.

2. In a second terminal, record one take.

   ```bash
   uv run python qa/demo/record.py /tmp/rulehall-demo
   ```

3. Cut the take into `docs/demo/`.

   ```bash
   uv run python qa/demo/cut.py /tmp/rulehall-demo
   ```

4. Watch `docs/demo/demo.mp4`. If a take goes wrong, stop the server, then do steps 1 to 3 again.

## How it works

- `record.py` saves each screencast frame with its time. A wait for the roles is marked to play 20 times faster (`FAST`), and a badge on the frame says so. A page load plays under a full-screen title word.
- `cut.py` gives each frame its played length, joins the frames at 60 fps, and stops at 1 minute (`LONGEST`).
- `roles.py` reads `script.json` and plays the roles:
  - `turns`: one entry for each turn of the master. `action` is the exact text that the player types, or the name of the option that the player clicks (`Commit`). `seed` sets the dice for the turn and for the rolls after it in that game. `calls` are the tool calls, run through the real rules. `narration` is what the narrator says after the turn.
  - `openings`: the first narration of each game, by scenario title.
  - `cues`: narration for a later narrator call, such as the end of a battle. The first `when` text found in the facts of the call wins.
  - `worldsmith`: the answer to each worldsmith call. The first `when` text found in the prompt wins.
- A narration line has a `speaker_id` (the id of a person in the scenario's `world.json`) or `null` for plain narration.
- A call with no script answer stops with an error that names the role. Nothing goes to an AI.
- If you change the words that `record.py` types, change the `action` in `script.json` too. If you change a `seed` or a call, run the take again and make sure that the narration still agrees with the dice.
- To change the scenes, edit the scene methods in `record.py`: `hook`, `loner`, `goons`, `relay`, `poke`, `create` and `end`.
