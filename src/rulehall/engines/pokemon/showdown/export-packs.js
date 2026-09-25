const fs = require("fs");
const path = require("path");
const { Dex } = require("pokemon-showdown");
const { fetchJson, pool } = require("./net");

const DEX = path.join(__dirname, "..", "dex.json");
const PACKS = path.join(__dirname, "..", "packs");
const POKEDEX_API = "https://pokeapi.co/api/v2/pokedex/";
const REGIONS = {
  srd: { dexes: ["kanto"] },
  johto: { dexes: ["original-johto"] },
  hoenn: { dexes: ["hoenn"] },
  sinnoh: { dexes: ["original-sinnoh"] },
  unova: { dexes: ["original-unova"] },
  kalos: { dexes: ["kalos-central", "kalos-coastal", "kalos-mountain"] },
  alola: { dexes: ["original-alola"], forme: "Alola" },
  galar: { dexes: ["galar"], forme: "Galar" },
  hisui: { dexes: ["hisui"], forme: "Hisui" },
  paldea: { dexes: ["paldea"], forme: "Paldea" },
};

const dex = Dex.forGen(9);
const exported = Object.keys(JSON.parse(fs.readFileSync(DEX, "utf8")).species).map((id) =>
  dex.species.get(id),
);

async function numbersOf(dexes) {
  const lists = await pool(dexes, (name) => fetchJson(POKEDEX_API + name));
  const nums = lists.flatMap((list) =>
    list.pokemon_entries.map((entry) => Number(entry.pokemon_species.url.split("/").at(-2))),
  );
  return [...new Set(nums)].sort((a, b) => a - b);
}

function idsOf(num, forme) {
  const formes = exported.filter((s) => s.num === num);
  const regional = forme ? formes.filter((s) => s.forme.startsWith(forme)) : [];
  const chosen = regional.length
    ? regional
    : formes.filter((s) => s.forme === "" || s.forme === "F");
  return chosen.map((s) => s.id);
}

async function main() {
  for (const [id, { dexes, forme }] of Object.entries(REGIONS)) {
    const file = path.join(PACKS, `${id}.json`);
    const pack = JSON.parse(fs.readFileSync(file, "utf8"));
    pack.species = (await numbersOf(dexes)).flatMap((num) => idsOf(num, forme));
    fs.writeFileSync(file, JSON.stringify(pack, null, 2) + "\n");
    console.log(`${id} ${pack.species.length} species`);
  }
}

main();
