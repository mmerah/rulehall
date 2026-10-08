const path = require("path");
const { setTimeout: sleep } = require("timers/promises");
const { toID } = require("pokemon-showdown");
const { USER_AGENT, cachedText, compare, fail, fetchText } = require("./net");

const API = "https://play.limitlesstcg.com/api";
const HEADERS = { "User-Agent": USER_AGENT };
const PAGE_SIZE = 500;
const WINDOW_REQUESTS = 50;
const WINDOW_MS = 300_000;
const WINDOW_MARGIN_MS = 2_000;
const TOP_CUT = 8;
const TOP4_PLACING = 4;
const TOP4_MIN_PLAYERS = 128;
const FINALIST_PLACING = 2;
const FINALIST_EVENTS = 10;
const POOLS = ["finalist", "top4", "top8"];

// Keyless public API: at most 50 requests in 5 minutes. Player names never leave this class.
class LimitlessApi {
  #cacheDir;
  #sentAt = [];

  constructor(cacheDir) {
    this.#cacheDir = cacheDir;
  }

  get requests() {
    return this.#sentAt.length;
  }

  async tournaments(format) {
    const result = [];
    for (let page = 1; ; page++) {
      const query = `game=VGC&format=${encodeURIComponent(format)}&limit=${PAGE_SIZE}&page=${page}`;
      const batch = await this.#fetch(`/tournaments?${query}`);
      result.push(
        ...batch.map(({ id, name, date, players }) => ({ id, name: name.trim(), date, players })),
      );
      if (batch.length < PAGE_SIZE) return result;
    }
  }

  async standings(tournamentId) {
    const standings = await this.#cached(
      `/tournaments/${tournamentId}/standings`,
      `standings-${tournamentId}.json`,
    );
    return standings.map(({ placing, decklist }, index) => ({
      rank: index + 1,
      placing,
      decklist,
    }));
  }

  async #fetch(apiPath) {
    await this.#throttle();
    console.error(`GET ${API}${apiPath}`);
    return JSON.parse(await fetchText(API + apiPath, HEADERS));
  }

  async #cached(apiPath, cacheName) {
    const cachePath = path.join(this.#cacheDir, cacheName);
    return JSON.parse(await cachedText(API + apiPath, cachePath, HEADERS, () => this.#throttle()));
  }

  async #throttle() {
    const oldest = this.#sentAt.at(-WINDOW_REQUESTS);
    if (oldest !== undefined) {
      const wait = oldest + WINDOW_MS + WINDOW_MARGIN_MS - Date.now();
      if (wait > 0) {
        console.error(`rate limit: waiting ${Math.ceil(wait / 1000)} s`);
        await sleep(wait);
      }
    }
    this.#sentAt.push(Date.now());
  }
}

// The sets of a decklist, else why it cannot become a team. A decklist carries no SP.
function normaliseTeam(regulation, members, teamId, natureOf, spreadOf) {
  const sets = [];
  for (const member of members) {
    const set = toSet(regulation, member, teamId, natureOf, spreadOf);
    if (typeof set === "string") return set;
    sets.push(set);
  }
  return sets;
}

// Every decklist once, in its best pool, the newest first.
function selectTeams(candidates) {
  const finalistEventIds = largestEventIds(
    candidates.filter((candidate) => candidate.placing <= FINALIST_PLACING),
  );
  const poolOf = (candidate) => {
    if (candidate.placing <= FINALIST_PLACING && finalistEventIds.has(candidate.event.id)) {
      return "finalist";
    }
    if (candidate.placing <= TOP4_PLACING && candidate.event.players >= TOP4_MIN_PLAYERS) {
      return "top4";
    }
    return "top8";
  };
  const ranked = candidates
    .map((candidate) => ({ candidate, pool: poolOf(candidate) }))
    .sort(
      (a, b) =>
        POOLS.indexOf(a.pool) - POOLS.indexOf(b.pool) ||
        compare(b.candidate.event.date, a.candidate.event.date) ||
        compare(a.candidate.event.id, b.candidate.event.id) ||
        a.candidate.placing - b.candidate.placing,
    );
  const seen = new Set();
  const kept = [];
  for (const { candidate, pool } of ranked) {
    const key = teamKey(candidate.sets);
    if (seen.has(key)) continue;
    seen.add(key);
    kept.push(toRealTeam(candidate, pool));
  }
  if (new Set(kept.map((team) => team.team_id)).size < kept.length) {
    fail("two kept teams share an id");
  }
  return kept;
}

