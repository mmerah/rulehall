const fs = require("fs");
const path = require("path");

const ATTRIBUTION =
  "This work includes material from the System Reference Document 5.2.1 (“SRD 5.2.1”) by Wizards of the Coast LLC, available at https://www.dndbeyond.com/srd. The SRD 5.2.1 is licensed under the Creative Commons Attribution 4.0 International License, available at https://creativecommons.org/licenses/by/4.0/legalcode.";
const CHANGES = "Cut and adapted for 5e Lite";
const SOURCE = {
  repository: "5e-bits/5e-database",
  commit: "a6212beb4b278917c2cff41c2b04c4ef4f3e0d6f",
  path: "src/2024/en",
  licence: "MIT, © 2018-2020 Adrian Padua, Christopher Ward",
  licence_file: "LICENSE-5e-database.md",
};
const ABILITIES = {
  str: "strength",
  dex: "dexterity",
  con: "constitution",
  int: "intelligence",
  wis: "wisdom",
  cha: "charisma",
};
const FIREARM_IDS = ["musket", "pistol", "bullets-firearm"];
const AREA_SHAPES = ["cone", "cube", "line", "sphere", "emanation"];
const LAYING_RIDERS = ["condition", "save-condition", "effect"];
const DAMAGE_RIDERS = { "advantage-damage": "if the attack roll had Advantage", "bloodied-damage": "is Bloodied" };
const RIDER_DEFAULTS = {
  ability: null,
  size_max: null,
  condition: null,
  damage: null,
  effect_id: null,
  ends: null,
  uses: null,
  ends_on: [],
  immune_condition: null,
  spared_types: [],
  spared_species_ids: [],
  on_success: false,
};
const OVERRIDE_DEFAULTS = { monsters: {}, multiattacks: {}, spells: {}, species: {}, classes: {}, prices: {}, pack_contents: {}, armor_categories: {}, weapon_damage: {} };
const DATA = path.join(__dirname, "..", "data");
const SHORT_DESCRIPTION = 200;
const RARITY_LINE = /^(Common|Uncommon|Rare|Very Rare|Legendary)\b[^.]*$/;
const SOURCE_DIR = path.join(__dirname, "node_modules", "5e-database");

function readSource(name) {
  return JSON.parse(
    fs.readFileSync(path.join(SOURCE_DIR, SOURCE.path, `5e-SRD-${name}.json`), "utf8"),
  );
}

function readTable(file) {
  const table = JSON.parse(fs.readFileSync(path.join(__dirname, "overlay", file), "utf8"));
  if (table.attribution !== ATTRIBUTION || table.changes !== CHANGES) {
    fail(`${file} lacks the attribution or the changes line`, [file]);
  }
  return table.rows;
}

function readOverrides() {
  return withDefaults(readTable("overrides.json"), [], OVERRIDE_DEFAULTS, "overrides.json");
}

function shape(entry, required, allowed, where) {
  const keys = Object.keys(entry);
  fail(`${where} lacks`, required.filter((key) => !keys.includes(key)));
  fail(`${where} has unknown`, keys.filter((key) => !required.includes(key) && !allowed.includes(key)));
  return entry;
}

function withDefaults(entry, required, defaults, where) {
  shape(entry, required, Object.keys(defaults), where);
  return { ...defaults, ...entry };
}

function riderRowOf(entry, where) {
  const row = withDefaults(entry, [], { rider_id: null, ...RIDER_DEFAULTS }, where);
  const implied = impliedRiderId(row);
  fail(`${where} rider_id is implied by its fields`, entry.rider_id !== undefined && entry.rider_id === implied ? [entry.rider_id] : []);
  return { ...row, rider_id: row.rider_id ?? implied ?? fail(`${where} lacks a rider_id`, [where]) };
}

function impliedRiderId(row) {
  if (row.effect_id !== null) return "effect";
  if (row.condition === null) return null;
  return row.ability === null ? "condition" : "save-condition";
}

