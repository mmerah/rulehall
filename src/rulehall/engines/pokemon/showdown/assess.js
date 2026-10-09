((me, foe, sheetOpen, estimates) => {
  const saved = battle.prng.clone();
  const randomizer = battle.randomizer;
  const AVERAGE_IV = 16;
  const IV_MAX = 31;
  const STAT_IDS = ["hp", "atk", "def", "spa", "spd", "spe"];
  const ABSORBS = { waterabsorb: "Water", stormdrain: "Water", dryskin: "Water", voltabsorb: "Electric", lightningrod: "Electric", motordrive: "Electric", flashfire: "Fire", wellbakedbody: "Fire", sapsipper: "Grass", eartheater: "Ground" };
  const SHIELDS = { bulletproof: "bullet", soundproof: "sound", windrider: "wind" };
  const PRIORITY_SHIELDS = ["dazzling", "queenlymajesty", "armortail"];
  const RULE_BREAKERS = ["moldbreaker", "teravolt", "turboblaze"];
  const SLOT_LETTERS = "abcdef";
  const REVEALED_BY = { choicelock: ({ item }) => Boolean(item && battle.dex.items.get(item).isChoice), metronome: ({ item }) => Boolean(item), unburden: ({ ability }) => ability };
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
  const nameOf = (ident) => ident.slice(ident.indexOf(": ") + 2);
  const slotOf = (ident) => ident.slice(0, ident.indexOf(":"));
  const faces = new Map();
  const seen = new Map();
  const onField = new Map();
  const fallen = new Set();
  const entrant = (ident, health) => {
    const fielded = [...onField.values()];
    const candidates = foe.pokemon.filter((mon) => !fielded.includes(mon) && !fallen.has(mon) && (mon.name === nameOf(ident) || mon.baseAbility === "illusion"));
    // The secret half of a switch line holds the real HP, which tells a disguised Pokemon from its face.
    const maxhp = Number(health.split(" ")[0].split("/")[1]);
    const fitting = candidates.filter((mon) => mon.maxhp === maxhp);
    const pool = fitting.length ? fitting : candidates;
    return pool.find((mon) => mon.name === nameOf(ident)) ?? pool[0];
  };
  lines.forEach((line, at) => {
    const [, kind, ident = "", detail = "", health = ""] = line.split("|");
    if (!ident.startsWith(foe.id)) return;
    const slot = slotOf(ident);
    const here = onField.get(slot);
    const sharedHalf = lines[at - 2] === `|split|${foe.id}`;
    if ((kind === "switch" || kind === "drag") && !sharedHalf) {
      const mon = entrant(ident, health);
      if (!mon) return;
      onField.set(slot, mon);
      faces.set(mon, foe.pokemon.find((each) => each.name === nameOf(ident)) ?? mon);
      seen.set(mon, at);
    }
    if (kind === "replace" && here) {
      faces.set(here, here);
      seen.set(here, at);
    }
    if (kind === "faint" && here) fallen.add(here);
    if (kind === "swap") {
      const other = `${foe.id}${SLOT_LETTERS[Number(detail)]}`;
      const there = onField.get(other);
      onField.set(other, here);
      onField.set(slot, there);
    }
  });
  const statsOf = (values) => Object.fromEntries(STAT_IDS.map((statId, index) => [statId, values[index]]));
  const even = (value) => statsOf(STAT_IDS.map(() => value));
  const faceOf = (mon) => (mon.side === foe ? faces.get(mon) ?? mon : mon);
  const shownFor = (shown, mon) => shown.get(`${mon.side.id}: ${faceOf(mon).name}`) ?? [];
  const revealed = (mon) => {
    const face = faceOf(mon);
    if (sheetOpen) return { ability: true, item: face.item ? face.getItem().name : "" };
    const items = shownFor(shownItems, face);
    const item = face.item ? (items.includes(face.getItem().name) ? face.getItem().name : null) : items.length ? "" : null;
    return { ability: shownFor(shownAbilities, face).includes(face.getAbility().name), item };
  };
  const estimated = (mon) => {
    const face = faceOf(mon);
    const estimate = estimates[foe.team.indexOf(face.set)];
    const spread = estimate ? { level: mon.level, nature: estimate.nature, evs: statsOf(estimate.sp), ivs: even(IV_MAX) } : { level: mon.level, nature: "Hardy", evs: even(0), ivs: even(AVERAGE_IV) };
    return battle.spreadModify(face.species.baseStats, spread);
  };
  const disguise = (mon) => {
    if (mon.side !== foe) return () => {};
    const face = faceOf(mon);
    const kept = { storedStats: mon.storedStats, ability: mon.ability, item: mon.item, hp: mon.hp, maxhp: mon.maxhp, species: mon.species, baseSpecies: mon.baseSpecies, types: mon.types, weighthg: mon.weighthg };
    const { hp, ...stats } = estimated(mon);
    mon.storedStats = stats;
    mon.maxhp = hp;
    mon.hp = kept.hp && Math.max(1, Math.round((hp * kept.hp) / kept.maxhp));
    const { ability, item } = revealed(mon);
    mon.ability = ability ? face.ability : "noability";
    mon.item = item === null ? "" : face.item;
    Object.assign(mon, { species: face.species, baseSpecies: face.baseSpecies, types: face.types, weighthg: face.weighthg });
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
  const hides = (mon, id) => mon.side === foe && Object.hasOwn(REVEALED_BY, id) && !REVEALED_BY[id](revealed(mon));
  const volatiles = (mon) => Object.keys(mon.volatiles).filter((id) => !hides(mon, id));
  const seenMoves = (mon) => faceOf(mon).moveSlots.filter((slot) => sheetOpen || slot.used).map((slot) => battle.dex.moves.get(slot.id));
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
  const appeared = foe.pokemon.filter((mon) => mon.previouslySwitchedIn > 0);
  // The player sees one Pokemon per face: a disguised foe merges with its face, the one seen last first.
  const rank = (mon) => (mon.isActive ? Infinity : seen.get(mon) ?? -1);
  const shown = appeared.filter((mon) => !appeared.some((other) => faceOf(other) === faceOf(mon) && rank(other) > rank(mon)));
  const foes = shown.map((mon) => {
    const { ability: shownAbility, item } = revealed(mon);
    const face = faceOf(mon);
    const ability = shownAbility ? face.getAbility().name : null;
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
})(ARGUMENTS)
