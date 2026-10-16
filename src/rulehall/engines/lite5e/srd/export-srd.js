const bestiary = require("./bestiary");
const spells = require("./spells");
const fs = require("fs");
const path = require("path");
const {
  ABILITIES,
  FIREARM_IDS,
  copyLicence,
  descriptionOf,
  diceOf,
  fail,
  readOverrides,
  readSource,
  readTable,
  shape,
  withDefaults,
  writeData,
} = require("./source");

const CLASS_IDS = ["fighter", "rogue", "cleric", "wizard", "barbarian", "paladin", "ranger", "warlock", "bard", "druid", "monk", "sorcerer"];
const MAX_LEVEL = 5;
const FEAT_TYPES = ["origin", "fighting-style", "general"];
const CUT_FEAT_IDS = ["grappler"];
const LEVELS = Array.from({ length: MAX_LEVEL }, (_, index) => index + 1);
const SLOT_KEYS = Array.from({ length: 9 }, (_, index) => `spell_slots_level_${index + 1}`);
const WEAPON_PROFICIENCIES = { "simple-weapons": "simple", "martial-weapons": "martial" };
const ARMOR_TRAINING = {
  "light-armor": ["light"],
  "medium-armor": ["medium"],
  "heavy-armor": ["heavy"],
  "all-armor": ["light", "medium", "heavy"],
  shields: ["shields"],
};
const PACK = path.join(__dirname, "..", "packs", "srd.json");
const MAGIC_IN_EQUIPMENT = ["potion-of-healing", "spell-scroll-level-1", "spell-scroll-cantrip"];
const PRICED_MAGIC_ID = "potion-of-healing";
const MAGIC_ITEM_ROW = ["name", "source_id", "kind", "rarity", "cost"];
const MAGIC_ITEM_OPTIONAL = ["bonus", "healing", "base_armor_id"];
const ITEM_TABLE_DEFAULTS = { combat_gear: {}, magic_items: {}, materials: {}, light_sources: [] };
const UNREAD_CLASS_SPECIFIC = ["weapon_mastery", "unarmored_movement_bonus"];
const CLASS_SPECIFIC_GRANTS = { eldritch_invocations: "invocation" };
const SPELL_PICK_KINDS = ["cantrip", "prepared", "spellbook", "warrior-cantrip"];
const FEATURE_RULES = {
  "ability-score-improvement": { grants: { feat: 1 } },
  "extra-attack": { modifiers: [{ kind: "bonus", to: "attacks" }] },
  "fighting-style": { grants: { "fighting-style": 1 } },
  expertise: { grants: { expertise: 2 } },
};
const TRAIT_RULES = [
  [/^darkvision-\d+$/, () => ({ modifiers: [{ kind: "bonus", to: "light-steps" }] })],
  [/-resistance-([a-z]+)$/, (match) => ({ modifiers: [{ kind: "resistance", damage_types: [match[1]] }] })],
];
const DERIVED_PICKS = {
  "species-skill": { from: ["class-skill"] },
  "lore-skill": { from: ["class-skill"] },
  "primal-knowledge": { from: ["class-skill"] },
  "savant-spell": { from: ["spellbook"] },
  "initiate-cantrip": { from: ["cantrip", "warrior-cantrip"] },
  "initiate-spell": { from: ["prepared", "spellbook"], spell_level: 1 },
};
const MATERIAL_ROW = ["name", "spell_id", "cost"];
const POTION_GRADES = /Potion of Healing(?:\((\w+)\))?(\d+d\d+ \+ \d+)(Common|Uncommon|Rare|Very Rare)/g;
const TOOL_CATEGORIES = ["tools", "other-tools"];
const TOOL_PROFICIENCY_CATEGORIES = {
  Tools: "tools",
  Other: "tools",
  "Artisan's Tools": "artisans-tools",
  "Musical Instruments": "musical-instruments",
};
const CHOICE_CATEGORY_JOIN = "-or-";
const TRAIT_LEVEL = /^(?:When you reach|Starting at) character level (\d+),/;
const GLOSSARY_FILES = { conditions: "Conditions", skills: "Skills" };
const PROFICIENCY_USES = "Proficiency Bonus";
const RAW_GEAR = ["cost", "equipment_categories", "index", "name", "url"];
const RAW_GEAR_OPTIONAL = [
  "weight",
  "description",
  "contents",
  "image",
  "ability",
  "craft",
  "utilize",
  "quantity",
  "storage",
];

function categoriesOf(entry) {
  return entry.equipment_categories.map((category) => category.index);
}

function costOf(cost, where) {
  shape(cost, ["quantity", "unit"], [], `${where} cost`);
  return { quantity: cost.quantity, unit: cost.unit };
}

function damageOf(damage, where) {
  shape(damage, ["damage_dice", "damage_type"], [], `${where} damage`);
  return { ...diceOf(damage.damage_dice, `${where} damage`), damage_type: damage.damage_type.index };
}

function rangeOf(range, where) {
  shape(range, ["normal"], ["long"], `${where} range`);
  return { normal: range.normal, long: range.long ?? null };
}

function weaponOf(entry) {
  shape(
    entry,
    [...RAW_GEAR, "damage", "mastery", "properties", "weight"],
    ["range", "throw_range", "two_handed_damage", "ammunition", "notes", "image"],
    entry.index,
  );
  const categories = categoriesOf(entry);
  const ranged = categories.includes("ranged-weapons");
  // The source omits the Morningstar's range; every melee weapon reaches 5 ft.
  const range = entry.range === undefined && !ranged ? { normal: 5 } : entry.range;
  return {
    name: entry.name,
    category: categories.includes("martial-weapons") ? "martial" : "simple",
    kind: ranged ? "ranged" : "melee",
    cost: costOf(entry.cost, entry.index),
    damage: damageOf(entry.damage, entry.index),
    versatile_damage:
      entry.two_handed_damage === undefined ? null : damageOf(entry.two_handed_damage, entry.index),
    properties: entry.properties.map((property) => property.index),
    range: rangeOf(range, entry.index),
    thrown_range: entry.throw_range === undefined ? null : rangeOf(entry.throw_range, entry.index),
  };
}

