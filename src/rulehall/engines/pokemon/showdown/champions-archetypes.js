const { compare, fail } = require("./net");

const RULES = require("./champions-archetypes.json");
const SETTER_MIN_SHARE = 0.5;
const CORE_COUNT = 2;
const MAX_REUSE = 2;
const REUSE_TOLERANCE = 0.8;

// Each archetype's setter, the most used species that holds its mechanic, with its top teammates.
function deriveArchetypes(regulation, kept, presets) {
  const mechanics = RULES.filter(hasMechanic);
  const holds = (entry, rule) => mechanicShare(regulation, entry, rule) >= SETTER_MIN_SHARE;
  const setterIds = new Set();
  const archetypes = [];
  for (const rule of RULES) {
    const setter = kept.find(
      (entry) =>
        !setterIds.has(entry.speciesId) &&
        (hasMechanic(rule)
          ? holds(entry, rule)
          : !mechanics.some((mechanic) => holds(entry, mechanic))),
    );
    if (setter === undefined) {
      console.error(`no ${rule.archetype_id} setter in ${regulation.formatId}`);
      continue;
    }
    setterIds.add(setter.speciesId);
    archetypes.push({ rule, setter });
  }
  if (!archetypes.some(({ rule }) => !hasMechanic(rule))) fail("no fallback archetype");
  const usage = new Map(kept.map((entry) => [entry.speciesId, entry]));
  const uses = new Map();
  const archetypeIds = archetypes.map(({ rule }) => rule.archetype_id);
  const usageOf = (speciesId) => usage.get(speciesId) ?? fail(`${speciesId} has no usage`);
  return archetypes.map(({ rule, setter }) => {
    const rivals = mechanics.filter((mechanic) => mechanic !== rule);
    const { sets, coreIds } = fillTeam(regulation, setter, kept, presets, usage, rivals, (id) =>
      setterIds.has(id) ? false : (uses.get(id) ?? 0) >= MAX_REUSE,
    );
    for (const set of sets) uses.set(set.species_id, (uses.get(set.species_id) ?? 0) + 1);
    return {
      archetype_id: rule.archetype_id,
      name: rule.name,
      setter_id: setter.speciesId,
      core_ids: coreIds,
      leads: [setter.speciesId, coreIds[0]],
      team: {
        archetype_ids: [
          rule.archetype_id,
          ...archetypeIdsOf(regulation, archetypeIds, sets, usageOf).filter(
            (archetypeId) => archetypeId !== rule.archetype_id,
          ),
        ],
        sets,
      },
    };
  });
}

// Every archetype whose mechanic the team holds; first the one whose holder shares the most
// teams with the other five. A team that holds none is the fallback's.
function archetypeIdsOf(regulation, archetypeIds, sets, usageOf) {
  const rules = RULES.filter((rule) => archetypeIds.includes(rule.archetype_id));
  const scored = rules.filter(hasMechanic).flatMap((rule) => {
    const holders = sets.filter((set) => holdsMechanic(regulation, set, rule));
    if (holders.length === 0) return [];
    const centrality = Math.max(...holders.map((holder) => centralityOf(holder, sets, usageOf)));
    return [{ archetypeId: rule.archetype_id, centrality }];
  });
  if (scored.length === 0) {
    const fallback = rules.find((rule) => !hasMechanic(rule)) ?? fail("no fallback archetype");
    return [fallback.archetype_id];
  }
  const primary = scored.reduce((top, each) => (each.centrality > top.centrality ? each : top));
  return [primary, ...scored.filter((each) => each !== primary)].map((each) => each.archetypeId);
}

function hasMechanic(rule) {
  return rule.ability_ids.length > 0 || rule.move_ids.length > 0;
}

function holdsMechanic(regulation, set, rule) {
  return (
    regulation.battleAbilityIds(set).some((abilityId) => rule.ability_ids.includes(abilityId)) ||
    set.move_ids.some((moveId) => rule.move_ids.includes(moveId))
  );
}

