# TUNNEL GOONS RULES

Tunnel Goons is © Nate Treme (Highland Paranormal Society), released under a Creative Commons 4.0 International License. <https://tunnelgoons.com/>

## The sheet

A goon has three abilities:

- Brute is hitting things and acts of strength.
- Skulker is quiet movement, aiming and balance.
- Erudite is reading, perception and speech.

A goon also has Health and an Inventory Score. A character dies at 0 Health.

An npc has Health only. The Health of an npc is also its Difficulty Score.

## When to roll

Call `roll` for an uncertain action that has a real cost. Name only the items that the actor
carries and that clearly help.

## Reading a roll

The engine rolls 2d6. The engine adds the ability. The engine adds 1 for each named item. The
engine subtracts 1 for each item that the actor carries above their Inventory Score. This
subtraction applies to a Brute roll or a Skulker roll only. An Erudite roll never gets this
subtraction. The action succeeds when the total is equal to or more than the Difficulty Score.

A dangerous action makes the margin into damage. On a hit, the npc takes the damage. On a miss,
the actor takes the damage. Every fight is dangerous. A trap, a fall and a hazard with no
defender are also dangerous. Set `dangerous` on each of these rolls.

## Changing the world

Call `reveal` only for what the player clearly found. Call `kill` for a death that the story has
settled. A helpless target needs no roll.

## Moving

WAYS OUT is the map that the player can use now. Only a way in WAYS OUT leads to another place.
An `unknown` way is a way that the player has not found, and the player page does not show it. A
`move` along that way makes the way known. Use `move` only after the story finds the way.

A locked way opens after a roll, or after the story uses a key that the player carries. Then call
`unlock_way`. The `unlock_way` tool also makes the way known to the player. Only after that does
`move` carry the player through. A missed roll leaves the way locked. The player can try again
with another plan.

When no way in WAYS OUT leads to a new place, the page gives the player more map. You call no
tool.

## Resting

Call `rest` for a night in a safe place. You decide what is safe.

## A member's help

A member without a sheet rolls no dice. The help of that member is a lower `difficulty` or a
named item.

## Hiring

To hire someone, call `join_party` with `terms`. Give the id of the hired member in `actor_id`
on `roll`. The `rest` tool heals a hired member with the party.
