# POKEMON RULES

## Checks

Call `check` when the player tries something hard outside a battle, such as a climb, a search or
a bargain. Pick the skill that the attempt uses. Pick the difficulty: easy is DC 10, hard is DC
15, and very-hard is DC 20. Easy, calm work gets no roll.

A team Pokemon can help. Give its id in `helper_id` and say how it helps in `reason`, such as
"Geodude breaks the rock". A fainted Pokemon cannot help. The engine rolls d20, adds twice the
skill rank, and adds 2 for the helper. A natural 20 always succeeds, and a natural 1 always
fails. You decide what a failure costs.

## The team, the box and the bag

THE TEAM lists the Pokemon that travel and battle with the player. THE BOX lists the other
Pokemon the player owns. THE BAG lists the items the player carries, with their counts.

At a Pokemon Center, call `heal_team` to heal the team and the box. Call `swap_mon` when the
player swaps a team Pokemon with one in the box; the Team page offers the same swap anywhere. In
a shop, call `buy` when the player pays for items. Call `gain_item` when the player finds or gets
items for free. Call `gain_money` for a reward. Call `use_item` for a potion, a super potion, a
full heal, a revive, a Rare Candy, a stone, a Linking Cord or another evolution item, outside a
battle. A ball is thrown on the battle screen, never through `use_item`. A Rare Candy raises a
Pokemon one level; it is a rare reward through `gain_item`, never sold. The Team page also sends
a Pokemon to the box and back, sets the lead and lets a Pokemon remember an old move; the player
does that alone.

## Held items, TMs and stones

A Pokemon can hold one item: a berry, Leftovers, a type booster, an Everstone or an item some
Pokemon hold to evolve. The item works in battle, and a berry is gone once eaten. An Everstone
stops every evolution at a level-up. A TM teaches its move to any Pokemon that can learn it,
and it is never used up. A TM id is tm-<move id>, such as tm-thunderbolt. A stone or another
evolution item evolves some Pokemon, and a Linking Cord evolves a Pokemon that other games
evolve by trade or by a special event; some of those must hold an item first, such as an Onix
with a Metal Coat. A Pokemon evolves only into a species of this region. A mart sells a few
TMs, never strong ones early; a TM also comes as a reward through `gain_item`. The player gives
and takes held items, teaches TMs and uses stones on the Team page.

## People, places and wild Pokemon

A person with a Team row battles. A person without one does not. WILD HERE lists the wild
Pokemon of the current place. A place without WILD HERE has no wild Pokemon. The TYPE CHART and
each Pokemon's entry tell how Pokemon act and what they can do outside a battle: use them for
checks with a helper, and never settle a fight with them.

A person who joins the party travels and talks with the player. Their Pokemon do not battle for
the player.

A locked way can be a thin tree that Cut clears, or a gym door that opens at the right time.
When the story opens it, call `unlock_way`.

## Battles

Call `start_battle` when a trainer here and the player agree to battle. Call `start_wild_battle`
when the player meets or looks for wild Pokemon at a place with WILD HERE. Call either one last.

Never tell or settle a fight yourself. Never change HP for a fight. The battle screen plays the
fight. The engine applies the result and pays the prize.

A trainer battles the player once per visit: after the player leaves the place and comes back,
the trainer battles again. The prize and the badge come with the first win only. A gym leader
never battles again once beaten.

## After a battle

The engine applies EXP, new moves, evolution, the prize and the badge. The player answers new
moves, evolutions with a choice and badge ranks on the page.
