const fs = require("fs");
const path = require("path");
const { parseArgs } = require("util");
const { USER_AGENT, cachedText, compare, fail, fetchText } = require("./net");
const { BO3_SUFFIX, FORMAT_PREFIX, Regulation, championsFormatIds } = require("./champions-legal");
const {
  assumedSpreads,
  buildPresets,
  likelyNature,
  megaBatches,
  parseChaos,
  realSpread,
  realTeamSpecies,
  teammateShares,
  usageCard,
} = require("./champions-usage");
const {
  LimitlessApi,
  POOLS,
  TOP_CUT,
  normaliseTeam,
  selectTeams,
} = require("./champions-limitless");
const { archetypeIdsOf, deriveArchetypes } = require("./champions-archetypes");

const OUTPUT = path.join(__dirname, "..", "champions", "data.json");
const CACHE_DIR = path.join(__dirname, ".cache");
const STATS_URL = "https://www.smogon.com/stats";
const HEADERS = { "User-Agent": USER_AGENT };
const MIN_PLAYERS = 64;
const TOP_SPECIES = 60;
const POOL_SIZE = 40;
// A species on this many real teams is draftable even when the ladder top lacks it.
const FILL_MIN_TEAMS = 8;

async function main() {
  const flags = readFlags();
  console.error(`chaos files and standings cached in ${CACHE_DIR}`);
  const { regulation, chaos, source } = await loadChaos(flags);
  const ladder = new Map(chaos.ranked.map((entry) => [entry.speciesId, entry]));
  const formatIds = championsFormatIds();
  const index = formatIds.indexOf(regulation.formatId);
  const realTeams = await loadRealTeams(regulation, formatIds.slice(index, index + 2), ladder);
  const onTeams = realTeamSpecies(realTeams);
  const entryOf = (speciesId) =>
    ladder.get(speciesId) ?? onTeams.get(speciesId) ?? fail(`${speciesId} has no usage`);
  const top = chaos.ranked.slice(0, TOP_SPECIES);
  const topIds = new Set(top.map((entry) => entry.speciesId));
  const fill = [...onTeams.values()]
    .filter((entry) => entry.weight >= FILL_MIN_TEAMS && !topIds.has(entry.speciesId))
    .sort((a, b) => b.weight - a.weight || compare(a.speciesId, b.speciesId))
    .map((entry) => entryOf(entry.speciesId));
  const presets = {};
  for (const entry of [...top, ...fill]) {
    const built = buildPresets(regulation, entry);
    if (built.length > 0) presets[entry.speciesId] = built;
  }
  const kept = [...top, ...fill].filter((entry) => presets[entry.speciesId] !== undefined);
  const keptFill = fill.filter((entry) => kept.includes(entry));
  // Every species a foe can bring needs an assumed spread and a usage card.
  const knownIds = [
    ...new Set([...kept.map((entry) => entry.speciesId), ...[...onTeams.keys()].sort(compare)]),
  ];
  const archetypes = deriveArchetypes(regulation, kept, presets);
  const archetypeIds = archetypes.map((archetype) => archetype.archetype_id);
  const data = {
    source,
    legal: regulation.legalData(),
    presets,
    assumed: Object.fromEntries(knownIds.map((id) => [id, assumedSpreads(entryOf(id))])),
    usage: Object.fromEntries(
      knownIds.map((id) => [id, usageCard(entryOf(id), ladder.has(id) ? "smogon" : "limitless")]),
    ),
    teammates: teammateShares(kept),
    pool: {
      species_ids: [
        ...kept.filter((entry) => topIds.has(entry.speciesId)).slice(0, POOL_SIZE),
        ...keptFill,
      ].map((entry) => entry.speciesId),
      mega_batches: megaBatches(regulation, chaos.megaUsage, presets),
    },
    archetypes,
    real_teams: realTeams.map((team) => ({
      ...team,
      archetype_ids: archetypeIdsOf(regulation, archetypeIds, team.sets, entryOf),
    })),
  };
  fs.writeFileSync(OUTPUT, JSON.stringify(sortedKeys(data), null, 1) + "\n");
  const presetCount = Object.values(presets).flat().length;
  console.log(`${source.format_id} ${source.month}, cutoff ${source.cutoff}`);
  console.log(`${Object.keys(data.legal.species).length} legal species`);
  console.log(`${kept.length} species with presets (${keptFill.length} from real teams)`);
  console.log(`${presetCount} presets, ${knownIds.length} usage cards`);
  console.log(`${archetypes.length} archetypes with a template team`);
  console.log(`${realTeams.length} real teams`);
  for (const pool of POOLS) {
    console.log(`  ${pool}: ${realTeams.filter((team) => team.pool === pool).length}`);
  }
  for (const formatId of new Set(realTeams.map((team) => team.regulation))) {
    const count = realTeams.filter((team) => team.regulation === formatId).length;
    console.log(`  ${formatId}: ${count}`);
  }
  for (const { archetype_id, setter_id, core_ids, team } of archetypes) {
    const holding = data.real_teams.filter((each) => each.archetype_ids.includes(archetype_id));
    const primary = holding.filter((each) => each.archetype_ids[0] === archetype_id);
    console.log(
      `${archetype_id}: ${setter_id} with ${core_ids.join(", ")}; ` +
        `template holds ${team.archetype_ids.join(", ")}; ` +
        `${holding.length} real teams, ${primary.length} primary`,
    );
  }
  console.log(`${fs.statSync(OUTPUT).size} bytes`);
}

