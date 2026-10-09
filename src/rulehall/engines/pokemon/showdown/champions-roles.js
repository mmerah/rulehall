const { compare } = require("./net");

const RULES = require("./champions-roles.json");
const SURE_CHANCE = 100;
const SCREENS = ["reflect", "lightscreen", "auroraveil"];
const PREDICATES = {
  "speed-control": (move) =>
    move.sideCondition === "tailwind" ||
    move.pseudoWeather === "trickroom" ||
    slowsFoe(move),
  "wide-guard": (move) => move.sideCondition === "wideguard",
  screens: (move) => SCREENS.includes(move.sideCondition),
  // Rage Powder has its own volatile status, so the redirect hook names the role.
  redirect: (move) => move.target === "self" && move.condition?.onFoeRedirectTarget !== undefined,
};

// Each role's legal moves and abilities: the ids its rule names and the moves its predicate holds.
function deriveRoles(regulation, legal) {
  const species = Object.values(legal.species);
  const legalMoveIds = [...new Set(species.flatMap((each) => each.move_ids))].sort(compare);
  const legalAbilityIds = new Set(species.flatMap((each) => each.ability_ids));
  return Object.fromEntries(
    RULES.map((rule) => {
      const holds = PREDICATES[rule.role_id] ?? (() => false);
      const moveIds = legalMoveIds.filter(
        (moveId) => rule.move_ids.includes(moveId) || holds(regulation.dex.moves.get(moveId)),
      );
      const abilityIds = rule.ability_ids.filter((abilityId) => legalAbilityIds.has(abilityId));
      return [rule.role_id, { name: rule.name, move_ids: moveIds, ability_ids: abilityIds }];
    }),
  );
}

// The move or a sure secondary lowers a foe's Speed or paralyses it.
function slowsFoe(move) {
  const effects = [
    ...(move.target === "self" ? [] : [move]),
    ...(move.secondaries ?? []).filter((secondary) => secondary.chance === SURE_CHANCE),
  ];
  return effects.some((effect) => (effect.boosts?.spe ?? 0) < 0 || effect.status === "par");
}

module.exports = { deriveRoles };
