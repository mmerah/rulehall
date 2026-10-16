const {
  ABILITIES,
  AREA_SHAPES,
  DAMAGE_RIDERS,
  FIREARM_IDS,
  capital,
  checkRider,
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
} = require("./source");

const CR_CAP = 5;
const LYCANTHROPES = ["werebear", "wereboar", "wererat", "weretiger", "werewolf"];
const SIZES = {
  Tiny: "tiny",
  Small: "small",
  Medium: "medium",
  "Medium or small": "medium",
  Large: "large",
  Huge: "huge",
  Gargantuan: "gargantuan",
};
const SPEED_MODES = ["walk", "burrow", "climb", "fly", "swim"];
const FRACTIONS = { 0.125: "1/8", 0.25: "1/4", 0.5: "1/2" };
const VERDICTS = ["special", "tag", "drop", "out"];
const SPECIAL_IDS = [
  "pack-tactics",
  "magic-resistance",
  "nimble-escape",
  "undead-fortitude",
  "bloodied-fury",
  "rampage",
  "swarm",
  "charge",
  "fire-aura",
  "regeneration",
  "life-drain",
  "agile",
  "flyby",
];
const ATTACK_SPECIALS = ["charge", "life-drain", "rampage"];
const DEATH_BURST = "death-burst";
const DEATH_BURST_HEAD = /^The [a-z]+ explodes when it dies\. /;
const REGAINED = /regains (\d+) Hit Points at the start of each of its turns/;
const STOPPING = /takes ((?:[A-Z][a-z]+ or )*[A-Z][a-z]+) damage, this trait/;
const AURA = /in a (\d+)-foot Emanation/;
const STOPS_WHILE_INCAPACITATED = /unless the \w+ has the Incapacitated condition/;
const ENTRY_GROUPS = ["special_abilities", "actions", "bonus_actions", "reactions", "legendary_actions"];
const RAW_MONSTER = [
  "index",
  "name",
  "size",
  "type",
  "alignment",
  "armor_class",
  "hit_points",
  "hit_dice",
  "hit_points_roll",
  "speed",
  ...Object.values(ABILITIES),
  "damage_resistances",
  "damage_vulnerabilities",
  "damage_immunities",
  "condition_immunities",
  "senses",
  "languages",
  "challenge_rating",
  "proficiencies",
  "proficiency_bonus",
  "xp",
];
const RAW_MONSTER_OPTIONAL = [
  "url",
  "image",
  "xp_in_lair",
  "forms",
  "gear",
  "special_abilities",
  "actions",
  "bonus_actions",
  "reactions",
  "legendary_actions",
];
const RAW_ENTRY_OPTIONAL = [
  "damage",
  "dc",
  "usage",
  "attack_bonus",
  "multiattack_type",
  "actions",
  "action_options",
  "spellcasting",
];
const ATTACK_HEAD = /^(Melee|Ranged|Melee or Ranged) Attack Roll: \+(\d+)( \(with Advantage [^)]*\))?, /;
const REACH = /^reach (\d+) (ft\.|feet\.)/;
const RANGE = /range (\d+)(\/(\d+))? ft\./;
const SAVE_HEAD = /^(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma) Saving Throw: DC (\d+), ([^.]*)\. Failure: (.*?)(?: Success: (.*))?$/s;
const AREAS = [
  [/^each creature in a (\d+)-foot (Cone|Cube|Line|Sphere|Emanation)(?: originating from the [a-z]+)?$/, (match) => [match[2], match[1]]],
  [/^each creature in a (\d+)-foot-long, (\d+)-foot-?wide Line$/, (match) => ["Line", match[1]]],
  [/^each creature in a (\d+)-foot-radius Sphere$/, (match) => ["Sphere", match[1]]],
];
const ONE_TARGET = /^one (?:(?:Tiny|Small|Medium|Large|Huge)(?: or (?:smaller|larger))? )?creature (?:the [a-z]+ can see )?within (\d+) feet(?: that the [a-z]+ can see)?$/;
const GRAPPLED_BY_SELF = "grappled-by-self";
const SIZE_LIMIT = /(Tiny|Small|Medium|Large|Huge|Gargantuan) or smaller/g;
const SIZED_RIDERS = ["grapple", "push"];
const PART = String.raw`(\d+) \((\d+d\d+)(?: ([-–−+]) (\d+))?\) ([A-Z][a-z]+) damage|(\d+) ([A-Z][a-z]+) damage`;
const BASE_PARTS = new RegExp(String.raw`^(?:${PART})(?: plus (?:${PART}))*`);
const ALTERNATIVE = new RegExp(String.raw`(?:, |—)(?:or|plus) (?:${PART}) if [^.—]*(?:—|(?=\.))`, "g");
const ACTION_DEFAULTS = {
  verdict: null,
  special_id: null,
  action_id: null,
  follow_up_action_id: null,
  reason: null,
};
const ACTION_OPTIONAL = ["riders", "special_riders", "target", "source"];
const TARGET_DEFAULTS = { reach_feet: null, range_feet: null, area: null, requires: [] };
const MULTIATTACK_ROW = ["total", "fixed", "options", "choose"];