function readFlags() {
  const { values } = parseArgs({
    options: {
      month: { type: "string" },
      format: { type: "string" },
      cutoff: { type: "string", default: "1760" },
    },
  });
  if (values.month !== undefined && !/^\d{4}-\d{2}$/.test(values.month)) {
    fail("--month must look like 2026-09");
  }
  if (!/^\d+$/.test(values.cutoff)) fail("--cutoff must be a number, for example 1760");
  const formatIds = championsFormatIds();
  if (values.format !== undefined && !formatIds.includes(values.format)) {
    fail(`--format must be one of ${formatIds.join(", ")}`);
  }
  return values;
}

// The newest Champions VGC format of the pinned Showdown with a bo3 chaos file, else the previous.
async function loadChaos(flags) {
  const formatIds = flags.format === undefined ? championsFormatIds().slice(0, 2) : [flags.format];
  const months = flags.month === undefined ? await smogonMonths() : [flags.month];
  for (const formatId of formatIds) {
    const fileName = `${formatId}${BO3_SUFFIX}-${flags.cutoff}.json`;
    for (const month of months) {
      const listing = await smogonListing(`${month}/chaos/`);
      // A month before Champions ends the search.
      if (!listing.includes(`href="${FORMAT_PREFIX}`)) break;
      if (!listing.includes(`href="${fileName}"`)) continue;
      const regulation = new Regulation(formatId);
      const raw = JSON.parse(
        await cachedText(
          `${STATS_URL}/${month}/chaos/${fileName}`,
          path.join(CACHE_DIR, "smogon", month, fileName),
          HEADERS,
        ),
      );
      const chaos = parseChaos(regulation, raw);
      const { cutoff, battles } = chaos;
      return { regulation, chaos, source: { format_id: formatId, month, cutoff, battles } };
    }
  }
  return fail(`no Smogon month publishes ${formatIds.join(" or ")} at ${flags.cutoff}`);
}

async function smogonMonths() {
  const index = await smogonListing("");
  return [...index.matchAll(/href="(\d{4}-\d{2})\/"/g)].map(([, month]) => month).sort().reverse();
}

// A listing grows, so it is fetched each run.
function smogonListing(urlPath) {
  console.error(`GET ${STATS_URL}/${urlPath}`);
  return fetchText(`${STATS_URL}/${urlPath}`, HEADERS);
}

// The top cut decklists of every big event of the played formats, legal in the current one.
async function loadRealTeams(regulation, playedIds, ladder) {
  const api = new LimitlessApi(path.join(CACHE_DIR, "limitless"));
  const natureOf = (speciesId, moveIds) =>
    likelyNature(regulation, ladder.get(speciesId), moveIds);
  const spreadOf = (speciesId, nature, key) =>
    realSpread(regulation, ladder.get(speciesId), speciesId, nature, key);
  const skipped = { "no nature": 0, "unknown name": 0, illegal: 0 };
  const candidates = [];
  let eventCount = 0;
  for (const formatId of playedIds) {
    const played = new Regulation(formatId);
    const events = (await api.tournaments(played.limitlessFormat)).filter(
      (event) => event.players >= MIN_PLAYERS,
    );
    eventCount += events.length;
    for (const event of events) {
      for (const standing of await api.standings(event.id)) {
        if (standing.placing === null || standing.placing > TOP_CUT) continue;
        if (standing.decklist?.length !== regulation.teamSize) continue;
        // Tied placings share a number, so the id takes the row of the standings.
        const teamId = `limitless-${event.id}-${standing.rank}`;
        const sets = normaliseTeam(regulation, standing.decklist, teamId, natureOf, spreadOf);
        if (typeof sets === "string") skipped[sets]++;
        else if (regulation.teamProblems(sets).length > 0) skipped.illegal++;
        else candidates.push({ teamId, formatId, event, placing: standing.placing, sets });
      }
    }
  }
  console.error(`${eventCount} events, ${api.requests} Limitless requests`);
  console.error(
    `skipped: ${Object.entries(skipped)
      .map(([why, count]) => `${count} ${why}`)
      .join(", ")}; ${candidates.length} legal teams`,
  );
  return selectTeams(candidates);
}

function sortedKeys(value) {
  if (Array.isArray(value)) return value.map(sortedKeys);
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort(compare)
      .map((key) => [key, sortedKeys(value[key])]),
  );
}

main();
