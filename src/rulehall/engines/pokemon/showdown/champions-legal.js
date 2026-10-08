const { Dex, TeamValidator, toID } = require("pokemon-showdown");
const { compare, fail } = require("./net");

const FORMAT_PREFIX = "gen9championsvgc";
const BO3_SUFFIX = "bo3";
// Showdown hard-codes the per-stat cap of Champions stat points.
const SP_MAX = 32;
const IV_MAX = 31;
const STAT_IDS = ["hp", "atk", "def", "spa", "spd", "spe"];

// The rules of one Champions VGC format: its dex, its caps, its validator and its Limitless name.
class Regulation {
  #validator;

  constructor(formatId) {
    const format = Dex.formats.get(formatId);
    if (!format.exists || !championsFormatIds().includes(format.id)) {
      fail(`${formatId} is no Champions VGC format of the pinned Showdown`);
    }
    const rules = Dex.formats.getRuleTable(format);
    this.formatId = format.id;
    this.limitlessFormat = regulationName(format);
    this.spTotal = rules.evLimit ?? fail(`${format.id} has no SP limit`);
    this.teamSize = rules.maxTeamSize;
    this.level = rules.adjustLevel ?? fail(`${format.id} adjusts no level`);
    this.movesMax = rules.maxMoveCount;
    this.dex = Dex.forFormat(format);
    this.#validator = TeamValidator.get(format);
  }

  setProblems(set) {
    return this.#validator.validateSet(this.#toShowdownSet(set), {}) ?? [];
  }

  teamProblems(sets) {
    return this.#validator.validateTeam(sets.map((set) => this.#toShowdownSet(set))) ?? [];
  }

  // The validator refuses any team under six, so a short team checks the two clauses by hand.
  partialTeamProblems(sets) {
    if (sets.length === this.teamSize) return this.teamProblems(sets);
    const problems = sets.flatMap((set) => this.setProblems(set));
    const nums = sets.map((set) => this.dex.species.get(set.species_id).num);
    if (new Set(nums).size < nums.length) problems.push("Species Clause");
    const itemIds = sets.map((set) => set.item_id);
    if (new Set(itemIds).size < itemIds.length) problems.push("Item Clause");
    return problems;
  }

  isMegaStone(itemId) {
    return this.dex.items.get(itemId).megaStone !== undefined;
  }

  megaStoneFits(itemId, speciesId) {
    return this.#megaOf(itemId, speciesId) !== undefined;
  }

  // The abilities a set can show in battle: its own, and its Mega forme's when it holds the stone.
  battleAbilityIds(set) {
    return [set.ability_id, ...this.megaAbilityIds(set.item_id, set.species_id)];
  }

  megaAbilityIds(itemId, speciesId) {
    const mega = this.#megaOf(itemId, speciesId);
    return mega === undefined ? [] : Object.values(this.dex.species.get(mega).abilities).map(toID);
  }

  legalData() {
    const species = {};
    for (const entry of this.dex.species.all()) {
      if (!entry.exists || entry.battleOnly || entry.isMega) continue;
      const probe = this.#toShowdownSet({
        species_id: entry.id,
        item_id: "",
        ability_id: toID(entry.abilities[0]),
        move_ids: [],
        nature: "Hardy",
        sp: STAT_IDS.map(() => 0),
      });
      const { tierSpecies } = this.#validator.getValidationSpecies(probe);
      if (this.#validator.checkSpecies(probe, entry, tierSpecies, {})) continue;
      const moveIds = [...this.dex.species.getMovePool(entry.id)]
        .filter(
          (moveId) => this.#validator.checkCanLearn(this.dex.moves.get(moveId), entry) === null,
        )
        .sort(compare);
      if (moveIds.length === 0) continue;
      const abilityIds = Object.values(entry.abilities)
        .map(toID)
        .filter((abilityId) => {
          const ability = this.dex.abilities.get(abilityId);
          return !this.#validator.checkAbility(probe, ability, {});
        })
        .sort(compare);
      species[entry.id] = {
        ability_ids: abilityIds,
        base_species_id: toID(entry.baseSpecies),
        move_ids: moveIds,
      };
    }
    const probe = { species: this.dex.species.get(Object.keys(species)[0]).name };
    const itemIds = this.dex.items
      .all()
      .filter((item) => item.exists && !this.#validator.checkItem(probe, item, {}))
      .map((item) => item.id)
      .sort(compare);
    const megaStones = {};
    for (const itemId of itemIds.filter((each) => this.isMegaStone(each))) {
      const holderIds = Object.keys(this.dex.items.get(itemId).megaStone)
        .map(toID)
        .filter((speciesId) => species[speciesId] !== undefined)
        .sort(compare);
      if (holderIds.length > 0) megaStones[itemId] = holderIds;
    }
    return {
      species,
      item_ids: itemIds,
      mega_stones: megaStones,
      sp_max: SP_MAX,
      sp_total: this.spTotal,
      team_size: this.teamSize,
      level: this.level,
      moves_max: this.movesMax,
    };
  }

  #megaOf(itemId, speciesId) {
    return this.dex.items.get(itemId).megaStone?.[this.dex.species.get(speciesId).name];
  }

  #toShowdownSet(set) {
    const name = this.dex.species.get(set.species_id).name;
    return {
      name,
      species: name,
      item: set.item_id,
      ability: set.ability_id,
      moves: [...set.move_ids],
      nature: set.nature,
      gender: "",
      evs: Object.fromEntries(STAT_IDS.map((statId, index) => [statId, set.sp[index]])),
      ivs: Object.fromEntries(STAT_IDS.map((statId) => [statId, IV_MAX])),
      level: this.level,
    };
  }
}

// The Champions VGC formats of the pinned Showdown, the newest regulation first.
function championsFormatIds() {
  return Dex.formats
    .all()
    .filter(
      (format) =>
        format.id.startsWith(FORMAT_PREFIX) &&
        !format.id.endsWith(BO3_SUFFIX) &&
        format.gameType === "doubles",
    )
    .map((format) => ({ formatId: format.id, name: regulationName(format) }))
    .sort((a, b) => compare(b.name, a.name))
    .map(({ formatId }) => formatId);
}

function regulationName(format) {
  return (format.name.match(/ Reg (\S+)$/) ?? fail(`${format.name}: no "Reg X" in the name`))[1];
}

module.exports = {
  BO3_SUFFIX,
  FORMAT_PREFIX,
  Regulation,
  SP_MAX,
  STAT_IDS,
  championsFormatIds,
};