function build({ gear }) {
  const actions = readActionRows();
  const overrides = readOverrides();
  const damageTypes = new Set(readSource("Damage-Types").map((type) => type.index));
  const raw = readSource("Monsters");
  const rawInScope = raw.filter((entry) => entry.challenge_rating <= CR_CAP && !LYCANTHROPES.some((id) => entry.index.startsWith(`${id}-`)));
  const scopeIds = rawInScope.map((entry) => entry.index);
  fail("overrides.json monster not in scope", Object.keys(overrides.monsters).filter((id) => !scopeIds.includes(id)));
  fail("overrides.json multiattack not in scope", Object.keys(overrides.multiattacks).filter((id) => !scopeIds.includes(id)));
  const inScope = rawInScope.map((entry) => withSourceFields(overrides.monsters[entry.index] ?? entry, actions));
  const items = new Map(inScope.flatMap((entry) => entriesOf(entry).map((item) => [item.key, item])));
  fail("actions.json row names no entry in the source", Object.keys(actions).filter((key) => !items.has(key)));
  for (const [key, row] of Object.entries(actions)) {
    const item = items.get(key);
    fail("actions.json tag on a special ability, where it is the default", row.verdict === "tag" && item.group === "special_abilities" ? [key] : []);
    for (const list of ["riders", "special_riders"]) {
      if (row[list] !== undefined) row[list] = row[list].map((rider) => withTextSize(rider, foldDashes(item.raw.desc), `actions.json ${key}`));
    }
    checkSpecialRow(row, item);
    if (row.riders !== undefined) checkRiderRow(row, item);
    if (row.target !== undefined) checkTargetRow(row.target, item);
  }
  const tables = { actions, damageTypes, multiattacks: overrides.multiattacks, weapons: weaponIdsByName(gear) };
  const stat_blocks = {};
  const leftOut = [];
  for (const entry of inScope) {
    const reasons = outReasonsOf(entry, actions);
    if (reasons.length) leftOut.push(`${entry.index} (${reasons.join("; ")})`);
    else stat_blocks[entry.index] = statBlockOf(entry, tables);
  }
  console.log(`bestiary: ${Object.keys(stat_blocks).length} stat blocks, ${leftOut.length} left out:\n  ${leftOut.join("\n  ")}`);
  return { stat_blocks };
}

