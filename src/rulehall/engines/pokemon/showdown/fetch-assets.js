const fs = require("fs");
const path = require("path");
const { Dex, toID } = require("pokemon-showdown");
const { pool } = require("./net");
const { species, moves } = require("../dex.json");
const avatars = require("../avatars.json");

const BASE_URL = "https://play.pokemonshowdown.com/";
const ITEM_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/";
const ITEM_IDS = [
  "poke-ball",
  "great-ball",
  "ultra-ball",
  "potion",
  "super-potion",
  "full-heal",
  "revive",
  "rare-candy",
  "oran-berry",
  "sitrus-berry",
  "cheri-berry",
  "chesto-berry",
  "pecha-berry",
  "rawst-berry",
  "aspear-berry",
  "lum-berry",
  "leftovers",
  "everstone",
  "silk-scarf",
  "charcoal",
  "mystic-water",
  "miracle-seed",
  "magnet",
  "never-melt-ice",
  "black-belt",
  "poison-barb",
  "soft-sand",
  "sharp-beak",
  "twisted-spoon",
  "silver-powder",
  "hard-stone",
  "spell-tag",
  "dragon-fang",
  "black-glasses",
  "metal-coat",
  "fairy-feather",
  "fire-stone",
  "water-stone",
  "thunder-stone",
  "leaf-stone",
  "moon-stone",
  "linking-cord",
  "sun-stone",
  "shiny-stone",
  "dusk-stone",
  "dawn-stone",
  "ice-stone",
  "black-augurite",
  "tart-apple",
  "sweet-apple",
  "cracked-pot",
  "auspicious-armor",
  "malicious-armor",
  "kings-rock",
  "dragon-scale",
  "up-grade",
  "dubious-disc",
  "protector",
  "electirizer",
  "magmarizer",
  "reaper-cloth",
  "prism-scale",
  "deep-sea-tooth",
  "deep-sea-scale",
  "sachet",
  "whipped-dream",
  "oval-stone",
  "razor-claw",
  "razor-fang",
];
const TM_TYPES = new Set(
  Object.values(moves)
    .filter((move) => move.tm)
    .map((move) => move.type.toLowerCase()),
);
const VENDOR = path.join(__dirname, "..", "..", "..", "..", "..", "vendor", "showdown");
const FILES = [
  "js/lib/jquery-1.11.0.min.js",
  "js/lib/html-sanitizer-minified.js",
  "js/battle-sound.js",
  "js/battledata.js",
  "data/pokedex-mini.js",
  "data/pokedex-mini-bw.js",
  "data/graphics.js",
  "data/pokedex.js",
  "data/moves.js",
  "data/abilities.js",
  "data/items.js",
  "data/teambuilder-tables.js",
  "js/battle-tooltips.js",
  "js/battle.js",
  "style/battle.css",
  "style/battle-log.css",
  "fx/gender-f.png",
  "fx/gender-m.png",
  "sprites/ani/substitute.gif",
  "sprites/ani-back/substitute.gif",
  "sprites/pokemonicons-sheet.png",
  "sprites/pokemonicons-pokeball-sheet.png",
];

// The 15 tracks BattleScene.rollBgm picks from, in data/graphics.js.
const MUSIC = [
  "dpp-trainer",
  "dpp-rival",
  "hgss-johto-trainer",
  "hgss-kanto-trainer",
  "bw-trainer",
  "bw-rival",
  "bw-subway-trainer",
  "bw2-kanto-gym-leader",
  "bw2-rival",
  "xy-trainer",
  "xy-rival",
  "oras-trainer",
  "oras-rival",
  "sm-trainer",
  "sm-rival",
];
// The base species whose forme cries have their own file, from specialBaseSpeciesCries in js/battledata.js.
const CRY_FORMES = [
  "calyrex",
  "kyurem",
  "cramorant",
  "indeedee",
  "lycanroc",
  "necrozma",
  "oinkologne",
  "oricorio",
  "slowpoke",
  "tatsugiri",
  "zygarde",
];

