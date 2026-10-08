const crypto = require("crypto");
const { toID } = require("pokemon-showdown");
const { SP_MAX, STAT_IDS } = require("./champions-legal");
const { compare, fail } = require("./net");

const MIN_SHARE = 0.01;
const SECOND_ITEM_SHARE = 0.1;
const NO_ITEM = "nothing";
const HASH_RANGE = 2 ** 32;
const BULK_IDS = ["hp", "def", "spd"];
const WEIGHT_DIGITS = 4;
const PERCENT_DIGITS = 1;
const CARD_TEAMMATES = 6;
const CARD_ITEMS = 5;
const CARD_MOVES = 8;
const CARD_SPREADS = 5;
const CARD_CHECKS = 5;
const CHECK_MIN_MEETINGS = 20;
// Smogon ranks checks by the win share minus 4 standard deviations.
const CHECK_DEVIATIONS = 4;
const NO_ENTRY_KEYS = new Set(["", NO_ITEM]);
const MEGA_BATCH_0_SIZE = 5;
const LATER_MEGA_BATCHES = 3;

// The usage of one species, its Mega formes folded in. Every weight counts teams.
function emptySpecies(speciesId) {
  return {
    speciesId,
    usage: 0,
    weight: 0,
    abilities: {},
    items: {},
    moves: {},
    spreads: {},
    teammates: {},
    checkMeetings: {},
    checkWins: {},
  };
}

function parseChaos(regulation, raw) {
  const species = new Map();
  const megaUsage = {};
  for (const [name, entry] of Object.entries(raw.data)) {
    const dexSpecies = knownSpecies(regulation, name);
    const speciesId = baseSpeciesId(regulation, name);
    const target = species.get(speciesId) ?? emptySpecies(speciesId);
    target.usage += entry.usage;
    target.weight += sum(entry.Spreads);
    if (dexSpecies.isMega) addWeights(megaUsage, { [toID(dexSpecies.requiredItem)]: entry.usage });
    else addWeights(target.abilities, entry.Abilities);
    addWeights(target.items, entry.Items);
    addWeights(target.moves, entry.Moves);
    addWeights(target.spreads, entry.Spreads);
    for (const [mate, weight] of Object.entries(entry.Teammates)) {
      addWeights(target.teammates, { [baseSpeciesId(regulation, mate)]: weight });
    }
    for (const [foe, { n, p }] of Object.entries(entry["Checks and Counters"])) {
      const foeId = baseSpeciesId(regulation, foe);
      addWeights(target.checkMeetings, { [foeId]: n });
      addWeights(target.checkWins, { [foeId]: n * p });
    }
    species.set(speciesId, target);
  }
  const ranked = [...species.values()].sort(
    (a, b) => b.usage - a.usage || compare(a.speciesId, b.speciesId),
  );
  return {
    cutoff: raw.info.cutoff,
    battles: raw.info["number of battles"],
    ranked,
    megaUsage,
  };
}

// The usage of each species on the real teams, in the chaos shape, for a species the ladder lacks.
function realTeamSpecies(realTeams) {
  const species = new Map();
  for (const team of realTeams) {
    for (const set of team.sets) {
      const entry = species.get(set.species_id) ?? emptySpecies(set.species_id);
      entry.usage += 1 / realTeams.length;
      entry.weight += 1;
      addWeights(entry.abilities, { [set.ability_id]: 1 });
      addWeights(entry.items, { [set.item_id]: 1 });
      for (const moveId of set.move_ids) addWeights(entry.moves, { [moveId]: 1 });
      addWeights(entry.spreads, { [spreadKey(set.nature, set.sp)]: 1 });
      for (const mate of team.sets) {
        if (mate !== set) addWeights(entry.teammates, { [mate.species_id]: 1 });
      }
      species.set(set.species_id, entry);
    }
  }
  return species;
}