function readActionRows() {
  return Object.fromEntries(
    Object.entries(readTable("actions.json")).map(([key, entry]) => {
      const where = `actions.json ${key}`;
      shape(entry, [], [...Object.keys(ACTION_DEFAULTS), ...ACTION_OPTIONAL], where);
      fail(`${where} verdict special is implied by its special_id`, entry.verdict === "special" ? [where] : []);
      fail(`${where} special named after its entry is the default`, Object.keys(entry).join() === "special_id" && key.endsWith(`/${entry.special_id}`) ? [where] : []);
      const row = { ...ACTION_DEFAULTS, ...entry, verdict: entry.verdict ?? (entry.special_id === undefined ? null : "special") };
      if (entry.riders !== undefined) row.riders = entry.riders.map((rider) => riderRowOf(rider, `${where} rider`));
      if (entry.special_riders !== undefined) row.special_riders = entry.special_riders.map((rider) => riderRowOf(rider, `${where} special rider`));
      if (entry.target !== undefined) row.target = withDefaults(entry.target, [], TARGET_DEFAULTS, `${where} target`);
      return [key, row];
    }),
  );
}

function withSourceFields(entry, actions) {
  const groups = ENTRY_GROUPS.filter((group) => entry[group] !== undefined).map((group) => [
    group,
    entry[group].map((raw) => {
      const fields = actions[`${entry.index}/${slug(raw.name)}`]?.source ?? {};
      fail(`actions.json ${entry.index}/${slug(raw.name)} source repeats a source field`, Object.keys(fields).filter((key) => key in raw));
      return { ...raw, ...fields };
    }),
  ]);
  return { ...entry, ...Object.fromEntries(groups) };
}

function entriesOf(entry) {
  return ENTRY_GROUPS.flatMap((group) =>
    (entry[group] ?? []).map((raw) => {
      const actionId = slug(raw.name);
      return { group, raw, actionId, key: `${entry.index}/${actionId}` };
    }),
  );
}

function outReasonsOf(entry, actions) {
  return entriesOf(entry)
    .map(({ key }) => actions[key])
    .filter((row) => row?.verdict === "out")
    .map((row) => row.reason);
}

function statBlockOf(entry, tables) {
  const where = entry.index;
  shape(entry, RAW_MONSTER, RAW_MONSTER_OPTIONAL, where);
  const block = {
    name: entry.name,
    size: SIZES[entry.size] ?? fail(`${where} size`, [entry.size]),
    creature_type: entry.type,
    armor_class: entry.armor_class[0].value,
    hit_points: entry.hit_points,
    speed: speedOf(entry.speed, where),
    scores: Object.fromEntries(Object.values(ABILITIES).map((ability) => [ability, entry[ability]])),
    save_bonuses: bonusesOf(entry.proficiencies, "saving-throw-", (id) => ABILITIES[id], where),
    skill_bonuses: bonusesOf(entry.proficiencies, "skill-", (id) => id, where),
    damage_resistances: damageTypesOf(entry.damage_resistances, tables.damageTypes, where),
    damage_immunities: damageTypesOf(entry.damage_immunities, tables.damageTypes, where),
    damage_vulnerabilities: damageTypesOf(entry.damage_vulnerabilities, tables.damageTypes, where),
    condition_immunities: entry.condition_immunities.map((condition) => condition.index),
    challenge_rating: FRACTIONS[entry.challenge_rating] ?? String(entry.challenge_rating),
    xp: entry.xp,
    passive_perception: entry.senses.passive_perception,
    darkvision: entry.senses.darkvision !== undefined,
    actions: [],
    multiattack: null,
    bonus_actions: [],
    specials: [],
    death_burst: null,
    tags: [],
    gear_drops: [],
  };
  const entries = entriesOf(entry);
  fail(`${where} repeats an action id`, entries.map(({ actionId }) => actionId).filter((id, index, ids) => ids.indexOf(id) !== index));
  const kept = [];
  const dropped = [];
  for (const item of entries) {
    shape(item.raw, ["name", "desc"], RAW_ENTRY_OPTIONAL, item.key);
    const row = actionRowOf(item, tables.actions);
    if (item.raw.spellcasting !== undefined) {
      fail(`${item.key} spellcasting needs a drop or out row`, ["drop", "out"].includes(row?.verdict) ? [] : [item.key]);
    }
    if (item.actionId === DEATH_BURST) block.death_burst = deathBurstOf(item, tables);
    else if (item.group === "reactions" || row?.verdict === "drop" || FIREARM_IDS.includes(item.actionId)) dropped.push(item);
    else if (row?.verdict === "tag") block.tags.push(item.actionId);
    else kept.push({ ...item, row });
  }
  const multiattacks = kept.filter(({ raw }) => raw.multiattack_type !== undefined);
  for (const item of kept.filter((candidate) => !multiattacks.includes(candidate))) {
    const extraParts = playOf(item, block, tables);
    if (item.row?.verdict === "special") block.specials.push(specialOf(item, extraParts));
    else fail(`${item.key} damage that maps to no rider`, extraParts.length ? [item.key] : []);
  }
  const attackIds = [...block.actions, ...block.bonus_actions].map((attack) => attack.action_id);
  const namedIds = block.specials.flatMap((special) => [special.action_id, special.follow_up_action_id ?? null]);
  fail(`${where} special names no attack`, namedIds.filter((id) => id !== null && !attackIds.includes(id)));
  fail(`${where} multiattacks`, multiattacks.length > 1 ? [where] : []);
  const override = tables.multiattacks[where];
  fail(`overrides.json ${where} multiattack on a stat block with none`, override !== undefined && !multiattacks.length ? [where] : []);
  if (multiattacks.length) block.multiattack = override === undefined ? multiattackOf(multiattacks[0], entries, kept, dropped) : multiattackOverrideOf(override, block, where);
  block.gear_drops = block.actions
    .filter((action) => action.kind !== "save")
    .map((attack) => tables.weapons.get(attack.name.replace(/\s*\([^)]*\)/g, "").toLowerCase()))
    .filter((id) => id !== undefined);
  return block;
}

