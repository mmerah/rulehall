const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");
const { PNG } = require("pngjs");
const { fail } = require("./source");
const art = require("./overlay/art.json");
const { species, classes } = require("../data/character_options.json");
const { stat_blocks: statBlocks } = require("../data/bestiary.json");

const ARCHIVE_URL =
  "https://opengameart.org/sites/default/files/Dungeon%20Crawl%20Stone%20Soup%20Full_0.zip";
const SHA256 = "41b4dc79632be19c47bf4555fd61e949189bb4496771b72e2dec5715b2d7bab4";
const PACK_ROOT = "Dungeon Crawl Stone Soup Full/";
const TILE_SIZE = 32;
const SILHOUETTE_RGB = [24, 24, 32];
const ASSETS = path.join(__dirname, "..", "assets");
const END_OF_DIRECTORY = Buffer.from([0x50, 0x4b, 0x05, 0x06]);

async function download() {
  const response = await fetch(ARCHIVE_URL);
  fail(`${response.status} ${ARCHIVE_URL}`, response.ok ? [] : [response.statusText]);
  const archive = Buffer.from(await response.arrayBuffer());
  const digest = crypto.createHash("sha256").update(archive).digest("hex");
  fail("the tileset archive changed", digest === SHA256 ? [] : [digest]);
  return archive;
}

function* entries(zip) {
  const end = zip.lastIndexOf(END_OF_DIRECTORY);
  let offset = zip.readUInt32LE(end + 16);
  for (let index = 0; index < zip.readUInt16LE(end + 10); index++) {
    const method = zip.readUInt16LE(offset + 10);
    const size = zip.readUInt32LE(offset + 20);
    const nameLength = zip.readUInt16LE(offset + 28);
    const name = zip.toString("utf8", offset + 46, offset + 46 + nameLength);
    const local = zip.readUInt32LE(offset + 42);
    const start = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28);
    fail(`${name} compression`, [0, 8].includes(method) ? [] : [String(method)]);
    const raw = zip.subarray(start, start + size);
    yield [name, method === 8 ? zlib.inflateRawSync(raw) : raw];
    offset += 46 + nameLength + zip.readUInt16LE(offset + 30) + zip.readUInt16LE(offset + 32);
  }
}

function checkRows(title, table, expected) {
  fail(`${title} missing in art.json`, expected.filter((key) => !(key in table)));
  fail(`${title} unknown in art.json`, Object.keys(table).filter((key) => !expected.includes(key)));
}

function portraitIds() {
  return Object.entries(species).flatMap(([speciesId, entry]) => {
    const lineages = Object.keys(entry.subspecies ?? {});
    return lineages.length ? lineages.map((lineage) => `${speciesId}-${lineage}`) : [speciesId];
  });
}

function checkArt() {
  checkRows("species", art.species, portraitIds());
  checkRows("classes", art.classes, Object.keys(classes));
  checkRows("stat blocks", art.stat_blocks, Object.keys(statBlocks));
  const creatureTypes = [...new Set(Object.values(statBlocks).map((block) => block.creature_type))];
  checkRows("creature types", art.creature_types, creatureTypes);
}

function sprites() {
  const outputs = [];
  for (const [speciesId, doll] of Object.entries(art.species)) {
    for (const [classId, kit] of Object.entries(art.classes)) {
      outputs.push([`portraits/${speciesId}-${classId}.png`, [...doll.under, ...kit, ...doll.over], false]);
    }
  }
  for (const [statBlockId, layers] of Object.entries(art.stat_blocks)) {
    if (layers) outputs.push([`foes/${statBlockId}.png`, layers, false]);
  }
  for (const [creatureType, tile] of Object.entries(art.creature_types)) {
    outputs.push([`silhouettes/${creatureType}.png`, [tile], true]);
  }
  return outputs;
}

// PNG.sync.read refuses the second IEND chunk that many DCSS tiles end with; the async parser accepts it.
function decode(body) {
  return new Promise((resolve, reject) =>
    new PNG().parse(body, (error, png) => (error ? reject(error) : resolve(png))),
  );
}

async function readTiles(archive, names) {
  const tiles = new Map();
  for (const [name, body] of entries(archive)) {
    const layer = name.slice(PACK_ROOT.length);
    if (name.startsWith(PACK_ROOT) && names.has(layer)) tiles.set(layer, await decode(body));
  }
  fail("layers missing in the archive", [...names].filter((name) => !tiles.has(name)));
  const wrongSize = [...tiles].filter(([, tile]) => tile.width !== TILE_SIZE || tile.height !== TILE_SIZE);
  fail(`layers not ${TILE_SIZE}x${TILE_SIZE}`, wrongSize.map(([name]) => name));
  return tiles;
}

function compose(layers, tiles, silhouette) {
  const canvas = new PNG({ width: TILE_SIZE, height: TILE_SIZE });
  const target = canvas.data;
  for (const layer of layers) {
    const source = tiles.get(layer).data;
    for (let index = 0; index < target.length; index += 4) {
      const sourceAlpha = source[index + 3] / 255;
      if (!sourceAlpha) continue;
      const below = (target[index + 3] / 255) * (1 - sourceAlpha);
      const alpha = sourceAlpha + below;
      for (let channel = 0; channel < 3; channel++) {
        const mixed = source[index + channel] * sourceAlpha + target[index + channel] * below;
        target[index + channel] = Math.round(mixed / alpha);
      }
      target[index + 3] = Math.round(alpha * 255);
    }
  }
  if (silhouette) {
    for (let index = 0; index < target.length; index += 4) target.set(SILHOUETTE_RGB, index);
  }
  return PNG.sync.write(canvas);
}

async function main() {
  checkArt();
  const outputs = sprites();
  const tiles = await readTiles(await download(), new Set(outputs.flatMap(([, layers]) => layers)));
  fs.rmSync(ASSETS, { recursive: true, force: true });
  for (const [file, layers, silhouette] of outputs) {
    fs.mkdirSync(path.dirname(path.join(ASSETS, file)), { recursive: true });
    fs.writeFileSync(path.join(ASSETS, file), compose(layers, tiles, silhouette));
  }
  console.log(`wrote ${outputs.length} sprites`);
}

main();
