((me, foe) => {
  const saved = battle.prng.clone();
  const randomizer = battle.randomizer;
  const AVERAGE_IV = 16;
  const ABSORBS = { waterabsorb: "Water", stormdrain: "Water", dryskin: "Water", voltabsorb: "Electric", lightningrod: "Electric", motordrive: "Electric", flashfire: "Fire", wellbakedbody: "Fire", sapsipper: "Grass", eartheater: "Ground" };
  const SHIELDS = { bulletproof: "bullet", soundproof: "sound", windrider: "wind" };
  const PRIORITY_SHIELDS = ["dazzling", "queenlymajesty", "armortail"];
  const RULE_BREAKERS = ["moldbreaker", "teravolt", "turboblaze"];
  const lines = battle.log.filter((line) => !line.startsWith("||"));
  const holderOf = (ident) => ident.replace(/^(p\d)[a-z]?: /, "$1: ");
  const shownAbilities = new Map();
  const shownItems = new Map();
  const note = (shown, ident, name) => shown.set(holderOf(ident), [...(shown.get(holderOf(ident)) ?? []), name]);
  for (const line of lines) {
    const [, kind, ...fields] = line.split("|");
    const [lead = "", named = ""] = fields;
    const of = fields.find((field) => field.startsWith("[of] "));
    if (kind === "-ability") note(shownAbilities, lead, named);
    if (kind === "-item" || kind === "-enditem") note(shownItems, lead, named);
    for (const field of fields) {
      const from = field.startsWith("[from] ");
      const effect = field.replace(/^\[from\] /, "");
      const holder = from && of ? of.slice("[of] ".length) : lead;
      if (effect.startsWith("ability: ")) note(shownAbilities, holder, effect.slice("ability: ".length));
      if (effect.startsWith("item: ")) note(shownItems, holder, effect.slice("item: ".length));
    }
  }
  const faceOf = (mon) => (mon.side === foe ? mon.illusion ?? mon : mon);
  const shownFor = (shown, mon) => shown.get(`${mon.side.id}: ${faceOf(mon).name}`) ?? [];
  const revealed = (mon) => {
    const items = shownFor(shownItems, mon);
    const item = mon.item ? (items.includes(mon.getItem().name) ? mon.getItem().name : null) : items.length ? "" : null;
    return { ability: shownFor(shownAbilities, mon).includes(mon.getAbility().name), item };
  };
  const estimated = (mon) => {
    const spread = { level: mon.level, nature: "Hardy", evs: { hp: 0, atk: 0, def: 0, spa: 0, spd: 0, spe: 0 }, ivs: { hp: AVERAGE_IV, atk: AVERAGE_IV, def: AVERAGE_IV, spa: AVERAGE_IV, spd: AVERAGE_IV, spe: AVERAGE_IV } };
    return battle.spreadModify(mon.species.baseStats, spread);
  };
  const disguise = (mon) => {
    if (mon.side !== foe) return () => {};
    const kept = { storedStats: mon.storedStats, ability: mon.ability, item: mon.item, hp: mon.hp, maxhp: mon.maxhp };
    const { hp, ...stats } = estimated(mon);
    mon.storedStats = stats;
    mon.maxhp = hp;
    mon.hp = kept.hp && Math.max(1, Math.round((hp * kept.hp) / kept.maxhp));
    const { ability, item } = revealed(mon);
    if (!ability) mon.ability = "noability";
    if (item === null) mon.item = "";
    return () => Object.assign(mon, kept);
  };
  const breaksRules = (mon) => RULE_BREAKERS.includes(mon.getAbility().id);
  const shieldOf = (source, victim, move) => {
    const ability = victim.getAbility();
    if (breaksRules(source)) return "";
    const flag = SHIELDS[ability.id];
    const shielded = ABSORBS[ability.id] === move.type || (flag && move.flags[flag]) || (ability.id === "wonderguard" && victim.runEffectiveness(move) <= 0) || (PRIORITY_SHIELDS.includes(ability.id) && move.priority > 0);
    return shielded ? ability.name : "";
  };
  const hitsOf = (source, move) => {
    if (!Array.isArray(move.multihit)) return [move.multihit || 1, move.multihit || 1];
    const [fewest, most] = move.multihit;
    if (source.hasAbility("skilllink")) return [most, most];
    return source.hasItem("loadeddice") && most === 5 ? [4, 5] : [fewest, most];
  };
  const enduredBy = (source, victim) => {
    if (victim.hp !== victim.maxhp) return "";
    if (victim.hasItem("focussash")) return "Focus Sash";
    return victim.hasAbility("sturdy") && !breaksRules(source) ? "Sturdy" : "";
  };
  const hit = (source, victim, moveId, spread) => {
    const move = battle.dex.getActiveMove(moveId);
    if (move.category === "Status") return null;
    move.willCrit = false;
    move.spreadHit = spread;
    const undo = [disguise(source), disguise(victim)];
    try {
      const at = (roll) => {
        battle.randomizer = (base) => battle.trunc(battle.trunc(base * roll) / 100);
        return battle.actions.getDamage(source, victim, move, true);
      };
      const shield = shieldOf(source, victim, move);
      const low = at(85);
      const immune = low === false || shield !== "";
      const [fewest, most] = hitsOf(source, move);
      const damage = immune || !low ? null : [low * fewest, at(100) * most];
      const endured = damage !== null && most === 1 && !move.ohko && damage[1] >= victim.hp ? enduredBy(source, victim) : "";
      return {
        hp: victim.hp,
        maxhp: victim.maxhp,
        damage,
        hits: [fewest, most],
        multiplier: immune ? 0 : 2 ** victim.runEffectiveness(move),
        shield,
        endured,
        one_hit_ko: Boolean(move.ohko),
      };
    } finally {
      undo.reverse().forEach((restore) => restore());
    }
  };
  const speedOf = (mon) => {
    const undo = disguise(mon);
    try {
      return mon.getStat("spe");
    } finally {
      undo();
    }
  };
  const standing = (side) => side.active.flatMap((mon, index) => (mon && !mon.fainted ? [{ mon, position: index + 1 }] : []));
  const reach = (user, move) => {
    const foes = standing(foe).map(({ mon, position }) => ({ mon, target: position }));
    const partners = standing(me).filter(({ mon }) => mon !== user).map(({ mon, position }) => ({ mon, target: -position }));
    const aimed = move.target === "allAdjacent" ? [...foes, ...partners] : foes;
    const spread = ["allAdjacent", "allAdjacentFoes"].includes(move.target) && aimed.length > 1;
    return { aimed, spread };
  };
  const raised = (mon) => Object.fromEntries(Object.entries(mon.boosts).filter(([, stages]) => stages !== 0));
  const statLine = ({ atk, def, spa, spd, spe }) => [atk, def, spa, spd, spe];
  const lockOf = (mon, slot, move) => {
    if (slot.pp <= 0) return "no PP left";
    if (!slot.disabled) return "";
    const effects = mon.volatiles;
    if (effects.disable && effects.disable.move === slot.id) return "Disable blocks it";
    if (effects.encore && effects.encore.move !== slot.id) return "Encore forces its last move";
    if (effects.choicelock && effects.choicelock.move !== slot.id) return "its choice item locks it into another move";
    if (effects.taunt && move.category === "Status") return "Taunt allows only attacks";
    if (effects.torment && mon.lastMove && mon.lastMove.id === slot.id) return "Torment forbids the same move twice in a row";
    if (effects.healblock && move.flags.heal) return "Heal Block stops healing moves";
    if (effects.throatchop && move.flags.sound) return "Throat Chop stops sound moves";
    if (mon.hasItem("assaultvest") && move.category === "Status") return "Assault Vest allows only attacks";
    if (move.flags.gravity && battle.field.getPseudoWeather("gravity")) return "Gravity stops it";
    if (move.flags.cantusetwice && mon.lastMove && mon.lastMove.id === slot.id) return "it cannot be used twice in a row";
    return "it cannot be used this turn";
  };
  const effect = (id, state) => ({ id, name: battle.dex.conditions.get(id).name || id, turns: state.duration || 0, layers: state.layers || 0 });
  const conditions = (side) => Object.entries(side.sideConditions).map(([id, state]) => effect(id, state));
  const volatiles = (mon) => Object.keys(mon.volatiles);
  const seenMoves = (mon) => mon.moveSlots.filter((slot) => slot.used).map((slot) => battle.dex.moves.get(slot.id));
  const place = (mon) => (mon.isActive ? mon.position + 1 : 0);
  const team = me.pokemon.map((mon, index) => ({
    slot: index + 1,
    name: mon.name,
    species: mon.species.name,
    level: mon.level,
    types: mon.getTypes(),
    hp: mon.hp,
    maxhp: mon.maxhp,
    status: mon.status,
    position: place(mon),
    boosts: raised(mon),
    volatiles: volatiles(mon),
    ability: mon.getAbility().name,
    item: mon.item ? mon.getItem().name : "",
    stats: statLine(mon.storedStats),
    speed: mon.fainted ? 0 : speedOf(mon),
    moves: mon.moveSlots.map((slot) => {
      const move = battle.dex.moves.get(slot.id);
      const { aimed, spread } = reach(mon, move);
      const hits = mon.fainted ? [] : aimed.flatMap(({ mon: victim, target }) => {
        const dealt = hit(mon, victim, slot.id, spread);
        return dealt ? [{ target, name: faceOf(victim).name, ...dealt }] : [];
      });
      return { name: move.name, type: move.type, category: move.category, priority: move.priority, pp: slot.pp, maxpp: slot.maxpp, lock: lockOf(mon, slot, move), target: move.target, hits };
    }),
    threats: mon.fainted ? [] : standing(foe).flatMap(({ mon: attacker }) => seenMoves(attacker).flatMap((move) => {
      const dealt = hit(attacker, mon, move.id, false);
      return dealt ? [{ user: faceOf(attacker).name, name: move.name, type: move.type, ...dealt }] : [];
    })),
  }));
  const shown = foe.pokemon.filter((mon) => mon.previouslySwitchedIn > 0);
  const foes = shown.map((mon) => {
    const { ability: shownAbility, item } = revealed(mon);
    const ability = shownAbility ? mon.getAbility().name : null;
    const face = faceOf(mon);
    return {
      name: face.name,
      species: face.species.name,
      level: mon.level,
      types: face === mon ? mon.getTypes() : face.species.types,
      hp: mon.hp,
      maxhp: mon.maxhp,
      status: mon.status,
      position: place(mon),
      boosts: raised(mon),
      volatiles: volatiles(mon),
      ability,
      abilities: ability === null ? [...new Set(Object.values(face.species.abilities))] : [],
      item,
      stats: statLine(estimated(mon)),
      speed: mon.fainted ? 0 : speedOf(mon),
      moves: seenMoves(mon).map((move) => ({ move_id: move.id, priority: move.priority })),
    };
  });
  const weather = battle.field.weather;
  const terrain = battle.field.terrain;
  battle.randomizer = randomizer;
  battle.prng = saved;
  return {
    turn: battle.turn,
    weather: weather ? effect(weather, battle.field.weatherState) : null,
    terrain: terrain ? effect(terrain, battle.field.terrainState) : null,
    rooms: Object.entries(battle.field.pseudoWeather).map(([id, state]) => effect(id, state)),
    own_side: conditions(me),
    foe_side: conditions(foe),
    team,
    foes,
    unseen: foe.pokemon.length - shown.length,
  };
})(SIDES)