function armorOf(entry) {
  shape(
    entry,
    [...RAW_GEAR, "armor_class", "stealth_disadvantage", "str_minimum", "weight"],
    ["doff_time", "don_time"],
    entry.index,
  );
  const armor = shape(entry.armor_class, ["base", "dex_bonus"], ["max_bonus"], `${entry.index} armor_class`);
  fail(`${entry.index} max_bonus`, armor.dex_bonus || armor.max_bonus === undefined || armor.max_bonus === 0 ? [] : [armor.max_bonus]);
  const categories = categoriesOf(entry);
  return {
    name: entry.name,
    category: ["light", "medium", "heavy"].find((kind) => categories.includes(`${kind}-armor`)) ?? "shield",
    cost: costOf(entry.cost, entry.index),
    base_ac: armor.base,
    dex_cap: armor.dex_bonus ? (armor.max_bonus ?? null) : 0,
    stealth_disadvantage: entry.stealth_disadvantage,
  };
}

function gearOf(entry, effects) {
  shape(entry, RAW_GEAR, RAW_GEAR_OPTIONAL, entry.index);
  const categories = categoriesOf(entry);
  const group = categories.includes("ammunition")
    ? "ammunition"
    : categories.some((category) => TOOL_CATEGORIES.includes(category))
      ? "tool"
      : "adventuring-gear";
  fail(`${entry.index} ability`, (group === "tool") === (entry.ability !== undefined) ? [] : [group]);
  return {
    name: entry.name,
    group,
    cost: costOf(entry.cost, entry.index),
    bundle: entry.quantity ?? 1,
    effect: effects[entry.index] ?? null,
    ability: entry.ability === undefined ? null : ABILITIES[entry.ability.index],
    ...(entry.description === undefined ? {} : { description: descriptionOf(entry.description) }),
    contents: Object.fromEntries(
      (entry.contents ?? [])
        .map((part) => {
          shape(part, ["item", "quantity"], [], `${entry.index} contents`);
          return [part.item.index, part.quantity];
        })
        // The SRD packs give flasks of oil: the source lists the flask as a separate part.
        .filter(([id], _, parts) => id !== "flask" || !parts.some(([other]) => other === "oil")),
    ),
  };
}

function applyPrices(gear, prices) {
  for (const [id, cost] of Object.entries(prices)) {
    const table = [gear.weapons, gear.armor, gear.gear].find((candidate) => id in candidate);
    if (table === undefined) fail("overrides.json price for no gear", [id]);
    const source = table[id].cost;
    const own = costOf(cost, `overrides.json ${id}`);
    fail("overrides.json price equals the source", own.quantity === source.quantity && own.unit === source.unit ? [id] : []);
    table[id].cost = own;
  }
}

function applyArmorCategories(gear, categories) {
  for (const [id, category] of Object.entries(categories)) {
    const armor = gear.armor[id];
    if (armor === undefined) fail("overrides.json armor category for no armor", [id]);
    fail("overrides.json armor category unknown", ["light", "medium", "heavy"].includes(category) ? [] : [category]);
    fail("overrides.json armor category equals the source", armor.category === category ? [id] : []);
    armor.category = category;
  }
}

function applyPackContents(gear, packContents) {
  for (const [id, contents] of Object.entries(packContents)) {
    const pack = gear.gear[id];
    fail("overrides.json pack_contents for no pack", pack === undefined || !Object.keys(pack.contents).length ? [id] : []);
    const same = JSON.stringify(Object.entries(contents).sort()) === JSON.stringify(Object.entries(pack.contents).sort());
    fail("overrides.json pack_contents equals the source", same ? [id] : []);
    fail(`overrides.json ${id} count`, Object.values(contents).filter((count) => !Number.isInteger(count) || count < 1).map(String));
    pack.contents = contents;
  }
}

function knownGear(gear, id) {
  return id in gear.weapons || id in gear.armor || id in gear.gear;
}

function magicItemsOf(rows) {
  const source = new Map(readSource("Magic-Items").map((entry) => [entry.index, entry]));
  const magicItems = {};
  for (const [id, row] of Object.entries(rows)) {
    shape(row, MAGIC_ITEM_ROW, MAGIC_ITEM_OPTIONAL, `items.json ${id}`);
    const entry = source.get(row.source_id) ?? fail("items.json magic item not in the source", [id]);
    shape(
      entry,
      ["index", "name", "equipment_category", "variants", "variant", "attunement", "rarity", "desc"],
      ["url", "image", "limited-to"],
      row.source_id,
    );
    if (id === row.source_id) fail("items.json magic item name differs", entry.name === row.name ? [] : [id]);
    if (entry.rarity.name === "Rarity Varies") checkVariedRow(id, row, entry.desc);
    else fail("items.json magic item rarity differs", entry.rarity.name.toLowerCase() === row.rarity ? [] : [id]);
    const { source_id, rarity, ...written } = row;
    magicItems[id] = { ...written, description: descriptionOf(entry.desc, { skipFirst: true }) };
  }
  return magicItems;
}

function checkVariedRow(id, row, desc) {
  if (row.kind !== "potion") fail("items.json varied rarity on no potion", [id]);
  const grade = row.name.match(/\((\w+)\)$/)?.[1];
  const found = [...desc.matchAll(POTION_GRADES)].find((match) => match[1] === grade);
  if (found === undefined) return;
  const healing = `${row.healing.dice} + ${row.healing.bonus}`;
  fail("items.json potion differs from its table", found[2] === healing && found[3].toLowerCase() === row.rarity ? [] : [id]);
}

function combatGearOf(rows, equipment) {
  fail("items.json combat gear not in the source", Object.keys(rows).filter((id) => !equipment.has(id)));
  return Object.fromEntries(Object.entries(rows).map(([id, row]) => [id, { bonus: 0, ...row }]));
}