function actionRowOf(item, actions) {
  if (item.key in actions) return actions[item.key];
  if (SPECIAL_IDS.includes(item.actionId)) return { ...ACTION_DEFAULTS, verdict: "special", special_id: item.actionId };
  return item.group === "special_abilities" ? { ...ACTION_DEFAULTS, verdict: "tag" } : undefined;
}

function playOf(item, block, tables) {
  const { group, raw, key, row } = item;
  if (group === "special_abilities" || group === "legendary_actions") {
    fail(`${key} has no special row in actions.json`, row?.verdict === "special" ? [] : [key]);
    return damageOfSource(raw.damage ?? [], key);
  }
  const desc = foldDashes(raw.desc);
  if (ATTACK_HEAD.test(desc)) {
    const { attack, extraParts } = attackOf(item, desc, tables);
    (group === "bonus_actions" ? block.bonus_actions : block.actions).push(attack);
    return extraParts;
  }
  if (SAVE_HEAD.test(desc) && group === "actions") {
    const { save, extraParts } = saveOf(item, desc, tables);
    block.actions.push(save);
    return extraParts;
  }
  fail(`${key} has no special row in actions.json and no plain shape`, row?.verdict === "special" ? [] : [key]);
  return damageOfSource(raw.damage ?? [], key);
}

