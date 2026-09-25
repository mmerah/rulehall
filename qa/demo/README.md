# Demo video

These scripts make `docs/demo/demo.mp4`, `demo.gif` and `poster.jpg`. They play the real app with the real AI roles and record it in headless Chromium. Nothing is staged except the frame around the app, the cursor, the captions and the zoom, which `stage.html` draws.

## You need

- A working `.env`: the roles you play with, and scene art turned on (`MEDIA__ENABLED=true`).
- The Pokemon simulator (`npm --prefix src/rulehall/engines/pokemon/showdown run setup`).
- `ffmpeg` with libx264 and `gifski` on your `PATH`.
- Optional: a played 24XX save in `saves/silent-relay--kael.*`. Without it, the 24XX scene is skipped.

## Make it

1. Start the app on a fresh copy of the data. The command wipes the folder you give it.

   ```bash
   uv run python qa/demo/serve.py /tmp/rulehall-demo/work
   ```

2. In a second terminal, record one take. It takes about 5 minutes and plays 4 real turns.

   ```bash
   uv run python qa/demo/record.py /tmp/rulehall-demo
   ```

3. Cut the take into `docs/demo/`.

   ```bash
   uv run python qa/demo/cut.py /tmp/rulehall-demo
   ```

4. Watch `docs/demo/demo.mp4`. The AI writes new words on every take, so a take can go wrong. If it does, stop the server, then do steps 1 to 3 again.

## How it works

- `record.py` saves each screencast frame with its time. A slow AI turn is marked to play 7 times faster, and a badge on the frame says so.
- `cut.py` gives each frame its played length, joins the frames at 60 fps, and stops at 2 minutes.
- To change the story, edit the scene methods in `record.py`: `loner`, `goons`, `relay`, `poke` and `create`.
