const fs = require("fs");
const path = require("path");
const { Dex, toID } = require("pokemon-showdown");
const { fetchJson, pool } = require("./net");

const OUTPUT = path.join(__dirname, "..", "dex.json");
const LEVELUP = /^(\d)L(\d+)$/;
const MACHINE = /^\dM$/;
// Pikachu-Alola is a cap, not a regional forme; Totem and Zen formes are battle-only.
const REGIONAL = /^(Alola|Galar|Hisui|Paldea)/;
const EXCLUDED = /Totem|Zen/;
const MARK = "BattlePokemonIconIndexes={";
const CLIENT = path.join(
  __dirname,
  "..",
  "..",
  "..",
  "..",
  "..",
  "vendor",
  "showdown",
  "js",
  "battledata.js",
);
const STATS = ["hp", "atk", "def", "spa", "spd", "spe"];
const EFFORTS = ["hp", "attack", "defense", "special-attack", "special-defense", "speed"];
const SPECIES_API = "https://pokeapi.co/api/v2/pokemon-species/";
const ABILITY_API = "https://pokeapi.co/api/v2/ability/";
const OFF_CHART = ["???", "Stellar"];

const dex = Dex.forGen(9);

function evolutionsLeft(species) {
  if (!species.evos.length) return 0;
  return 1 + Math.max(...species.evos.map((name) => evolutionsLeft(dex.species.get(name))));
}

function levelupOf(id) {
  const learnset = dex.species.getLearnsetData(id).learnset;
  const byGen = new Map();
  for (const [moveId, sources] of Object.entries(learnset)) {
    for (const source of sources) {
      const match = LEVELUP.exec(source);
      if (!match) continue;
      const gen = Number(match[1]);
      if (!byGen.has(gen)) byGen.set(gen, []);
      byGen.get(gen).push([Number(match[2]), moveId]);
    }
  }
  const gen = Math.max(...byGen.keys());
  const moves = byGen.get(gen);
  moves.sort((a, b) => a[0] - b[0] || a[1].localeCompare(b[1]));
  return { gen, moves };
}

function machinesOf(id) {
  const learnset = dex.species.getLearnsetData(id).learnset;
  return Object.keys(learnset)
    .filter((moveId) => learnset[moveId].some((source) => MACHINE.test(source)))
    .sort();
}

function exported(s) {
  return (
    s.num >= 1 &&
    (s.forme === "" ||
      s.forme === "F" ||
      (REGIONAL.test(s.forme) && !EXCLUDED.test(s.forme) && s.baseSpecies !== "Pikachu"))
  );
}

// The client's sheet index of each forme; a base forme's index is its number.
function iconIndexes() {
  if (!fs.existsSync(CLIENT)) {
    console.error("run the setup first");
    process.exit(1);
  }
  const text = fs.readFileSync(CLIENT, "utf8");
  const at = text.indexOf(MARK);
  if (at < 0) {
    console.error(`no ${MARK} in ${CLIENT}`);
    process.exit(1);
  }
  const start = at + MARK.length;
  const table = text.slice(start, text.indexOf("}", start));
  return new Map(
    [...table.matchAll(/([a-z0-9]+):(\d+)\+(\d+)/g)].map(([, id, a, b]) => [
      id,
      Number(a) + Number(b),
    ]),
  );
}

function newestEnglish(entries, what) {
  const english = entries.filter((entry) => entry.language.name === "en");
  if (!english.length) {
    console.error(`no English text for ${what}`);
    process.exit(1);
  }
  return english[english.length - 1].flavor_text.replace(/[\f\n\u00ad ]+/g, " ").trim();
}

async function speciesOf(num) {
  const { flavor_text_entries, varieties } = await fetchJson(SPECIES_API + num);
  return { entry: newestEnglish(flavor_text_entries, `species ${num}`), varieties };
}