// The share of the species' teams whose set shows the mechanic, its Mega forme's ability included.
function mechanicShare(regulation, entry, rule) {
  const moveCount = Math.max(0, ...rule.move_ids.map((moveId) => entry.moves[moveId] ?? 0));
  const baseCount = rule.ability_ids.reduce(
    (total, abilityId) => total + (entry.abilities[abilityId] ?? 0),
    0,
  );
  const megaCount = Object.entries(entry.items)
    .filter(([itemId]) =>
      regulation
        .megaAbilityIds(itemId, entry.speciesId)
        .some((abilityId) => rule.ability_ids.includes(abilityId)),
    )
    .reduce((total, [, count]) => total + count, 0);
  return Math.max(moveCount, baseCount + megaCount) / entry.weight;
}

function centralityOf(holder, sets, usageOf) {
  const entry = usageOf(holder.species_id);
  const mates = sets.filter((set) => set !== holder);
  const shares = mates.map((mate) => (entry.teammates[mate.species_id] ?? 0) / entry.weight);
  return shares.reduce((total, value) => total + value, 0) / shares.length;
}

// The setter, its top teammates that fit as cores, then the species that share the most teams.
// No member but the setter holds a rival mechanic.
function fillTeam(regulation, setter, kept, presets, usage, rivals, overused) {
  const options = (speciesId) =>
    (presets[speciesId] ?? []).filter(
      (preset) => !rivals.some((rule) => holdsMechanic(regulation, preset, rule)),
    );
  const team = [
    fittingPreset(regulation, presets[setter.speciesId], []) ??
      fail(`${setter.speciesId} has no valid preset`),
  ];
  const mateIds = Object.keys(setter.teammates)
    .filter((speciesId) => usage.has(speciesId) && speciesId !== setter.speciesId)
    .sort((a, b) => setter.teammates[b] - setter.teammates[a] || compare(a, b));
  const coreIds = [];
  for (const speciesId of mateIds) {
    if (coreIds.length === CORE_COUNT) break;
    const preset = fittingPreset(regulation, options(speciesId), team);
    if (preset === undefined) continue;
    team.push(preset);
    coreIds.push(speciesId);
  }
  if (coreIds.length === 0) fail(`${setter.speciesId} has no teammate that fits`);
  while (team.length < regulation.teamSize) {
    const scored = kept
      .flatMap((entry) => {
        const preset = fittingPreset(regulation, options(entry.speciesId), team);
        if (preset === undefined) return [];
        return [{ speciesId: entry.speciesId, preset, score: teamShare(entry, team, usage) }];
      })
      .sort((a, b) => b.score - a.score || compare(a.speciesId, b.speciesId));
    const best = scored[0] ?? fail(`${setter.speciesId}: no species fits`);
    const fresh = scored.find(
      (candidate) =>
        !overused(candidate.speciesId) && candidate.score >= best.score * REUSE_TOLERANCE,
    );
    team.push((fresh ?? best).preset);
  }
  const problems = regulation.teamProblems(team);
  if (problems.length > 0) fail(`${setter.speciesId}: ${problems.join(" ")}`);
  return { sets: team, coreIds };
}

// A Mega preset first, at most one Mega per team.
function fittingPreset(regulation, options, team) {
  const hasMega = team.some((set) => regulation.isMegaStone(set.item_id));
  const fits = (options ?? []).filter(
    (preset) =>
      !(hasMega && regulation.isMegaStone(preset.item_id)) &&
      regulation.partialTeamProblems([...team, preset]).length === 0,
  );
  return fits.find((preset) => regulation.isMegaStone(preset.item_id)) ?? fits[0];
}

// The mean over the members of the share of their teams that also run the candidate.
function teamShare(candidate, team, usage) {
  const conditional = team.map((set) => {
    const member = usage.get(set.species_id) ?? fail(`${set.species_id} has no usage`);
    return (member.teammates[candidate.speciesId] ?? 0) / member.weight;
  });
  return conditional.reduce((total, value) => total + value, 0) / conditional.length;
}

module.exports = { archetypeIdsOf, deriveArchetypes };