// Up to three: the top valid item, the best item of another family, the best stone.
function buildPresets(regulation, entry) {
  const items = topKeys(entry.items, entry.weight, MIN_SHARE).filter(
    (itemId) => itemId !== NO_ITEM,
  );
  const first = firstValid(regulation, entry, items);
  if (first === undefined) return [];
  const secondItems = topKeys(entry.items, entry.weight, SECOND_ITEM_SHARE).filter(
    (itemId) => itemId !== NO_ITEM &&
      itemFamily(regulation, itemId) !== itemFamily(regulation, first.item_id),
  );
  const unique = new Map();
  const stones = items.filter((itemId) => regulation.isMegaStone(itemId));
  const second = firstValid(regulation, entry, secondItems);
  for (const preset of [first, second, firstValid(regulation, entry, stones)]) {
    if (preset !== undefined) unique.set(JSON.stringify(preset), preset);
  }
  return [...unique.values()];
}

// One spread per nature group of at least 1%, the most used nature first.
function assumedSpreads(entry) {
  const total = sum(entry.spreads);
  return natureGroups(entry.spreads)
    .filter(([, spreads]) => sum(spreads) / total >= MIN_SHARE)
    .map(([nature, spreads]) => ({ nature, sp: topSpread(spreads) }));
}

// A real team's own spread: one of the usage spreads of its nature, picked by the hash of `key`.
function realSpread(regulation, entry, speciesId, nature, key) {
  const group = natureGroups(entry?.spreads ?? {}).find(([name]) => name === nature)?.[1];
  if (group === undefined) {
    return spreadFor(
      regulation,
      entry === undefined ? [] : assumedSpreads(entry),
      speciesId,
      nature,
    );
  }
  const spreadKeys = topKeys(group, sum(group), MIN_SHARE);
  let roll = hashFraction(key) * sum(spreadKeys.map((each) => group[each]));
  for (const each of spreadKeys) {
    roll -= group[each];
    if (roll < 0) return parseSpread(each);
  }
  return topSpread(group);
}

// The most used nature of the species whose arrows suit the attacks of the moves.
function likelyNature(regulation, entry, moveIds) {
  const natures = natureGroups(entry?.spreads ?? {}).map(([nature]) => nature);
  return natures.find((nature) => natureFits(regulation, nature, moveIds));
}

function usageCard(entry, source) {
  const listed = (weights, count) =>
    topKeys(weights, entry.weight, MIN_SHARE)
      .filter((key) => !NO_ENTRY_KEYS.has(key))
      .slice(0, count)
      .map((key) => [key, percent(weights[key] / entry.weight)]);
  const { [entry.speciesId]: _, ...teammates } = entry.teammates;
  return {
    source,
    usage_percent: percent(entry.usage),
    teammates: listed(teammates, CARD_TEAMMATES).map(([species_id, share]) => ({
      species_id,
      percent: share,
    })),
    items: listed(entry.items, CARD_ITEMS).map(([item_id, share]) => ({ item_id, percent: share })),
    moves: listed(entry.moves, CARD_MOVES).map(([move_id, share]) => ({ move_id, percent: share })),
    // The spreads of a species on real teams only are guesses.
    spreads:
      source === "limitless"
        ? []
        : listed(entry.spreads, CARD_SPREADS).map(([key, share]) => {
            const [nature, sp] = key.split(":");
            return { nature, sp: parseSpread(sp), percent: share };
          }),
    checks: checks(entry),
  };
}

// The share of a's teams that also run b, both ways for every pair either side lists.
function teammateShares(kept) {
  const byId = new Map(kept.map((entry) => [entry.speciesId, entry]));
  const shares = Object.fromEntries(kept.map((entry) => [entry.speciesId, {}]));
  for (const entry of kept) {
    for (const mateId of Object.keys(entry.teammates)) {
      const mate = byId.get(mateId);
      if (mate === undefined || mateId === entry.speciesId) continue;
      const together = Math.max(entry.teammates[mateId], mate.teammates[entry.speciesId] ?? 0);
      const there = share(together, entry.weight);
      const back = share(together, mate.weight);
      if (there < MIN_SHARE && back < MIN_SHARE) continue;
      shares[entry.speciesId][mateId] = there;
      shares[mateId][entry.speciesId] = back;
    }
  }
  return shares;
}