// PokeAPI names an ability by its slug: "Dragon's Maw" is dragons-maw.
async function abilityText(name) {
  const slug = name
    .toLowerCase()
    .replace(/'/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  const { flavor_text_entries } = await fetchJson(ABILITY_API + slug);
  return newestEnglish(flavor_text_entries, `ability ${name}`);
}

async function evYieldOf(s, varieties) {
  // PokeAPI names the Paldean Tauros "tauros-paldea-<x>-breed".
  const variety =
    varieties.find((v) => v.pokemon.name.replace(/-/g, "").replace(/breed$/, "") === s.id) ??
    varieties.find((v) => v.is_default);
  const { stats } = await fetchJson(variety.pokemon.url);
  return EFFORTS.map((name) => stats.find((stat) => stat.stat.name === name).effort);
}

function typeChart() {
  const types = dex.types
    .all()
    .filter((type) => type.exists && !type.isNonstandard && !OFF_CHART.includes(type.name))
    .map((type) => type.name)
    .sort();
  const chart = {};
  for (const attacker of types) {
    const hit = (taken) =>
      types.filter((defender) => dex.types.get(defender).damageTaken[attacker] === taken);
    chart[attacker] = { strong: hit(1), weak: hit(2), none: hit(3) };
  }
  return chart;
}

async function main() {
  const species = {};
  const moveIds = new Set();
  const machineIds = new Set();
  let fallback = 0;
  const all = dex.species
    .all()
    .filter(exported)
    .sort((a, b) => a.num - b.num || a.name.localeCompare(b.name));
  const ids = new Set(all.map((s) => s.id));
  const icons = iconIndexes();
  const nums = [...new Set(all.map((s) => s.num))];
  const fetched = await pool(nums, speciesOf);
  const byNum = new Map(nums.map((num, index) => [num, fetched[index]]));
  const yields = await pool(all, (s) => evYieldOf(s, byNum.get(s.num).varieties));
  for (const [index, s] of all.entries()) {
    const { gen, moves } = levelupOf(s.id);
    if (gen !== 9) fallback++;
    for (const [, moveId] of moves) moveIds.add(moveId);
    const machines = machinesOf(s.id);
    for (const moveId of machines) machineIds.add(moveId);
    species[s.id] = {
      icon: icons.get(s.id) ?? s.num,
      name: s.name,
      types: s.types,
      base_stats: STATS.map((stat) => s.baseStats[stat]),
      ev_yield: yields[index],
      abilities: Object.entries(s.abilities)
        .filter(([key]) => key !== "H")
        .map(([, name]) => name),
      gender: s.gender || "",
      male_share: s.genderRatio.M,
      evos: s.evos.map(toID).filter((id) => ids.has(id)),
      evo_level: s.evoLevel ?? null,
      evo_type: s.evoType ?? null,
      // Kleavor's Black Augurite sits in evoCondition.
      evo_item: s.evoItem ?? (s.evoType === "useItem" ? s.evoCondition : null) ?? null,
      evo_condition: s.evoCondition ?? null,
      evo_move: s.evoMove ? toID(s.evoMove) : null,
      evolutions_left: evolutionsLeft(s),
      tags: s.tags,
      levelup: moves,
      machines,
      entry: byNum.get(s.num).entry,
    };
  }

  const moves = {};
  for (const id of [...new Set([...moveIds, ...machineIds])].sort()) {
    const move = dex.moves.get(id);
    moves[id] = {
      name: move.name,
      type: move.type,
      category: move.category,
      power: move.basePower,
      // Showdown writes `true` for a move that never misses.
      accuracy: move.accuracy === true ? null : move.accuracy,
      pp: move.noPPBoosts ? move.pp : Math.floor((move.pp * 8) / 5),
      tm: machineIds.has(id),
      text: move.shortDesc,
    };
  }
  const abilityNames = [...new Set(all.flatMap((s) => species[s.id].abilities))];
  const texts = await pool(abilityNames, abilityText);
  const abilities = Object.fromEntries(abilityNames.map((name, index) => [name, texts[index]]));
  const items = {};
  for (const item of dex.items.all()) {
    if (item.exists && item.shortDesc && !item.megaStone && !item.zMove) {
      items[item.id] = item.shortDesc;
    }
  }

  fs.writeFileSync(
    OUTPUT,
    JSON.stringify({ species, moves, abilities, items, type_chart: typeChart() }) + "\n",
  );
  console.log(
    `species ${all.length} moves ${Object.keys(moves).length} tms ${machineIds.size} fallback ${fallback} abilities ${abilityNames.length} items ${Object.keys(items).length}`,
  );
}

main();