function toSet(regulation, member, teamId, natureOf, spreadOf) {
  const { dex } = regulation;
  const listed = dex.species.get(member.id);
  const base = typeof listed.battleOnly === "string" ? dex.species.get(listed.battleOnly) : listed;
  const item = dex.items.get(listed.isMega ? listed.requiredItem : member.item);
  const moves = member.attacks.map((name) => dex.moves.get(name));
  if (!listed.exists || !base.exists || !item.exists) return "unknown name";
  if (!moves.every((move) => move.exists)) return "unknown name";
  const species = stoneHolder(dex, item, base);
  const formeAbility =
    listed !== base ||
    regulation.megaAbilityIds(item.id, species.id).includes(toID(member.ability));
  const abilityId = abilityOf(dex, member, species, formeAbility);
  if (abilityId === undefined) return "unknown name";
  const moveIds = moves.map((move) => move.id);
  const listedNature = dex.natures.get(member.nature ?? "");
  const nature = listedNature.exists ? listedNature.name : natureOf(species.id, moveIds);
  if (nature === undefined) return "no nature";
  return {
    species_id: species.id,
    ability_id: abilityId,
    item_id: item.id,
    move_ids: moveIds,
    nature,
    sp: spreadOf(species.id, nature, `${teamId}-${species.id}`),
  };
}

function stoneHolder(dex, item, base) {
  if (item.megaStone === undefined || base.name !== base.baseSpecies) return base;
  const holders = Object.keys(item.megaStone).map((name) => dex.species.get(name));
  return holders.find((holder) => holder.baseSpecies === base.baseSpecies) ?? base;
}

// A Mega or battle forme, or its ability, is listed; the team sheet needs the base ability.
function abilityOf(dex, member, species, listedAsForme) {
  const ability = dex.abilities.get(member.ability);
  if (!ability.exists) return undefined;
  const legalIds = Object.values(species.abilities).map(toID);
  return listedAsForme && !legalIds.includes(ability.id) ? legalIds[0] : ability.id;
}

function largestEventIds(candidates) {
  const events = new Map(candidates.map((candidate) => [candidate.event.id, candidate.event]));
  const largest = [...events.values()]
    .sort((a, b) => b.players - a.players || compare(a.id, b.id))
    .slice(0, FINALIST_EVENTS);
  return new Set(largest.map((event) => event.id));
}

function toRealTeam(candidate, pool) {
  const { teamId, formatId, event, placing } = candidate;
  const date = event.date.slice(0, 10);
  return {
    team_id: teamId,
    label: `${placingLabel(placing)}, ${event.name}`,
    credit: `Limitless: ${event.name}, ${date}, placing ${placing}`,
    regulation: formatId,
    date,
    players: event.players,
    placing,
    pool,
    sets: candidate.sets,
  };
}

function placingLabel(placing) {
  if (placing === 1) return "Winner";
  if (placing === FINALIST_PLACING) return "Finalist";
  if (placing <= TOP4_PLACING) return "Top 4";
  return "Top 8";
}

// The same decklist from two events is one team: the picked SP name the event.
function teamKey(sets) {
  return sets
    .map(({ sp: _, ...set }) =>
      JSON.stringify({ ...set, move_ids: [...set.move_ids].sort(compare) }),
    )
    .sort(compare)
    .join("|");
}

module.exports = { LimitlessApi, POOLS, TOP_CUT, normaliseTeam, selectTeams };
