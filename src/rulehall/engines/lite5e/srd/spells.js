const {
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

const CLASS_MAX_LEVELS = { cleric: 3, wizard: 3, druid: 3, paladin: 3, ranger: 3, warlock: 3, bard: 3, sorcerer: 3 };
const BATTLE_CASTING_TIMES = ["action", "bonus-action"];
const RAW_SPELL = [
  "index",
  "url",
  "name",
  "level",
  "school",
  "classes",
  "casting_time",
  "ritual",
  "range",
  "components",
  "duration",
  "concentration",
  "description",
];
const RAW_SPELL_OPTIONAL = ["material", "attack_type", "damage", "higher_level"];
const CANTRIP_UPGRADE = /Cantrip Upgrade\. The damage increases by (\d+d\d+) when you reach levels 5 /;
const LONG_RANGES = ["1 mile", "Unlimited"];
const RANGE_COMPONENTS = /\s*Component: (.*)$/;
const SAVE_ABILITIES = /(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma) saving throw/g;
const HALF_ON_SUCCESS = /half as much damage/;
const HIGHER_LEVEL_DICE = /(?:damage|healing)(?: \([^)]*\))? increases by (\d+d\d+) for e(?:ach|very) (?:spell )?slot level above/;
const MORE_TARGETS = /(?:target|affect) one additional \w+ for each spell slot level above|creates? one (?:more|additional) \w+ for each spell slot level above/;
const TARGET_COUNT = /\bup to (two|three|four|five|six|ten) (?:willing )?creatures\b/i;
const NUMBER_WORDS = { two: 2, three: 3, four: 4, five: 5, six: 6, ten: 10 };
const STORY_TYPES = /\b(?:[Tt]arget an?|[Oo]ne|[Ee]ach|[Aa]n?(?: Tiny)?) (Beast|Humanoid)\b/g;
const CHOSEN_CREATURES = /\bcreatures of your choice\b/;
const AREAS = /(\d+)-foot(?:[- ]radius)?[- ](Cone|Cube|Line|Sphere|Emanation)/gi;
const STORY_ROW = ["save_ability", "story_condition", "story_boon", "story_targets"];
const BATTLE_ROW = [
  "name",
  "description",
  "casting_time",
  "range_feet",
  "save_ability",
  "success",
  "area",
  "damage",
  "healing_dice",
  "higher_level_dice",
  "target_count",
  "targets_per_level",
  "creature_types",
  "target_filter",
  "riders",
  "effect",
  "upgrade_targets",
  "exploding_dice",
  "volley",
  "variants",
  "missed_damage_parts",
  "damage_modifier",
  "strike_range_feet",
  "heals_half_dealt",
  "then",
];

function build({ characterOptions }) {
  const source = new Map(readSource("Spells").map((entry) => [entry.index, entry]));
  const { cut, spells: groups } = readGroups();
  const overrides = readOverrides().spells;
  fail("overrides.json spell not in the source", Object.keys(overrides).filter((id) => !source.has(id)));
  const scope = scopeOf(source, characterOptions);
  fail("spell_groups.json cut spell out of scope", cut.filter((id) => !scope.has(id)));
  fail("spell_groups.json row not in the source", Object.keys(groups).filter((id) => !source.has(id)));
  fail("spell_groups.json row out of scope", Object.keys(groups).filter((id) => source.has(id) && !scope.has(id)));
  fail("spell_groups.json row of a cut spell", Object.keys(groups).filter((id) => cut.includes(id)));
  const spells = {};
  for (const id of [...scope].filter((id) => !cut.includes(id)).sort()) {
    spells[id] = spellOf({ ...source.get(id), ...(overrides[id] ?? {}) }, groups[id] ?? {});
  }
  const battleSpells = Object.entries(spells).filter(([, spell]) => spell.battle !== null);
  fail(
    "battle spell cast in neither an action nor a bonus action",
    battleSpells
      .filter(([, spell]) => !BATTLE_CASTING_TIMES.includes(spell.casting_time) && spell.battle.healing_dice === undefined)
      .map(([id]) => id),
  );
  fail("battle spell with no data and no effect", battleSpells.filter(([, spell]) => !plays(spell)).map(([id]) => id));
  return { spells };
}