function attackOf(item, desc, tables) {
  const { raw, key, actionId } = item;
  const head = desc.match(ATTACK_HEAD);
  const [, kind, , advantage] = head;
  const rest = desc.slice(head[0].length);
  const hitAt = rest.indexOf(" Hit: ");
  fail(`${key} has no Hit:`, hitAt < 0 ? [key] : []);
  const reachText = rest.slice(0, hitAt);
  const target = tables.actions[key]?.target;
  let reach = null;
  let range = null;
  if (target !== undefined) {
    fail(`actions.json ${key} target has an area on an attack`, target.area === null ? [] : [key]);
    reach = target.reach_feet;
    range = target.range_feet;
  } else {
    const reachMatch = kind === "Ranged" ? null : reachText.match(REACH);
    const rangeMatch = kind === "Melee" ? null : reachText.match(RANGE);
    fail(`${key} reach or range does not parse`, (kind !== "Ranged" && !reachMatch) || (kind !== "Melee" && !rangeMatch) ? [key] : []);
    reach = reachMatch ? Number(reachMatch[1]) : null;
    range = rangeMatch ? Number(rangeMatch[1]) : null;
  }
  const hit = rest.slice(hitAt + " Hit: ".length);
  const { damage, extraParts, extraText } = damageOfText(hit);
  const riders = ridersOf(item, desc, hit, extraText, extraParts, tables, advantage !== undefined);
  return {
    attack: {
      action_id: actionId,
      name: raw.name,
      kind: kind === "Ranged" ? "ranged" : "melee",
      to_hit: Number(head[2]),
      ability: null,
      dc: null,
      success: null,
      area: null,
      reach_feet: reach,
      range_feet: range,
      requires: target?.requires ?? [],
      damage,
      usage: usageOf(raw.usage, key),
      riders: riders.riders,
    },
    extraParts: riders.unclaimed,
  };
}

function saveOf(item, desc, tables) {
  const { raw, key, actionId } = item;
  const [, ability, dc, targetText, failure, success] = desc.match(SAVE_HEAD);
  const half = success !== undefined && success.startsWith("Half damage");
  const target = tables.actions[key]?.target;
  let area = null;
  let range = null;
  if (target !== undefined) {
    area = target.area;
    range = target.range_feet;
    fail(`actions.json ${key} target needs an area or a range, not both`, (area === null) === (range === null) || target.reach_feet !== null ? [key] : []);
  } else {
    const parsed = AREAS.map(([pattern, read]) => [targetText.match(pattern), read]).find(([match]) => match);
    const one = targetText.match(ONE_TARGET);
    fail(`${key} target does not parse`, parsed === undefined && !one ? [key] : []);
    if (parsed !== undefined) {
      const [shapeName, feet] = parsed[1](parsed[0]);
      area = areaOf(shapeName.toLowerCase(), Number(feet), key);
    } else range = Number(one[1]);
  }
  const { damage, extraParts, extraText } = damageOfText(failure);
  const riders = ridersOf(item, desc, failure, extraText, extraParts, tables, false);
  return {
    save: {
      action_id: actionId,
      name: raw.name,
      kind: "save",
      to_hit: null,
      ability: ability.toLowerCase(),
      dc: Number(dc),
      success: half ? "half" : "none",
      area,
      reach_feet: null,
      range_feet: range,
      requires: target?.requires ?? [],
      damage,
      usage: usageOf(raw.usage, key),
      riders: riders.riders,
    },
    extraParts: riders.unclaimed,
  };
}

function areaOf(shapeName, feet, where) {
  fail(`${where} area shape`, AREA_SHAPES.includes(shapeName) && Number.isInteger(feet) ? [] : [where]);
  return { shape: shapeName, feet };
}

function damageOfText(text) {
  const extraParts = [];
  const withoutAlternatives = text.replace(ALTERNATIVE, (clause) => {
    extraParts.push(partOf(clause.match(new RegExp(PART))));
    return clause.endsWith("—") ? " " : "";
  });
  const base = withoutAlternatives.match(BASE_PARTS);
  const baseText = base?.[0] ?? "";
  const damage = [...baseText.matchAll(new RegExp(PART, "g"))].map(partOf);
  const extraText = withoutAlternatives.slice(baseText.length);
  extraParts.push(...[...extraText.matchAll(new RegExp(PART, "g"))].map(partOf));
  return { damage, extraParts, extraText: extraText.replace(/^\.$/, "") };
}

function partOf(match) {
  if (match[2] === undefined) return { dice: null, bonus: Number(match[6]), damage_type: match[7].toLowerCase() };
  const sign = match[3] === undefined ? 0 : match[3] === "+" ? 1 : -1;
  return { dice: match[2], bonus: sign * Number(match[4] ?? 0), damage_type: match[5].toLowerCase() };
}