// The ladder's stones by usage, then the stones only the presets hold.
function megaBatches(regulation, megaUsage, presets) {
  const holders = Object.entries(presets).map(([speciesId, list]) => [speciesId, list[0]]);
  const ladderStones = Object.keys(megaUsage).sort(
    (a, b) => megaUsage[b] - megaUsage[a] || compare(a, b),
  );
  const presetStones = Object.values(presets)
    .flat()
    .map((preset) => preset.item_id)
    .filter((itemId) => regulation.isMegaStone(itemId));
  const stones = [...new Set([...ladderStones, ...presetStones])].filter((stoneId) => {
    const holder = holders.find(([speciesId]) => regulation.megaStoneFits(stoneId, speciesId));
    return (
      holder !== undefined &&
      regulation.setProblems({ ...holder[1], item_id: stoneId }).length === 0
    );
  });
  const rest = stones.slice(MEGA_BATCH_0_SIZE);
  const size = Math.ceil(rest.length / LATER_MEGA_BATCHES);
  const later = Array.from({ length: LATER_MEGA_BATCHES }, (_, index) =>
    rest.slice(index * size, (index + 1) * size),
  );
  return [stones.slice(0, MEGA_BATCH_0_SIZE), ...later];
}

function sum(weights) {
  return Object.values(weights).reduce((total, weight) => total + weight, 0);
}

function firstValid(regulation, entry, itemIds) {
  for (const itemId of itemIds) {
    const preset = makePreset(regulation, entry, itemId);
    if (preset.move_ids.length > 0 && regulation.setProblems(preset).length === 0) return preset;
  }
  return undefined;
}

function makePreset(regulation, entry, itemId) {
  const [nature, spreads] =
    natureGroups(entry.spreads)[0] ?? fail(`${entry.speciesId} has no spread`);
  const choice = regulation.dex.items.get(itemId).isChoice === true;
  const moveIds = topKeys(entry.moves, entry.weight, MIN_SHARE)
    .filter((moveId) => moveId !== "" && (!choice || fitsChoice(regulation, moveId)))
    .slice(0, regulation.movesMax);
  return {
    species_id: entry.speciesId,
    ability_id: topAbility(regulation, entry),
    item_id: itemId,
    move_ids: moveIds,
    nature,
    sp: topSpread(spreads),
  };
}

// A Choice item locks its holder into one move: no status, first-turn-only or recharge moves.
function fitsChoice(regulation, moveId) {
  const move = regulation.dex.data.Moves[moveId];
  return (
    move?.category !== "Status" &&
    move?.onDisableMove === undefined &&
    move?.flags?.recharge === undefined
  );
}

// The chaos file gives a Mega forme its Mega ability, so a Mega-only species has no ability data.
function topAbility(regulation, entry) {
  const [abilityId] = topKeys(entry.abilities, entry.weight, MIN_SHARE);
  return abilityId ?? toID(regulation.dex.species.get(entry.speciesId).abilities["0"]);
}

function itemFamily(regulation, itemId) {
  const item = regulation.dex.items.get(itemId);
  if (item.isChoice === true) return "choice";
  if (item.isBerry) return "berry";
  if (item.megaStone !== undefined) return "megastone";
  return item.id;
}

function natureFits(regulation, nature, moveIds) {
  const { plus, minus } = regulation.dex.natures.get(nature);
  if (plus === undefined || plus === minus) return true;
  const attacks = new Set(
    moveIds
      .map((moveId) => regulation.dex.moves.get(moveId).category)
      .filter((category) => category !== "Status")
      .map((category) => (category === "Physical" ? "atk" : "spa")),
  );
  return !attacks.has(minus) && (!["atk", "spa"].includes(plus) || attacks.has(plus));
}

// A nature the stats lack takes the spread of the most used nature raising the same stat.
function spreadFor(regulation, spreads, speciesId, nature) {
  const exact = spreads.find((spread) => spread.nature === nature);
  if (exact !== undefined) return exact.sp;
  const up = regulation.dex.natures.get(nature).plus;
  const sameUp = spreads.find((spread) => regulation.dex.natures.get(spread.nature).plus === up);
  return sameUp?.sp ?? standardSpread(regulation, speciesId, nature);
}