async function fetchFile(file, base = BASE_URL, optional = false, fallback = null) {
  const target = path.join(VENDOR, file);
  if (fs.existsSync(target)) return 0;
  const response = await fetch(base + file);
  // Upstream lacks twelve -f PNGs (Torchic front, Golbat back, ...); the view asks for them anyway.
  if (response.status === 404 && fallback) {
    fs.copyFileSync(path.join(VENDOR, fallback), target);
    return 1;
  }
  if (response.status !== 200) {
    if (optional) {
      console.log(`skipped ${response.status} ${base + file}`);
      return 0;
    }
    console.error(`${response.status} ${base + file}`);
    process.exit(1);
  }
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, Buffer.from(await response.arrayBuffer()));
  return 1;
}

function effectFiles(graphics) {
  const urls = [...graphics.matchAll(/url:'([^']+)'/g)].map((match) => `fx/${match[1]}`);
  const backdrops = listed(graphics, "BattleBackdropsFive").map((name) => `fx/${name}`);
  const gen6bgs = listed(graphics, "BattleBackdrops").map((name) => `sprites/gen6bgs/${name}`);
  const literals = graphics.match(/fx\/[a-z0-9-]+\.(png|jpg|gif)/g);
  const weather = graphics.match(/weather-[a-z]+\.(png|jpg)/g).map((name) => `fx/${name}`);
  return [...urls, ...backdrops, ...gen6bgs, ...literals, ...weather];
}

function listed(graphics, name) {
  const list = new RegExp(`var ${name}=\\[([^\\]]*)\\]`).exec(graphics)[1];
  return [...list.matchAll(/'([^']+)'/g)].map((match) => match[1]);
}

function spriteFiles(sprites) {
  const plain = ["sprites/gen5/substitute.png", "sprites/gen5-back/substitute.png"];
  const withFallback = [];
  for (const id of Object.keys(species)) {
    const spriteId = Dex.species.get(id).spriteid;
    plain.push(`sprites/gen5/${spriteId}.png`, `sprites/gen5-back/${spriteId}.png`);
    if (sprites[id].front) plain.push(`sprites/ani/${spriteId}.gif`);
    if (sprites[id].back) plain.push(`sprites/ani-back/${spriteId}.gif`);
    if (sprites[id].frontf) plain.push(`sprites/ani/${spriteId}-f.gif`);
    if (sprites[id].backf) plain.push(`sprites/ani-back/${spriteId}-f.gif`);
    if (sprites[id].frontf) {
      withFallback.push(
        [`sprites/gen5/${spriteId}-f.png`, `sprites/gen5/${spriteId}.png`],
        [`sprites/gen5-back/${spriteId}-f.png`, `sprites/gen5-back/${spriteId}.png`],
      );
    }
  }
  plain.push(...[...avatars.player, ...avatars.npc].map((name) => `sprites/trainers/${name}.png`));
  return [plain, withFallback];
}

function soundFiles() {
  return [
    ...MUSIC.map((name) => `audio/${name}.mp3`),
    ...Object.keys(species).map((id) => {
      const entry = Dex.species.get(id);
      const base = toID(entry.baseSpecies);
      const forme = entry.forme ? "-" + toID(entry.forme) : "";
      return `audio/cries/${base}${CRY_FORMES.includes(base) ? forme : ""}.mp3`;
    }),
  ];
}

function itemFiles() {
  return [
    ...ITEM_IDS.map((id) => `sprites/items/${id}.png`),
    ...[...TM_TYPES].map((type) => `sprites/items/tm-${type}.png`),
  ];
}

async function main() {
  let fetched = 0;
  for (const file of FILES) fetched += await fetchFile(file);
  const { BattlePokemonSprites } = require(path.join(VENDOR, "data", "pokedex-mini.js"));
  const graphics = fs.readFileSync(path.join(VENDOR, "data", "graphics.js"), "utf8");
  const [plainSprites, spritesWithFallback] = spriteFiles(BattlePokemonSprites);
  const plain = new Set([...effectFiles(graphics), ...plainSprites, ...soundFiles()]);
  fetched += sum(await pool([...plain], (file) => fetchFile(file)));
  fetched += sum(
    await pool(spritesWithFallback, ([file, fallback]) =>
      fetchFile(file, BASE_URL, false, fallback),
    ),
  );
  fetched += sum(await pool([...new Set(itemFiles())], (file) => fetchFile(file, ITEM_URL, true)));
  console.log(`fetched ${fetched} files`);
}

function sum(counts) {
  return counts.reduce((total, count) => total + count, 0);
}

main();