function damageOfSource(damage, where) {
  return damage.map((part) => {
    shape(part, ["damage_type", "damage_dice"], [], `${where} damage`);
    const { dice, bonus } = diceOf(part.damage_dice, `${where} damage`);
    fail(`${where} damage dice`, dice === null ? [part.damage_dice] : []);
    return { dice, bonus, damage_type: part.damage_type.index };
  });
}

function ridersOf(item, desc, text, extraText, extraParts, tables, hasAdvantageClause) {
  const { raw, key } = item;
  const table = tables.actions[key];
  const special = item.row?.verdict === "special";
  fail(`${key} needs riders in actions.json`, table?.riders === undefined && extraText !== "" && !special ? [key] : []);
  const riders = (table?.riders ?? []).map((row) => riderOf(row, text, key));
  const unclaimed = [...extraParts];
  for (const rider of riders.filter((candidate) => candidate.rider_id in DAMAGE_RIDERS)) {
    rider.damage = unclaimed.shift() ?? fail(`${key} ${rider.rider_id} has no extra damage in the text`, [key]);
    fail(`${key} ${rider.rider_id} differs from the text`, text.includes(DAMAGE_RIDERS[rider.rider_id]) ? [] : [key]);
  }
  const conditional = riders.filter((rider) => rider.rider_id === "conditional-advantage").length;
  fail(`${key} with Advantage clause and conditional-advantage rider disagree`, conditional === (hasAdvantageClause ? 1 : 0) ? [] : [key]);
  if (raw.dc !== undefined && raw.attack_bonus !== undefined && table?.reason == null) {
    const dcRiders = riders.filter((rider) => rider.dc !== null);
    fail(`${key} dc is neither an escape DC nor an on-hit save`, dcRiders.length > 0 && dcRiders.every((rider) => rider.dc === raw.dc.dc_value) ? [] : [key]);
  }
  return { riders, unclaimed };
}

function checkRiderRow(table, item) {
  const where = `actions.json ${item.key} riders`;
  fail(`${where} need a reason exactly when the list is empty`, (table.reason !== null) === (table.riders.length === 0) ? [] : [item.key]);
  const desc = foldDashes(item.raw.desc);
  for (const row of table.riders) checkRider(row, desc, where);
}

function checkTargetRow(row, item) {
  const key = item.key;
  fail(`actions.json ${key} target requires`, Array.isArray(row.requires) ? [] : [key]);
  const text = foldDashes(item.raw.desc).toLowerCase();
  const own = row.requires.includes(GRAPPLED_BY_SELF);
  fail(`actions.json ${key} target requires grappled-by-self beside a condition`, own && row.requires.length > 1 ? [key] : []);
  fail(`actions.json ${key} target grappled-by-self not in the text`, own && !/grappled by the [a-z]+/.test(text) ? [key] : []);
  fail(`actions.json ${key} target required condition not in the text`, own ? [] : row.requires.filter((condition) => !text.includes(condition)));
  if (row.area !== null) {
    shape(row.area, ["shape", "feet"], [], `actions.json ${key} target area`);
    areaOf(row.area.shape, row.area.feet, `actions.json ${key} target`);
  }
}

function withTextSize(rider, desc, where) {
  if (!SIZED_RIDERS.includes(rider.rider_id) && rider.condition !== "prone") return rider;
  fail(`${where} size_max is read from the text`, rider.size_max === null ? [] : [where]);
  const sizes = new Set([...desc.matchAll(SIZE_LIMIT)].map((match) => match[1].toLowerCase()));
  return { ...rider, size_max: sizes.size === 1 ? [...sizes][0] : null };
}