function materialsOf(rows) {
  const spellSource = new Map(readSource("Spells").map((entry) => [entry.index, entry]));
  const materials = {};
  for (const [id, row] of Object.entries(rows)) {
    shape(row, MATERIAL_ROW, [], `items.json ${id}`);
    const cost = costOf(row.cost, `items.json ${id}`);
    const material = spellSource.get(row.spell_id)?.material ?? fail("items.json material of no spell", [id]);
    const named = `${row.name.toLowerCase()} worth ${cost.quantity}+ ${cost.unit.toUpperCase()}`;
    fail("items.json material differs from its spell", material.includes(named) ? [] : [id]);
    materials[id] = { name: row.name, group: "adventuring-gear", cost, bundle: 1, effect: null, ability: null, contents: {} };
  }
  return materials;
}

function buildGear(prices, packContents, armorCategories) {
  const table = withDefaults(readTable("items.json"), [], ITEM_TABLE_DEFAULTS, "items.json");
  const equipment = new Map(readSource("Equipment").map((entry) => [entry.index, entry]));
  const combatGear = combatGearOf(table.combat_gear, equipment);
  const gear = { weapons: {}, armor: {}, gear: {}, magic_items: magicItemsOf(table.magic_items) };
  const priced = equipment.get(PRICED_MAGIC_ID) ?? fail("magic item not in the Equipment file", [PRICED_MAGIC_ID]);
  const cost = gear.magic_items[PRICED_MAGIC_ID].cost;
  fail("items.json price differs from the Equipment file", cost.quantity === priced.cost.quantity && cost.unit === priced.cost.unit ? [] : [PRICED_MAGIC_ID]);
  const unclassified = [];
  for (const entry of equipment.values()) {
    const categories = categoriesOf(entry);
    if (MAGIC_IN_EQUIPMENT.includes(entry.index) || FIREARM_IDS.includes(entry.index)) continue;
    if (categories.includes("weapons")) gear.weapons[entry.index] = weaponOf(entry);
    else if (categories.includes("armor")) gear.armor[entry.index] = armorOf(entry);
    else if (
      ["adventuring-gear", "ammunition", ...TOOL_CATEGORIES].some((category) => categories.includes(category))
    ) {
      gear.gear[entry.index] = gearOf(entry, combatGear);
    } else unclassified.push(entry.index);
  }
  fail("equipment in no known category", unclassified);
  const materials = materialsOf(table.materials);
  fail("items.json material already in the Equipment file", Object.keys(materials).filter((id) => knownGear(gear, id)));
  Object.assign(gear.gear, materials);
  applyPackContents(gear, packContents);
  fail(
    "pack contents not in gear.json",
    Object.values(gear.gear).flatMap((entry) => Object.keys(entry.contents)).filter((id) => !knownGear(gear, id)),
  );
  applyPrices(gear, prices);
  applyArmorCategories(gear, armorCategories);
  fail("items.json light source not in gear.json", table.light_sources.filter((id) => !(id in gear.gear)));
  for (const id of table.light_sources) gear.gear[id].light_source = true;
  fail("items.json magic item base not an armor", Object.values(gear.magic_items).flatMap((item) => item.base_armor_id ?? []).filter((id) => !(id in gear.armor)));
  return gear;
}

function numbersOf(value, where) {
  const inner = typeof value === "object" && value !== null ? Object.values(value) : [value];
  fail(`${where} is not a number or an object of numbers`, inner.some((part) => typeof part !== "number") ? [where] : []);
  return value;
}

function levelOf(entry, classSpecificKeys, useFields) {
  shape(entry, ["index", "name", "level", "prof_bonus", "features", "class", "url"], ["class_specific", "spellcasting"], entry.index);
  const own = entry.class_specific ?? {};
  fail(`${entry.index} class_specific has unknown`, Object.keys(own).filter((key) => !UNREAD_CLASS_SPECIFIC.includes(key) && !classSpecificKeys.includes(key)));
  const counted = (key) => (own[key] === undefined ? 0 : numbersOf(own[key], `${entry.index} ${key}`));
  const classSpecific = Object.fromEntries(
    classSpecificKeys
      .filter((key) => !(key in useFields) && !(key in CLASS_SPECIFIC_GRANTS))
      .map((key) => [key, own[key] === undefined ? null : numbersOf(own[key], `${entry.index} ${key}`)]),
  );
  const spellcasting = entry.spellcasting;
  if (spellcasting !== undefined) {
    shape(
      spellcasting,
      ["cantrips_known", "prepared_spells", ...SLOT_KEYS],
      [],
      `${entry.index} spellcasting`,
    );
  }
  return {
    level: entry.level,
    proficiency_bonus: entry.prof_bonus,
    feature_ids: entry.features.map((feature) => feature.index),
    class_specific: classSpecific,
    slots: spellcasting === undefined ? null : SLOT_KEYS.map((key) => spellcasting[key]),
    known: {
      cantrip: spellcasting?.cantrips_known ?? 0,
      prepared: spellcasting?.prepared_spells ?? 0,
      ...Object.fromEntries(Object.entries(CLASS_SPECIFIC_GRANTS).map(([key, kind]) => [kind, counted(key)])),
    },
    use_counts: Object.fromEntries(
      Object.entries(useFields)
        .map(([key, use]) => [use, counted(key)])
        .filter(([, count]) => count > 0),
    ),
  };
}

function grantsOf(levels, firstGrants, levelGrants, where) {
  fail(`classes.json ${where} level_grants level`, Object.keys(levelGrants).filter((level) => !LEVELS.includes(Number(level))));
  return levels.map(({ known, ...level }, index) => {
    const before = index === 0 ? {} : levels[index - 1].known;
    const grown = Object.entries(known).map(([kind, count]) => [kind, count - (before[kind] ?? 0)]);
    const grants = Object.fromEntries(
      [...(index === 0 ? Object.entries(firstGrants) : []), ...grown, ...Object.entries(levelGrants[level.level] ?? {})].filter(
        ([, count]) => count !== 0,
      ),
    );
    return { ...level, grants };
  });
}

function skillChoicesOf(choices, where) {
  fail(`${where} skill choices`, choices.length === 1 ? [] : [String(choices.length)]);
  const choice = shape(choices[0], ["desc", "choose", "type", "from"], [], `${where} skill choice`);
  shape(choice.from, ["option_set_type", "options"], [], `${where} skill choice from`);
  fail(`${where} skill choice type`, choice.type === "proficiencies" && choice.from.option_set_type === "options_array" ? [] : [choice.type]);
  return {
    choose: choice.choose,
    skill_ids: choice.from.options.map((option) => {
      shape(option, ["option_type", "item"], [], `${where} skill option`);
      fail(`${where} skill option type`, option.option_type === "reference" ? [] : [option.option_type]);
      return option.item.index.replace(/^skill-/, "");
    }),
  };
}

