(() => {
  const me = battle.p2;
  const foe = battle.p1;
  const active = foe.active[0];
  const target = active && !active.fainted ? active : undefined;
  const saved = battle.prng.clone();
  const randomizer = battle.randomizer;
  const damage = (source, victim, moveId) => {
    if (!source || !victim || source.fainted || victim.fainted) return null;
    const move = battle.dex.getActiveMove(moveId);
    move.willCrit = false;
    const at = (roll) => {
      battle.randomizer = (base) => battle.trunc(battle.trunc(base * roll) / 100);
      const dealt = battle.actions.getDamage(source, victim, move, true);
      return typeof dealt === "number" ? dealt : dealt === false ? 0 : null;
    };
    const low = at(85);
    return low === null ? null : [low, at(100)];
  };
  const raised = (mon) => Object.fromEntries(Object.entries(mon.boosts).filter(([, stages]) => stages !== 0));
  const seen = target ? target.baseMoveSlots.filter((slot) => slot.used) : [];
  const team = me.pokemon.map((mon, index) => ({
    slot: index + 1,
    name: mon.name,
    level: mon.level,
    types: mon.getTypes(),
    hp: mon.hp,
    maxhp: mon.maxhp,
    status: mon.status,
    active: mon.isActive,
    boosts: raised(mon),
    moves: mon.baseMoveSlots.map((slot) => {
      const move = battle.dex.moves.get(slot.id);
      const dealt = damage(mon, target, slot.id);
      const percent = dealt && target ? dealt.map((hp) => Math.floor((100 * hp) / target.maxhp)) : null;
      return { name: move.name, type: move.type, pp: slot.pp, maxpp: slot.maxpp, disabled: !!slot.disabled, multihit: move.multihit || null, damage: dealt, percent };
    }),
    threats: seen.map((slot) => {
      const move = battle.dex.moves.get(slot.id);
      return { name: move.name, type: move.type, damage: damage(target, mon, slot.id) };
    }),
  }));
  const foes = foe.pokemon.map((mon) => ({
    name: mon.name,
    level: mon.level,
    types: mon.getTypes(),
    percent: Math.ceil((100 * mon.hp) / mon.maxhp),
    status: mon.status,
    active: mon.isActive,
    out: mon.previouslySwitchedIn > 0,
    boosts: raised(mon),
    moves: mon.baseMoveSlots.filter((slot) => slot.used).map((slot) => { const move = battle.dex.moves.get(slot.id); return { name: move.name, type: move.type }; }),
  }));
  battle.randomizer = randomizer;
  battle.prng = saved;
  return { team, foes };
})()