function riderOf(row, text, key) {
  let dc = null;
  if (row.rider_id === "grapple") {
    dc = Number((text.match(/escape DC (\d+)/) ?? fail(`${key} grapple without escape DC`, [key]))[1]);
  }
  if (row.rider_id === "save-condition") {
    const save = new RegExp(`${capital(row.ability)} Saving Throw: DC (\\d+)`);
    dc = Number((text.match(save) ?? fail(`${key} save-condition without its save`, [key]))[1]);
  }
  return { ...row, dc };
}

function checkSpecialRow(row, item) {
  const where = `actions.json ${item.key}`;
  const desc = foldDashes(item.raw.desc);
  fail(`${where} verdict`, row.verdict === null || VERDICTS.includes(row.verdict) ? [] : [row.verdict]);
  fail(`${where} special id`, (row.verdict === "special") === SPECIAL_IDS.includes(row.special_id) && (row.verdict === "special" || row.special_id === null) ? [] : [String(row.special_id)]);
  fail(`${where} reason`, row.riders !== undefined || (row.reason !== null) === ["drop", "out"].includes(row.verdict) ? [] : [item.key]);
  fail(`${where} parameters on a row that is not special`, row.verdict === "special" || (row.action_id === null && row.follow_up_action_id === null && row.special_riders === undefined) ? [] : [item.key]);
  fail(`${where} action_id is its own entry, which is the default`, row.action_id === item.actionId ? [item.key] : []);
  fail(`${where} follow_up_action_id on a special that is not charge`, row.follow_up_action_id !== null && row.special_id !== "charge" ? [item.key] : []);
  for (const rider of row.special_riders ?? []) checkRider(rider, desc, `${where} special rider`);
}

function specialOf(item, extraParts) {
  const { raw, key, row, group } = item;
  const desc = foldDashes(raw.desc);
  const regained = row.special_id === "regeneration" ? (desc.match(REGAINED) ?? fail(`${key} regeneration without regained Hit Points`, [key])) : null;
  const stopping = row.special_id === "regeneration" ? (desc.match(STOPPING) ?? fail(`${key} regeneration without stopping damage`, [key])) : null;
  const aura = row.special_id === "fire-aura" ? (desc.match(AURA) ?? fail(`${key} fire aura without an Emanation`, [key])) : null;
  const actionId = row.action_id ?? (ATTACK_SPECIALS.includes(row.special_id) && group !== "special_abilities" ? item.actionId : null);
  fail(`${key} action_id`, (actionId !== null) === ATTACK_SPECIALS.includes(row.special_id) ? [] : [key]);
  return {
    special_id: row.special_id,
    regained_hit_points: regained === null ? null : Number(regained[1]),
    stopping_damage_types: stopping === null ? [] : stopping[1].toLowerCase().split(" or "),
    heals_self: row.special_id === "life-drain" && desc.includes("regains Hit Points equal to"),
    stops_while_incapacitated: STOPS_WHILE_INCAPACITATED.test(desc),
    action_id: actionId,
    damage: extraParts,
    usage: usageOf(raw.usage, key),
    follow_up_action_id: row.follow_up_action_id,
    riders: (row.special_riders ?? []).map((rider) => ({ ...rider, dc: null })),
    area: aura === null ? null : areaOf("emanation", Number(aura[1]), key),
  };
}

function deathBurstOf(item, tables) {
  const { raw, key } = item;
  fail(`${key} has a row in actions.json, but a death burst is read from its text`, key in tables.actions ? [key] : []);
  const desc = foldDashes(raw.desc);
  fail(`${key} death burst head`, DEATH_BURST_HEAD.test(desc) ? [] : [key]);
  const { save, extraParts } = saveOf({ ...item, row: undefined }, desc.replace(DEATH_BURST_HEAD, ""), tables);
  fail(`${key} death burst with extra damage`, extraParts.length ? [key] : []);
  return save;
}