function startingGearOf(options, gear, categoryMembers, override, where) {
  const [first] = options;
  shape(first, ["desc", "choose", "type", "from"], [], `${where} equipment`);
  const optionA = first.from.options[0];
  shape(optionA, ["option_type", "items"], [], `${where} option A`);
  fail(`${where} option A type`, optionA.option_type === "multiple" ? [] : [optionA.option_type]);
  const result = { gear: [], gear_categories: [], gp: 0 };
  for (const item of optionA.items) {
    if (item.option_type === "money") {
      fail(`${where} option A money unit`, item.unit === "gp" ? [] : [item.unit]);
      result.gp = item.count;
      continue;
    }
    if (item.option_type === "choice") {
      result.gear_categories.push({ category_id: choiceCategoryOf(item.choice, categoryMembers, where), count: 1 });
      continue;
    }
    shape(item, ["option_type", "count", "of"], [], `${where} option A item`);
    fail(`${where} option A item type`, item.option_type === "counted_reference" ? [] : [item.option_type]);
    const id = item.of.index;
    if (item.of.url.includes("/equipment-categories/")) {
      fail(`${where} option A category not in the source`, categoryMembers.has(id) ? [] : [id]);
      result.gear_categories.push({ category_id: id, count: item.count });
    } else {
      fail(`${where} option A gear not in gear.json`, knownGear(gear, id) ? [] : [id]);
      result.gear.push({ gear_id: id, count: item.count });
    }
  }
  return { ...result, ...gearOptionOverrideOf(override, result, gear, categoryMembers, where) };
}

function choiceCategoryOf(choice, categoryMembers, where) {
  shape(choice, ["desc", "choose", "type", "from"], [], `${where} option A choice`);
  shape(choice.from, ["option_set_type", "options"], [], `${where} option A choice from`);
  fail(`${where} option A choice`, choice.choose === 1 && choice.from.option_set_type === "options_array" ? [] : [where]);
  const ids = choice.from.options.map((option) => {
    shape(option, ["option_type", "choice"], [], `${where} option A choice option`);
    const inner = shape(option.choice, ["desc", "choose", "type", "from"], [], `${where} option A choice option`);
    shape(inner.from, ["option_set_type", "equipment_category"], [], `${where} option A choice option from`);
    fail(`${where} option A choice option`, inner.choose === 1 ? [] : [String(inner.choose)]);
    const id = inner.from.equipment_category.index;
    fail(`${where} option A category not in the source`, categoryMembers.has(id) ? [] : [id]);
    return id;
  });
  return ids.join(CHOICE_CATEGORY_JOIN);
}

function gearOptionOverrideOf(override, source, gear, categoryMembers, where) {
  const own = shape(override ?? {}, [], ["gear", "gear_categories"], `overrides.json ${where} gear_option_a`);
  const same = Object.keys(own).filter((key) => JSON.stringify(own[key]) === JSON.stringify(source[key]));
  fail(`overrides.json ${where} gear_option_a equals the source`, same);
  for (const part of own.gear ?? []) {
    shape(part, ["gear_id", "count"], [], `overrides.json ${where} gear`);
    fail(`overrides.json ${where} gear not in gear.json`, knownGear(gear, part.gear_id) ? [] : [part.gear_id]);
  }
  for (const part of own.gear_categories ?? []) {
    shape(part, ["category_id", "count"], [], `overrides.json ${where} gear category`);
    fail(`overrides.json ${where} category not in the source`, categoryMembers.has(part.category_id) ? [] : [part.category_id]);
  }
  return own;
}

function toolOf(proficiency, gear, categoryMembers, where) {
  const id = proficiency.reference.index;
  fail(`${where} tool not a tool in gear.json`, gear.gear[id]?.group === "tool" ? [] : [id]);
  const members = categoryMembers.get(TOOL_PROFICIENCY_CATEGORIES[proficiency.type]) ?? [];
  fail(`${where} tool not in the gear category of its proficiency type`, members.includes(id) ? [] : [id]);
  return id;
}

function proficiencyChoicesOf(choices, proficiencies, gear, categoryMembers, cutToolIds, where) {
  const [skills, ...tools] = choices;
  fail(`${where} tool choices`, tools.length <= 1 ? [] : [String(tools.length)]);
  fail(`overrides.json ${where} cut tool choices on a class with no tool choice`, !tools.length && cutToolIds.length ? [where] : []);
  return {
    skill_choices: skillChoicesOf([skills], where),
    tool_choices: tools.length ? toolChoicesOf(tools[0], proficiencies, gear, categoryMembers, cutToolIds, where) : null,
  };
}

function toolChoicesOf(choice, proficiencies, gear, categoryMembers, cutToolIds, where) {
  shape(choice, ["desc", "choose", "type", "from"], [], `${where} tool choice`);
  shape(choice.from, ["option_set_type", "options"], [], `${where} tool choice from`);
  fail(`${where} tool choice type`, choice.type === "proficiencies" && choice.from.option_set_type === "options_array" ? [] : [choice.type]);
  const references = choice.from.options.flatMap((option) => {
    if (option.option_type === "reference") return [shape(option, ["option_type", "item"], [], `${where} tool option`).item];
    shape(option, ["option_type", "choice"], [], `${where} tool option`);
    const inner = shape(option.choice, ["desc", "choose", "type", "from"], [], `${where} tool option choice`);
    fail(`${where} nested tool choice that is not one of one`, choice.choose === 1 && inner.choose === 1 ? [] : [inner.desc]);
    return inner.from.options.map((nested) => shape(nested, ["option_type", "item"], [], `${where} tool option`).item);
  });
  const ids = references.map((reference) => reference.index);
  fail(`overrides.json ${where} cut tool choice not in the source`, cutToolIds.filter((id) => !ids.includes(id)));
  return {
    choose: choice.choose,
    tool_ids: ids
      .filter((id) => !cutToolIds.includes(id))
      .map((id) => toolOf(proficiencies.get(id) ?? fail(`${where} tool not in the source`, [id]), gear, categoryMembers, where)),
  };
}