function cutSpellIds() {
  return readGroups().cut;
}

function readGroups() {
  return shape(readTable("spell_groups.json"), ["cut", "spells"], [], "spell_groups.json");
}

function scopeOf(source, characterOptions) {
  const scope = new Set();
  for (const entry of source.values()) {
    const classIds = entry.classes.map((spellClass) => spellClass.index);
    if (Object.entries(CLASS_MAX_LEVELS).some(([classId, max]) => classIds.includes(classId) && entry.level <= max)) {
      scope.add(entry.index);
    }
  }
  const speciesSpells = Object.values(characterOptions.species)
    .flatMap((species) => [species.traits, ...Object.values(species.subspecies).map((lineage) => lineage.traits)])
    .flat()
    .flatMap((trait) => trait.spell_ids);
  fail("species spell not in the source", speciesSpells.filter((id) => !source.has(id)));
  for (const id of speciesSpells) scope.add(id);
  return scope;
}

function spellOf(entry, ownRow) {
  shape(entry, RAW_SPELL, RAW_SPELL_OPTIONAL, entry.index);
  const row = { group: "story", ...ownRow };
  const [range, rangeFeet] = row.range_feet === undefined ? rangeOf(entry.range, row.group, entry.index) : ["feet", row.range_feet];
  return {
    name: row.name ?? entry.name,
    level: entry.level,
    school: entry.school.index,
    class_ids: entry.classes.map((spellClass) => spellClass.index),
    casting_time: row.casting_time ?? slug(entry.casting_time.split(",")[0]),
    range,
    range_feet: rangeFeet,
    duration: slug(entry.duration.replace(/^(concentration )?up to /i, "")),
    concentration: entry.concentration,
    ritual: entry.ritual,
    components: componentsOf(entry),
    attack_type: entry.attack_type ?? null,
    description: foldDashes((row.description ?? entry.description).trim()),
    ...groupOf(row, entry),
  };
}

function proseOf(entry) {
  return foldDashes(`${entry.description}\n${entry.higher_level ?? ""}`);
}

function derivedOf(row, key, value, where) {
  if (!(key in row)) return value;
  fail(`spell_groups.json ${where} ${key} equals the derived value`, JSON.stringify(row[key]) === JSON.stringify(value) ? [where] : []);
  return row[key];
}

function proseSaveAbility(prose) {
  const abilities = new Set([...prose.matchAll(SAVE_ABILITIES)].map((match) => match[1].toLowerCase()));
  return abilities.size === 1 ? [...abilities][0] : null;
}

function proseArea(prose) {
  const areas = new Set([...prose.matchAll(AREAS)].map((match) => `${match[2].toLowerCase()} ${match[1]}`));
  if (areas.size !== 1) return null;
  const [shapeName, feet] = [...areas][0].split(" ");
  return { shape: shapeName, feet: Number(feet) };
}

function storyTargetsOf(prose, range) {
  const counted = NUMBER_WORDS[prose.match(TARGET_COUNT)?.[1].toLowerCase()];
  const every = proseArea(prose) !== null || CHOSEN_CREATURES.test(prose);
  return {
    target_count: counted ?? 1,
    every_creature: counted === undefined && every,
    targets_per_level: MORE_TARGETS.test(prose) ? 1 : 0,
    creature_types: range === "Self" ? [] : [...new Set([...prose.matchAll(STORY_TYPES)].map((match) => match[1].toLowerCase()))],
  };
}

function sourceDamageOf(entry) {
  return entry.damage?.damage_at_slot_level === undefined ? [] : [damageOf(entry.damage, entry.index)];
}