function usageOf(usage, where) {
  if (usage === undefined) return null;
  if (usage.type === "recharge on roll") {
    shape(usage, ["type", "dice", "min_value"], [], `${where} usage`);
    fail(`${where} recharge dice`, usage.dice === "1d6" ? [] : [usage.dice]);
    return { recharge_min: usage.min_value, uses_per_day: null };
  }
  shape(usage, ["type", "times"], [], `${where} usage`);
  fail(`${where} usage type`, usage.type === "per day" ? [] : [usage.type]);
  return { recharge_min: null, uses_per_day: usage.times };
}

function multiattackOf(item, entries, kept, dropped) {
  const { raw, key } = item;
  const idOf = (name) => {
    const entry = entries.find((candidate) => candidate.raw.name === name);
    if (entry !== undefined) return entry;
    const caster = entries.find((candidate) => candidate.raw.spellcasting?.spells.some((spell) => spell.name === name));
    return caster ?? fail(`${key} names no action`, [name]);
  };
  const isDropped = (entry) => dropped.includes(entry) || !kept.some((candidate) => candidate.key === entry.key);
  const fixed = (raw.actions ?? []).map((action) => {
    shape(action, ["action_name", "count", "type"], [], `${key} action`);
    const entry = idOf(action.action_name);
    fail(`${key} fixed attack is dropped`, isDropped(entry) ? [action.action_name] : []);
    return { action_id: entry.actionId, count: action.count };
  });
  let options = [];
  let choose = 0;
  if (raw.action_options !== undefined) {
    shape(raw.action_options, ["choose", "type", "from"], ["desc"], `${key} action_options`);
    shape(raw.action_options.from, ["option_set_type", "options"], [], `${key} action_options from`);
    choose = raw.action_options.choose;
    options = raw.action_options.from.options
      .map((option) => {
        shape(option, ["option_type", "action_name", "count", "type"], [], `${key} option`);
        return idOf(option.action_name);
      })
      .filter((entry) => !isDropped(entry))
      .map((entry) => entry.actionId);
  }
  fail(`${key} replaces an attack, so overrides.json gives its multiattack`, /replace one attack/.test(raw.desc) ? [key] : []);
  return { total: fixed.reduce((sum, action) => sum + action.count, 0) + choose, fixed, options, choose };
}

function multiattackOverrideOf(override, block, where) {
  shape(override, MULTIATTACK_ROW, [], `overrides.json ${where} multiattack`);
  const ids = block.actions.map((attack) => attack.action_id);
  for (const part of override.fixed) shape(part, ["action_id", "count"], [], `overrides.json ${where} multiattack part`);
  const named = [...override.fixed.map((part) => part.action_id), ...override.options];
  fail(`overrides.json ${where} multiattack names no attack`, named.filter((id) => !ids.includes(id)));
  const total = override.fixed.reduce((sum, part) => sum + part.count, 0) + override.choose;
  fail(`overrides.json ${where} multiattack total`, total === override.total ? [] : [where]);
  return override;
}

function speedOf(speed, where) {
  fail(`${where} speed`, Object.keys(speed).filter((mode) => ![...SPEED_MODES, "hover"].includes(mode)));
  return SPEED_MODES.filter((mode) => speed[mode] !== undefined)
    .map((mode) => (mode === "walk" ? speed[mode] : `${mode} ${speed[mode]}${mode === "fly" && speed.hover ? " (hover)" : ""}`))
    .join(", ");
}

function bonusesOf(proficiencies, prefix, idOf, where) {
  return Object.fromEntries(
    proficiencies
      .filter((proficiency) => proficiency.proficiency.index.startsWith(prefix))
      .map((proficiency) => {
        const id = idOf(proficiency.proficiency.index.slice(prefix.length)) ?? fail(`${where} proficiency`, [proficiency.proficiency.index]);
        return [id, proficiency.value];
      }),
  );
}

function damageTypesOf(types, known, where) {
  fail(`${where} unknown damage type`, types.filter((type) => !known.has(type)));
  return types;
}

function weaponIdsByName(gear) {
  return new Map(Object.entries(gear.weapons).map(([id, weapon]) => [weapon.name.toLowerCase(), id]));
}

module.exports = { build };