function trainingOf(entry, proficiencies, override) {
  const where = entry.index;
  const ids = entry.proficiencies.map((proficiency) => proficiency.index);
  const typeOf = (id) => proficiencies.get(id)?.type;
  const weapons = ids.filter((id) => typeOf(id) === "Weapons");
  const single = weapons.filter((id) => !(id in WEAPON_PROFICIENCIES));
  const own = override?.weapon_proficiencies;
  fail(`${where} lists single weapons, so overrides.json gives its weapon proficiencies`, single.length && own === undefined ? single : []);
  fail(`overrides.json ${where} weapon proficiencies on a class with no single weapon`, !single.length && own !== undefined ? [where] : []);
  const armor = ids.filter((id) => typeOf(id) === "Armor");
  return {
    armor_training: [...new Set(armor.flatMap((id) => ARMOR_TRAINING[id]))],
    weapon_proficiencies: own ?? weapons.map((id) => WEAPON_PROFICIENCIES[id]),
  };
}

function featuresOf(classes, rows) {
  const source = new Map(readSource("Features").map((feature) => [feature.index, feature]));
  const ids = [...new Set(Object.values(classes).flatMap((entry) => entry.levels.flatMap((level) => level.feature_ids)))];
  fail("class feature not in the source", ids.filter((id) => !source.has(id)));
  fail("classes.json feature not in the class levels", Object.keys(rows).filter((id) => !ids.includes(id)));
  return Object.fromEntries(
    ids.sort().map((id) => {
      const rule = featureRuleOf(id);
      fail(`classes.json ${id} repeats its feature rule`, Object.keys(rows[id] ?? {}).filter((key) => key in rule));
      return [id, { name: source.get(id).name, description: descriptionOf(source.get(id).description), ...rule, ...rows[id] }];
    }),
  );
}

function featureRuleOf(featureId) {
  const classId = CLASS_IDS.find((id) => featureId.startsWith(`${id}-`));
  return FEATURE_RULES[featureId.slice(`${classId}-`.length)] ?? {};
}

function addDerivedPicks(characterOptions, spellsBody) {
  for (const [classId, entry] of Object.entries(characterOptions.classes)) {
    const kinds = grantedKindsOf(classId, entry, characterOptions);
    const picks = entry.defaults.picks;
    for (const [kind, rule] of Object.entries(DERIVED_PICKS).filter(([kind]) => kinds.has(kind))) {
      const ids = rule.from.flatMap((from) => picks[from] ?? []).filter((id) => rule.spell_level === undefined || spellsBody.spells[id].level === rule.spell_level);
      fail(`classes.json ${classId} ${kind} picks equal the derived picks`, JSON.stringify(picks[kind]) === JSON.stringify(ids) ? [kind] : []);
      if (ids.length) picks[kind] ??= ids;
    }
  }
}

function grantedKindsOf(classId, entry, characterOptions) {
  const { features, feats, species, class_options: classOptions } = characterOptions;
  const granters = [
    ...Object.values(feats),
    ...traitsOf(species),
    ...entry.levels,
    ...entry.levels.flatMap((level) => level.feature_ids.map((id) => features[id])),
    ...Object.values(classOptions).filter((option) => option.class_id === classId),
  ];
  return new Set(granters.flatMap((granter) => Object.keys(granter.grants ?? {})));
}

function traitsOf(species) {
  return Object.values(species).flatMap((entry) => [...entry.traits, ...Object.values(entry.subspecies).flatMap((lineage) => lineage.traits)]);
}

function levelSpellIdsOf(boon) {
  return (boon.always_prepared ?? []).flatMap((part) => part.spell_ids);
}

function featureUsesOf(uses, characterOptions) {
  const { species, feats, features } = characterOptions;
  const subspeciesIds = Object.values(species).flatMap((entry) => Object.keys(entry.subspecies));
  const sources = [...Object.keys(features), ...traitsOf(species).map((trait) => trait.trait_id), ...Object.keys(feats), ...Object.keys(species), ...subspeciesIds];
  return Object.fromEntries(
    Object.entries(uses).map(([id, { class_field: classField, ...row }]) => {
      fail(`uses.json ${id} source`, row.source_id === undefined || sources.includes(row.source_id) ? [] : [row.source_id]);
      fail(`uses.json ${id} short_rest_with`, row.short_rest_with === undefined || row.short_rest_with in features ? [] : [row.short_rest_with]);
      if (classField !== undefined) return [id, { ...row, amount: "class-level" }];
      const named = [...new Set(sources.filter((source) => source === id || source.endsWith(`-${id}`)))];
      fail(`uses.json ${id} source_id equals the one source named after the use`, named.length === 1 && row.source_id === named[0] ? [id] : []);
      const sourceId = row.source_id ?? (named.length === 1 ? named[0] : fail(`uses.json ${id} needs a source_id`, [id]));
      return [id, { source_id: sourceId, ...row }];
    }),
  );
}

function checkBattleActions(characterOptions, bestiaryBody) {
  const rows = readTable("battle_actions.json");
  for (const [index, row] of rows.entries()) {
    const where = `battle_actions.json ${row.action_id}${row.variant_id === undefined ? "" : `/${row.variant_id}`}`;
    fail(`${where} feature`, row.feature_id === undefined || row.feature_id in characterOptions.features ? [] : [row.feature_id]);
    fail(`${where} use`, row.use === undefined || row.use in characterOptions.feature_uses ? [] : [row.use]);
    fail(`${where} wild shape form`, row.action_id !== "wild-shape" || row.variant_id in bestiaryBody.stat_blocks ? [] : [row.variant_id]);
    fail(`${where} repeats an earlier row`, rows.slice(0, index).some((other) => verbOf(other) === verbOf(row) && other.action_id === row.action_id && other.variant_id === row.variant_id) ? [where] : []);
  }
}

function verbOf(battleAction) {
  return battleAction.budget === "bonus" ? "bonus" : "act";
}

