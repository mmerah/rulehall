# Rulehall

[![A two-minute demo: one turn in each rule set, a Pokemon battle, and a scenario written from a PDF](docs/demo/demo.gif)](docs/demo/demo.mp4)

Click the demo to watch it in full quality.

A browser game for solo tabletop role-playing. You type what your character does. Three AI roles and a rules engine play the rest. A fourth, the opponent, plays the other side of a battle when a setting turns it on.

- The **game master** applies the rules. It rolls through the engine, changes the world through tools, and ends each turn by telling the narrator what matters.
- The **narrator** writes the prose you read. It only ever sees what your character has learned, so it cannot spoil a secret.
- The **worldsmith** writes the opening scene and grows the world as you play: the next place, a complication, a new face.

Python code owns the rules. It rolls the dice, validates every change the game master asks for, keeps the game state and saves it. The AI roles never touch the save.

Four rule sets ship with the app:

- **Loner 3e** plays in scenes. An oracle answers yes or no with a twist, and you decide where the story goes next.
- **Tunnel Goons** is a dungeon crawl on a map. You walk, fight and rest, and the map grows when you reach its edge.
- **24XX** is science fiction in scenes. One skill die, three outcome bands, and gear that breaks to soften a hit.
- **Pokemon** is a region on a map. Skill checks roll a d20, and battles play in the Pokemon Showdown simulator and its battle view.

A scenario is a backdrop, a premise, a scope and an opening scene, written by the worldsmith from your prompt or a document you drop in. A character is one sheet per rule set. Both come with the game or you make your own in the app. Each rule set plays a pack: its own tables, or a full kit with a backdrop, names, traits and adventure seeds. Loner ships twelve genre packs, and you can write a pack of your own from the **New pack** page.

Play runs on the AI subscription you already have. Scene art is optional, off by default, with its own provider key.

## Start the app

You need `uv` and an AI command-line program (Claude, Codex). The default settings use the `claude` command.

1. Install the project.

   ```bash
   uv sync
   ```

2. Start the app.

   ```bash
   uv run rulehall
   ```

3. Open the address that the command shows.

Open Settings in the app to change the AI commands or other settings. The keys are written
to `.env` and apply at once. The server address and port apply the next time the server starts.

A role can play over a completion API instead of a command. Under Roles, set its provider to `openrouter` or `local` and name a model that supports tool calls, such as `deepseek/deepseek-v4-flash-0731` on OpenRouter or a tool-capable model served by Ollama at the local default `http://localhost:11434/v1`. The provider's base URL and key live under Providers. The narrator and the worldsmith then answer in one request each. The master plays its tools in the app's own process.

Your files live next to the app:

- `user/characters/<id>/<engine>.json`: one sheet per rule set.
- `user/scenarios/<id>/world.json`: the opening the worldsmith wrote.
- `packs/<engine>/<id>.json`: packs you wrote in the app. Edit the file to change a pack. Shipped packs are read-only.

The shipped `scenarios/` and `characters/` are read-only, and their ids win over yours.

Saves carry no version. A save from before a change in the stored shape is stale: the launcher skips it with a warning and never migrates or deletes it.

## Pokemon battles

The Pokemon rule set runs its battles in Pokemon Showdown, a Node program.

1. Install Node 22.

2. Install the simulator, its battle view and the sprites.

   ```bash
   npm --prefix src/rulehall/engines/pokemon/showdown run setup
   ```

The setup downloads about 220 MB and takes a few minutes. The sprites cover every species of the dex. The game needs no network after setup. The dex export (`npm --prefix src/rulehall/engines/pokemon/showdown run export-dex`) and the pack export (`npm --prefix src/rulehall/engines/pokemon/showdown run export-packs`) need the network and are only for maintainers.

Rulehall is a free fan project, not affiliated with Nintendo, Creatures Inc., Game Freak or The Pokemon Company. The sprites, music and Pokedex entries belong to them. Read [docs/POKEMON.md](docs/POKEMON.md#licence-and-attribution) for what comes from where.

## Play from another device

The app listens only on its own computer by default. Tailscale lets your other devices reach it, at home or away. You need a free Tailscale account.

1. Install Tailscale on the computer that runs the app, then log in. On Linux:

   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```

2. Add this line to `.env`, then start the app again.

   ```bash
   SERVER__HOST=0.0.0.0
   ```

3. Find the Tailscale name of the computer. It is on the first line.

   ```bash
   tailscale status
   ```

4. Install the Tailscale app on the other device. Log in with the same account.

5. On that device, open `http://<name>:8080`. If the name does not work, use the `100.x.x.x` address from step 3.

The app has no login. Every device that can reach the port can play and can change every setting, keys and provider addresses included. The page never shows a stored key. Do not open the port to the internet.

## Run in Docker

Each push to `master` publishes `ghcr.io/mmerah/rulehall` (tags `latest` and `sha-<commit>`). The image holds Python, Node, Pokemon Showdown with its sprites, and the `claude` and `codex` commands.

```bash
docker run -d -p 8080:8080 \
  -v rulehall-data:/data -v rulehall-home:/home/rulehall \
  -e CLAUDE_CODE_OAUTH_TOKEN=<token> \
  ghcr.io/mmerah/rulehall
```

- `/data` holds `.env`, `saves/`, `packs/` and `user/`.
- `/home/rulehall` holds the logins of the AI commands.
- Make the token with `claude setup-token` on a computer that has a browser.
- For OpenRouter, set `PROVIDERS__OPENROUTER__API_KEY`, or set the key on the Settings page.
- `GET /status` answers `{"busy": <bool>, "idle_seconds": <float>}`. `busy` is true while a turn or a scenario or pack is being written.

## Project information

- Read [CLAUDE.md](CLAUDE.md) for development rules and checks.
- Read [SECURITY.md](SECURITY.md) to report a vulnerability.
- Read [docs/LONER-3E.md](docs/LONER-3E.md) for sources, license, attribution, and implementation differences.
- Read [docs/TUNNEL-GOONS.md](docs/TUNNEL-GOONS.md) for sources, license, attribution, and implementation differences.
- Read [docs/24XX.md](docs/24XX.md) for sources, license, attribution, and implementation differences.
- Read [docs/POKEMON.md](docs/POKEMON.md) for sources, licenses, and the rules we chose.

## License

The code is MIT, © 2026 Mounir Merah. Read [LICENSE](LICENSE). The rule sets below keep their own licenses.

Loner v.3.0 © 2025 Roberto Bisceglie, CC BY-SA 4.0 — attribution in the [Loner notes](docs/LONER-3E.md).

Tunnel Goons is © Nate Treme, released under a Creative Commons 4.0 International License — attribution in the [Tunnel Goons notes](docs/TUNNEL-GOONS.md).

24XX rules (v1.4) are CC BY Jason Tocci — attribution in the [24XX notes](docs/24XX.md).