function checkRider(row, desc, where) {
  fail(`${where} condition not in the text`, row.condition === null || desc.toLowerCase().includes(row.condition) ? [] : [row.condition]);
  fail(`${where} spared kind not in the text`, [...row.spared_types, ...row.spared_species_ids].filter((kind) => !desc.toLowerCase().includes(kind)));
  fail(`${where} size not in the text`, row.size_max === null || desc.includes(`${capital(row.size_max)} or smaller`) ? [] : [row.size_max]);
  fail(`${where} ability on a rider without a save`, (row.ability !== null) === (row.rider_id === "save-condition") ? [] : [where]);
  fail(`${where} damage is read from the text`, row.damage === null ? [] : [where]);
  fail(`${where} effect id exactly on an effect rider`, (row.effect_id !== null) === (row.rider_id === "effect") ? [] : [where]);
  const lays = LAYING_RIDERS.includes(row.rider_id);
  const laying = [row.ends, row.uses, row.immune_condition].some((value) => value !== null) || [row.ends_on, row.spared_types, row.spared_species_ids].some((list) => list.length > 0);
  fail(`${where} end, uses or immunity on a rider that lays nothing`, laying && !lays ? [where] : []);
}

function capital(word) {
  return word[0].toUpperCase() + word.slice(1);
}

function diceOf(text, where) {
  const match = text.match(/^(?:(\d+d\d+)(?: ?([+-]) ?(\d+))?|(\d+))$/) ?? fail(`${where} dice`, [text]);
  if (match[4] !== undefined) return { dice: null, bonus: Number(match[4]) };
  return { dice: match[1], bonus: match[2] === undefined ? 0 : Number(`${match[2]}${match[3]}`) };
}

function fail(title, names) {
  if (names.length) throw new Error(`${title}: ${names.join(", ")}`);
}

function slug(name) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function foldDashes(text) {
  return text.replace(/[–−](?=\d)/g, "-");
}

function descriptionOf(text, { skipFirst = false } = {}) {
  const paragraphs = foldDashes(text)
    .replace(/\*\*/g, "")
    .replace(/([a-z])- ([a-z])/g, "$1$2")
    .split(/\s*\n\s*/)
    .map((paragraph) => paragraph.trim().replace(/\.(?=[A-Z]).*$/, "."))
    .filter((paragraph) => paragraph && !RARITY_LINE.test(paragraph))
    .slice(skipFirst ? 1 : 0);
  const kept = [];
  for (const paragraph of paragraphs) {
    if (kept.length && kept.join(" ").length >= SHORT_DESCRIPTION) break;
    kept.push(paragraph);
  }
  return kept.join("\n");
}

function writeData(file, body) {
  fs.mkdirSync(DATA, { recursive: true });
  fs.writeFileSync(
    path.join(DATA, file),
    JSON.stringify(sorted(compact({ attribution: ATTRIBUTION, changes: CHANGES, source: SOURCE, ...body })), null, 2) +
      "\n",
  );
}

function copyLicence() {
  fs.copyFileSync(path.join(SOURCE_DIR, "LICENSE.md"), path.join(DATA, SOURCE.licence_file));
}

function compact(value) {
  if (Array.isArray(value)) return value.map(compact);
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value)
      .map(([key, entry]) => [key, compact(entry)])
      .filter(([, entry]) => !isEmpty(entry)),
  );
}

function isEmpty(value) {
  if (value === null || value === false) return true;
  if (Array.isArray(value)) return value.length === 0;
  return typeof value === "object" && Object.keys(value).length === 0;
}

function sorted(value) {
  if (Array.isArray(value)) return value.map(sorted);
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, sorted(value[key])]),
  );
}

module.exports = {
  ABILITIES,
  AREA_SHAPES,
  DAMAGE_RIDERS,
  FIREARM_IDS,
  capital,
  checkRider,
  copyLicence,
  descriptionOf,
  diceOf,
  fail,
  foldDashes,
  readOverrides,
  readSource,
  readTable,
  riderRowOf,
  shape,
  slug,
  withDefaults,
  writeData,
};