function checkClassPicks(characterOptions, spellsBody) {
  const { classes, feats, invocations, metamagic, class_options: classOptions } = characterOptions;
  const defaultPicks = [characterOptions.default_picks, ...Object.values(classes).map((entry) => entry.defaults.picks)];
  fail(
    "classes.json default spell not in spells.json",
    defaultPicks.flatMap((picks) => SPELL_PICK_KINDS.flatMap((kind) => picks[kind] ?? [])).filter((spellId) => !(spellId in spellsBody.spells)),
  );
  fail("classes.json default invocation not in invocations.json", defaultPicks.flatMap((picks) => picks.invocation ?? []).filter((id) => !(id in invocations)));
  fail("classes.json default metamagic not in metamagic.json", defaultPicks.flatMap((picks) => picks.metamagic ?? []).filter((id) => !(id in metamagic)));
  fail("classes.json class option of no class", Object.values(classOptions).map((option) => option.class_id).filter((id) => !(id in classes)));
  fail("feats.json feat of no class", Object.values(feats).flatMap((feat) => [feat.class_id ?? [], feat.cantrip_list ?? []].flat()).filter((id) => !(id in classes)));
  const boons = [...Object.values(characterOptions.features), ...Object.values(classOptions)];
  const invocationSpellIds = Object.values(invocations).flatMap((invocation) => invocation.spell_id ?? []);
  fail("classes.json spell not in spells.json", [...boons.flatMap(levelSpellIdsOf), ...invocationSpellIds].filter((spellId) => !(spellId in spellsBody.spells)));
  const freeCastIds = Object.values(characterOptions.feature_uses).flatMap((use) => use.free_cast_spell_id ?? []);
  fail("uses.json free cast spell not in spells.json", freeCastIds.filter((spellId) => !(spellId in spellsBody.spells)));
}

function classOf(entry, levels, gear, categoryMembers, classSpecificKeys, useFields, proficiencies, override, ownRow) {
  fail("classes.json lacks a class", ownRow === undefined ? [entry.index] : []);
  shape(
    entry,
    ["index", "name", "hit_die", "proficiencies", "proficiency_choices", "saving_throws", "starting_equipment_options", "url"],
    ["primary_ability", "class_levels", "multi_classing", "subclasses", "spellcasting", "spells"],
    entry.index,
  );
  const own = levels
    .filter((level) => level.class.index === entry.index)
    .sort((a, b) => a.level - b.level)
    .map((level) => levelOf(level, classSpecificKeys, useFields));
  const found = own.map((level) => level.level).join();
  fail(`${entry.index} class levels`, found === LEVELS.join() ? [] : [found]);
  const classOverride = shape(override ?? {}, [], ["weapon_proficiencies", "gear_option_a", "cut_tool_choices"], `overrides.json ${entry.index}`);
  const choices = proficiencyChoicesOf(entry.proficiency_choices, proficiencies, gear, categoryMembers, classOverride.cut_tool_choices ?? [], entry.index);
  const { level_grants: levelGrants = {}, ...classRow } = shape(ownRow, ["defaults"], ["level_grants", "prepared_swap", "spellbook"], `classes.json ${entry.index}`);
  const firstGrants = { "class-skill": choices.skill_choices.choose, tool: choices.tool_choices?.choose ?? 0 };
  return {
    name: entry.name,
    hit_die: entry.hit_die,
    spell_ability: entry.spellcasting === undefined ? null : ABILITIES[entry.spellcasting.spellcasting_ability.index],
    saving_throws: entry.saving_throws.map((ability) => ABILITIES[ability.index]),
    skill_options: choices.skill_choices.skill_ids,
    tool_options: choices.tool_choices?.tool_ids ?? [],
    tool_ids: entry.proficiencies
      .map((proficiency) => proficiencies.get(proficiency.index))
      .filter((proficiency) => proficiency.type in TOOL_PROFICIENCY_CATEGORIES)
      .map((proficiency) => toolOf(proficiency, gear, categoryMembers, entry.index)),
    gear_option_a: startingGearOf(entry.starting_equipment_options, gear, categoryMembers, classOverride.gear_option_a, entry.index),
    ...trainingOf(entry, proficiencies, classOverride),
    levels: grantsOf(own, firstGrants, levelGrants, entry.index),
    ...classRow,
  };
}

function traitOf(trait, level, own, where) {
  shape(
    trait,
    ["index", "url", "name", "description"],
    ["species", "subspecies", "spells", "proficiency_choices", "speed"],
    where,
  );
  fail(`traits.json ${where} spell_ids on a trait whose source lists spells`, own.spell_ids !== undefined && trait.spells !== undefined ? [where] : []);
  const spells = (trait.spells ?? []).map((entry) => {
    shape(entry, ["spell"], ["uses", "recovery"], `${where} spell`);
    fail(`${where} spell uses`, entry.uses === undefined || (entry.uses === PROFICIENCY_USES && entry.recovery === "Long Rest") ? [] : [entry.uses]);
    return entry;
  });
  const proficiencyCasts = spells.some((entry) => entry.uses === PROFICIENCY_USES);
  const rule = traitRuleOf(trait.index);
  fail(`traits.json ${where} repeats its trait rule`, Object.keys(own).filter((key) => key in rule));
  const skills = trait.proficiency_choices === undefined ? null : skillChoicesOf([trait.proficiency_choices], where);
  return {
    trait_id: trait.index,
    name: trait.name,
    description: descriptionOf(trait.description),
    level,
    spell_ids: spells.map((entry) => entry.spell.index),
    skill_options: skills?.skill_ids ?? [],
    ...(proficiencyCasts ? { free_casts: "proficiency-bonus" } : {}),
    ...rule,
    ...own,
    grants: { ...(skills === null ? {} : { "species-skill": skills.choose }), ...own.grants },
  };
}

function traitRuleOf(traitId) {
  for (const [pattern, ruleOf] of TRAIT_RULES) {
    const match = traitId.match(pattern);
    if (match !== null) return ruleOf(match);
  }
  return {};
}

function traitLevelOf(trait) {
  const found = trait.description.match(TRAIT_LEVEL);
  return found === null ? null : Number(found[1]);
}