// 32 SP in the favoured attack and 32 in Speed (HP when the nature lowers it), the rest in bulk.
function standardSpread(regulation, speciesId, nature) {
  const main = mainStatIds(regulation, speciesId, nature);
  const rest = BULK_IDS.find((statId) => !main.includes(statId)) ?? "def";
  return STAT_IDS.map((statId) => {
    if (main.includes(statId)) return SP_MAX;
    return statId === rest ? regulation.spTotal - main.length * SP_MAX : 0;
  });
}

function mainStatIds(regulation, speciesId, nature) {
  const { plus: up, minus: down } = regulation.dex.natures.get(nature);
  if (up === "def" || up === "spd") return ["hp", up];
  const { baseStats } = regulation.dex.species.get(speciesId);
  const higherAttack = baseStats.atk >= baseStats.spa ? "atk" : "spa";
  const otherAttack = down === "atk" ? "spa" : down === "spa" ? "atk" : higherAttack;
  const attack = up === "atk" || up === "spa" ? up : otherAttack;
  return [attack, down === "spe" ? "hp" : "spe"];
}

function checks(entry) {
  return Object.entries(entry.checkMeetings)
    .filter(([foeId, meetings]) => meetings >= CHECK_MIN_MEETINGS && foeId !== entry.speciesId)
    .map(([speciesId, meetings]) => {
      const winShare = (entry.checkWins[speciesId] ?? 0) / meetings;
      const deviation = Math.sqrt((winShare * (1 - winShare)) / meetings);
      return { speciesId, winShare, score: winShare - CHECK_DEVIATIONS * deviation };
    })
    .sort((a, b) => b.score - a.score || compare(a.speciesId, b.speciesId))
    .slice(0, CARD_CHECKS)
    .map(({ speciesId, winShare }) => ({ species_id: speciesId, percent: percent(winShare) }))
    .sort((a, b) => b.percent - a.percent || compare(a.species_id, b.species_id));
}

function natureGroups(spreads) {
  const groups = new Map();
  for (const [key, weight] of Object.entries(spreads)) {
    const [nature, sp] = key.split(":");
    if (sp === undefined) fail(`bad spread ${key}`);
    const group = groups.get(nature) ?? {};
    group[sp] = weight;
    groups.set(nature, group);
  }
  return [...groups].sort((a, b) => sum(b[1]) - sum(a[1]) || compare(a[0], b[0]));
}

// The chaos key of a spread: "Jolly:2/32/0/0/0/32".
function spreadKey(nature, sp) {
  return `${nature}:${sp.join("/")}`;
}

function parseSpread(key) {
  const values = key.split("/").map(Number);
  if (values.length !== STAT_IDS.length || values.some((value) => !Number.isInteger(value))) {
    fail(`bad spread ${key}`);
  }
  return values;
}

function topSpread(spreads) {
  const [best] = topKeys(spreads, 1, 0);
  return parseSpread(best ?? fail("empty spread group"));
}

function topKeys(weights, total, minShare) {
  return Object.entries(weights)
    .filter(([, weight]) => weight / total >= minShare)
    .sort((a, b) => b[1] - a[1] || compare(a[0], b[0]))
    .map(([key]) => key);
}

function addWeights(target, source) {
  for (const [key, weight] of Object.entries(source)) target[key] = (target[key] ?? 0) + weight;
}

function share(part, whole) {
  return Number(Math.min(1, part / whole).toFixed(WEIGHT_DIGITS));
}

function percent(value) {
  return Number((Math.min(1, value) * 100).toFixed(PERCENT_DIGITS));
}

function hashFraction(key) {
  return crypto.createHash("sha256").update(key).digest().readUInt32BE(0) / HASH_RANGE;
}

// A Mega forme counts as its base species: "Charizard-Mega-Y" is charizard.
function baseSpeciesId(regulation, name) {
  const species = knownSpecies(regulation, name);
  if (!species.isMega) return species.id;
  const base = species.battleOnly ?? species.baseSpecies;
  if (typeof base !== "string") fail(`${name} has several battle-only bases`);
  return toID(base);
}

function knownSpecies(regulation, name) {
  const species = regulation.dex.species.get(name);
  return species.exists ? species : fail(`${name} is no species of the format`);
}

module.exports = {
  assumedSpreads,
  buildPresets,
  likelyNature,
  megaBatches,
  parseChaos,
  realSpread,
  realTeamSpecies,
  teammateShares,
  usageCard,
};