function groupOf(row, entry) {
  const where = entry.index;
  const prose = proseOf(entry);
  const { group, name, casting_time, range_feet, description: _, save_ability, effect, riders = [], ...rest } = shape(
    row,
    ["group"],
    row.group === "story" ? STORY_ROW : BATTLE_ROW,
    `spell_groups.json ${where}`,
  );
  const saveAbility = derivedOf(row, "save_ability", proseSaveAbility(prose), where);
  fail(`spell_groups.json ${where} description equals the source`, row.description === entry.description ? [where] : []);
  if (group === "story") {
    if (row.story_condition !== undefined) shape(row.story_condition, ["condition", "tier"], [], `${where} story condition`);
    const derivedTargets = storyTargetsOf(prose, entry.range);
    const storyTargets = row.story_targets === undefined ? derivedTargets : { ...derivedTargets, ...row.story_targets };
    fail(`spell_groups.json ${where} story_targets equals the derived value`, row.story_targets !== undefined && JSON.stringify(storyTargets) === JSON.stringify(derivedTargets) ? [where] : []);
    return { ...rest, group, save_ability: saveAbility, story_targets: storyTargets, battle: null };
  }
  const derived = {
    success: saveAbility === null ? null : HALF_ON_SUCCESS.test(prose) ? "half" : "none",
    area: proseArea(prose),
    damage: sourceDamageOf(entry),
    higher_level_dice: prose.match(HIGHER_LEVEL_DICE)?.[1] ?? null,
    targets_per_level: MORE_TARGETS.test(prose) ? 1 : 0,
    target_count: NUMBER_WORDS[prose.match(TARGET_COUNT)?.[1].toLowerCase()] ?? 1,
  };
  const own = Object.fromEntries(Object.entries(derived).map(([key, value]) => [key, derivedOf(row, key, value, where)]));
  fail(`${where} success rule needs a save`, (saveAbility === null) === (own.success === null) ? [] : [where]);
  const description = foldDashes(entry.description);
  return {
    group,
    save_ability: saveAbility,
    battle: {
      ...rest,
      ...own,
      damage: own.damage.map((part) => withDefaults(part, ["dice"], { bonus: 0, damage_type: null }, `${where} damage`)),
      cantrip_upgrade: entry.level === 0 ? (description.match(CANTRIP_UPGRADE)?.[1] ?? null) : null,
      effect: effect === undefined ? null : effectOf(effect, where),
      riders: riders.map((part) => {
        const rider = riderRowOf(part, `spell_groups.json ${where} rider`);
        checkRider(rider, description, `spell_groups.json ${where} rider`);
        return { ...rider, dc: null };
      }),
    },
  };
}

function effectOf(entry, where) {
  fail(`spell_groups.json ${where} effect_id equals the spell id`, entry.effect_id === where ? [where] : []);
  return { rider_id: "effect", effect_id: where, ...shape(entry, [], ["effect_id", "uses", "ends"], `spell_groups.json ${where} effect`) };
}

function damageOf(damage, where) {
  shape(damage, ["damage_type", "damage_at_slot_level"], [], `${where} damage`);
  const dice = Object.values(damage.damage_at_slot_level);
  fail(`${where} damage has more than one slot level`, dice.length === 1 ? [] : [where]);
  return { ...diceOf(dice[0], `${where} damage`), damage_type: damage.damage_type.index };
}

function plays(spell) {
  const { effect, damage, healing_dice: healingDice, riders, then = [] } = spell.battle;
  return effect !== null || healingDice !== undefined || damage.length + riders.length + then.length > 0;
}

function componentsOf(entry) {
  const stray = entry.range.match(RANGE_COMPONENTS);
  if (stray === null) return entry.components;
  fail(`${entry.index} has components in its list and in its range`, entry.components.length ? [entry.index] : []);
  return stray[1].split(", ");
}

function rangeOf(range, group, where) {
  const text = range.replace(RANGE_COMPONENTS, "");
  if (text === "Self" || text === "Touch") return [text.toLowerCase(), null];
  if (LONG_RANGES.includes(text)) {
    fail(`${where} long range on a spell that is not a story spell`, group === "story" ? [] : [where]);
    return ["long", null];
  }
  const feet = /^(\d+) feet$/.exec(text) ?? fail(`${where} range`, [range]);
  return ["feet", Number(feet[1])];
}

module.exports = { build, cutSpellIds };