function buildSpecies(overrides, cutSpellIds) {
  const traits = new Map(readSource("Traits").map((trait) => [trait.index, trait]));
  const traitRows = readTable("traits.json");
  fail("traits.json trait not in the source", Object.keys(traitRows).filter((id) => !traits.has(id)));
  const subspecies = readSource("Subspecies");
  const traitById = (id) => {
    fail("trait not in the source", traits.has(id) ? [] : [id]);
    return traits.get(id);
  };
  const traitsOf = (list) =>
    list
      .map((entry) => {
        const trait = traitById(entry.index);
        return traitOf(trait, entry.level ?? traitLevelOf(trait), traitRows[entry.index] ?? {}, entry.index);
      })
      .filter((trait) => (trait.level ?? 1) <= MAX_LEVEL && !trait.spell_ids.some((id) => cutSpellIds.includes(id)));
  const source = readSource("Species");
  fail("overrides.json species not in the source", Object.keys(overrides).filter((id) => !source.some((entry) => entry.index === id)));
  const result = {};
  for (const entry of source) {
    shape(entry, ["index", "url", "name", "type", "speed", "traits"], ["size", "size_options", "subspecies"], entry.index);
    const sizes =
      entry.size === undefined
        ? entry.size_options.from.options.map((option) => option.size)
        : [entry.size];
    const lineages = {};
    for (const lineage of subspecies.filter((candidate) => candidate.species.index === entry.index)) {
      shape(lineage, ["index", "url", "name", "traits", "species"], ["damage_type"], lineage.index);
      lineages[lineage.index] = {
        name: lineage.name,
        damage_type: lineage.damage_type?.index ?? null,
        traits: traitsOf(lineage.traits),
      };
    }
    fail(
      `${entry.index} subspecies`,
      (entry.subspecies ?? []).map((lineage) => lineage.index).filter((id) => !(id in lineages)),
    );
    result[entry.index] = {
      name: entry.name,
      sizes: sizes.map((size) => size.toLowerCase()),
      speed: entry.speed,
      traits: traitsOf(entry.traits),
      subspecies: lineages,
      ...shape(overrides[entry.index] ?? {}, [], ["sizes"], `overrides.json ${entry.index}`),
    };
  }
  return result;
}

function buildFeats() {
  const source = readSource("Feats");
  const own = readTable("feats.json");
  fail("cut feat not in the source", CUT_FEAT_IDS.filter((id) => !source.some((entry) => entry.index === id)));
  const feats = {};
  for (const [id, row] of Object.entries(own).filter(([id]) => !source.some((entry) => entry.index === id))) {
    feats[id] = shape(row, ["name", "type", "description"], ["class_id", "cantrip_list", "grants"], `feats.json ${id}`);
  }
  for (const entry of source.filter((feat) => FEAT_TYPES.includes(feat.type) && !CUT_FEAT_IDS.includes(feat.index))) {
    shape(entry, ["index", "name", "description", "type", "url"], ["repeatable", "prerequisites"], entry.index);
    const prerequisites = shape(entry.prerequisites ?? {}, [], ["feature_named", "minimum_level"], `${entry.index} prerequisites`);
    feats[entry.index] = {
      name: entry.name,
      type: entry.type,
      repeatable: entry.repeatable !== undefined,
      minimum_level: prerequisites.minimum_level ?? null,
      description: descriptionOf(entry.description),
      ...own[entry.index],
    };
  }
  return feats;
}

function buildCharacterOptions(gear, overrides, categoryMembers, cutSpellIds) {
  const own = withDefaults(readTable("classes.json"), [], { classes: {}, features: {}, class_options: {}, default_picks: {}, cut_features: [] }, "classes.json");
  const sourceLevels = readSource("Levels").filter(
    (level) => CLASS_IDS.includes(level.class.index) && level.subclass === undefined && level.level <= MAX_LEVEL,
  );
  const sourceFeatureIds = sourceLevels.flatMap((level) => level.features.map((feature) => feature.index));
  fail("classes.json cut feature not in the class levels", own.cut_features.filter((id) => !sourceFeatureIds.includes(id)));
  const levels = sourceLevels.map((level) => ({ ...level, features: level.features.filter((feature) => !own.cut_features.includes(feature.index)) }));
  const classSpecificKeys = [...new Set(levels.flatMap((level) => Object.keys(level.class_specific ?? {})))]
    .filter((key) => !UNREAD_CLASS_SPECIFIC.includes(key))
    .sort();
  const sourceClasses = readSource("Classes");
  const proficiencies = new Map(readSource("Proficiencies").map((proficiency) => [proficiency.index, proficiency]));
  fail("armor proficiency is unknown", [...proficiencies.values()].filter(({ index, type }) => type === "Armor" && !(index in ARMOR_TRAINING)).map(({ index }) => index));
  fail("overrides.json class not in scope", Object.keys(overrides.classes).filter((id) => !CLASS_IDS.includes(id)));
  fail("classes.json class not in scope", Object.keys(own.classes).filter((id) => !CLASS_IDS.includes(id)));
  const uses = readTable("uses.json");
  const useFields = Object.fromEntries(Object.entries(uses).flatMap(([id, row]) => (row.class_field === undefined ? [] : [[row.class_field, id]])));
  fail("uses.json class_field not in the source", Object.keys(useFields).filter((key) => !classSpecificKeys.includes(key)));
  const classes = {};
  for (const id of CLASS_IDS) {
    const entry = sourceClasses.find((candidate) => candidate.index === id) ?? fail("class not in the source", [id]);
    classes[id] = classOf(entry, levels, gear, categoryMembers, classSpecificKeys, useFields, proficiencies, overrides.classes[id], own.classes[id]);
  }
  const characterOptions = {
    classes,
    species: buildSpecies(overrides.species, cutSpellIds),
    feats: buildFeats(),
    features: featuresOf(classes, own.features),
    class_options: own.class_options,
    default_picks: own.default_picks,
    invocations: readTable("invocations.json"),
    metamagic: readTable("metamagic.json"),
    ...glossariesOf(gear),
  };
  return { ...characterOptions, feature_uses: featureUsesOf(uses, characterOptions) };
}

function glossariesOf(gear) {
  const glossaries = Object.fromEntries(
    Object.entries(GLOSSARY_FILES).map(([key, file]) => [
      key,
      Object.fromEntries(readSource(file).map((entry) => [entry.index, { name: entry.name, description: descriptionOf(entry.description) }])),
    ]),
  );
  for (const item of Object.values(gear.gear)) {
    const condition = item.effect?.condition;
    if (condition) glossaries.conditions[condition] ??= { name: condition[0].toUpperCase() + condition.slice(1), description: item.description };
  }
  return glossaries;
}

function checkTraitSpells(characterOptions, spellsBody) {
  fail("trait spell not in spells.json", traitsOf(characterOptions.species).flatMap((trait) => trait.spell_ids).filter((id) => !(id in spellsBody.spells)));
}

function categoryMembersOf() {
  return new Map(
    readSource("Equipment-Categories").map((category) => {
      shape(category, ["index", "name", "equipment", "url"], [], category.index);
      return [category.index, category.equipment.map((item) => item.index)];
    }),
  );
}

function classCategoriesOf(characterOptions, gear, categoryMembers) {
  const ids = Object.values(characterOptions.classes).flatMap((entry) =>
    entry.gear_option_a.gear_categories.map((part) => part.category_id),
  );
  return Object.fromEntries(
    [...new Set(ids)].map((id) => {
      const members = categoryMembers.get(id) ?? id.split(CHOICE_CATEGORY_JOIN).flatMap((part) => categoryMembers.get(part));
      fail(`${id} members not in gear.json`, members.filter((member) => !knownGear(gear, member)));
      return [id, members];
    }),
  );
}

function checkBackgrounds(categoryMembers) {
  const shipped = new Map(JSON.parse(fs.readFileSync(PACK, "utf8")).backgrounds.map((background) => [background.id, background]));
  const differences = [];
  for (const entry of readSource("Backgrounds")) {
    shape(
      entry,
      ["index", "name", "ability_scores", "feat", "proficiencies", "equipment_options", "url"],
      ["proficiency_choices"],
      entry.index,
    );
    const background = shipped.get(entry.index) ?? fail("SRD background not in packs/srd.json", [entry.index]);
    differences.push(
      ...backgroundDifferences(entry, background, categoryMembers).map((field) => `${entry.index} ${field}`),
    );
  }
  fail("packs/srd.json background differs from the source", differences);
}

function backgroundDifferences(entry, background, categoryMembers) {
  const proficiencies = entry.proficiencies.map((proficiency) => proficiency.index);
  const prefixed = (prefix, ids) => ids.filter((id) => id.startsWith(prefix)).map((id) => id.slice(prefix.length));
  const tools = prefixed("tool-", proficiencies);
  const toolChoices = prefixed(
    "tool-",
    (entry.proficiency_choices ?? []).flatMap((choice) => choice.from.options.map((option) => option.item.index)),
  );
  const [optionA] = entry.equipment_options[0].from.options;
  const ownGear = background.gear.map((part) => `${part.gear_id} x${part.count}`);
  const memberOf = (categoryId, count, pick) => {
    const members = categoryMembers.get(categoryId) ?? fail("background category not in the source", [categoryId]);
    const found = background.gear.find((part) => members.includes(part.gear_id) && part.count === count && pick(part.gear_id));
    return found === undefined ? `${categoryId} x${count}` : `${found.gear_id} x${count}`;
  };
  let gp = 0;
  const sourceGear = [];
  for (const item of optionA.items) {
    if (item.option_type === "money") gp = item.count;
    else if (item.option_type === "choice") {
      const category = item.choice.from.equipment_category.index;
      sourceGear.push(memberOf(category, 1, (id) => id === background.tool_id));
    } else if (item.of.url.includes("/equipment-categories/")) sourceGear.push(memberOf(item.of.index, item.count, () => true));
    else sourceGear.push(`${item.of.index} x${item.count}`);
  }
  const sameItems = (left, right) => [...left].sort().join() === [...right].sort().join();
  const checks = {
    abilities: sameItems(entry.ability_scores.map((ability) => ABILITIES[ability.index]), background.abilities),
    feat: entry.feat.index === background.feat_id,
    magic_initiate_list: entry.feat.note === undefined || entry.feat.note.toLowerCase() === background.magic_initiate_list,
    skills: sameItems(prefixed("skill-", proficiencies), background.skill_ids),
    tool: tools.length ? tools.length === 1 && tools[0] === background.tool_id : toolChoices.includes(background.tool_id),
    gear: sameItems(sourceGear, ownGear),
    gp: gp === background.gp,
  };
  return Object.keys(checks).filter((field) => !checks[field]);
}

function main() {
  const overrides = readOverrides();
  const gear = buildGear(overrides.prices, overrides.pack_contents, overrides.armor_categories);
  const categoryMembers = categoryMembersOf();
  const characterOptions = buildCharacterOptions(gear, overrides, categoryMembers, spells.cutSpellIds());
  checkBackgrounds(categoryMembers);
  const spellsBody = spells.build({ characterOptions });
  checkTraitSpells(characterOptions, spellsBody);
  addDerivedPicks(characterOptions, spellsBody);
  checkClassPicks(characterOptions, spellsBody);
  const bestiaryBody = bestiary.build({ gear });
  checkBattleActions(characterOptions, bestiaryBody);
  writeData("gear.json", { ...gear, categories: classCategoriesOf(characterOptions, gear, categoryMembers) });
  writeData("character_options.json", characterOptions);
  writeData("spells.json", spellsBody);
  writeData("bestiary.json", bestiaryBody);
  copyLicence();
  console.log(
    `weapons ${Object.keys(gear.weapons).length} armor ${Object.keys(gear.armor).length} gear ${Object.keys(gear.gear).length} magic items ${Object.keys(gear.magic_items).length} classes ${CLASS_IDS.length} species ${Object.keys(characterOptions.species).length} feats ${Object.keys(characterOptions.feats).length} spells ${Object.keys(spellsBody.spells).length} stat blocks ${Object.keys(bestiaryBody.stat_blocks).length}`,
  );
}

main();
