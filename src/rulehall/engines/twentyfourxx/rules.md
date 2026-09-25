# 24XX RULES

24XX rules (v1.4) are CC BY Jason Tocci. <https://24xx-srd.carrd.co/>

## The sheet

A skill on the sheet is a d8, a d10 or a d12. A skill that is not on the sheet rolls a plain d6.
The sign ₡ marks credits. GEAR lists the items that the player carries. A bulky item takes much
space. Each item breaks a set number of times before the item is destroyed. A hindrance is a
thing that slows the actor, for example an injury or a fear.

## When to roll

Only roll to avoid a risk. Do not roll when there is no risk. Plain talk, careful unhurried work
and a certain outcome get no roll. Apply them directly. Set `skill` when a skill applies.

Every roll changes the situation. Do not roll a second time for the same attempt. If the actor
could simply try the same thing again, do not roll: say that they did it. A fight has no rounds.
One roll settles the attempt, not one blow of it.

Set `helped` when the conditions help, or when a party member who is not hired helps. The engine
adds one d6. Set `helped_by` when a hired member helps. That member rolls their own skill die. Set
`hindered` when something slows the actor. The die then becomes a d4.

## Reading a roll

- 1 to 2 is a disaster. The actor takes the full risk. You decide if the actor succeeds at all.
- 3 to 4 is a setback. The actor takes a lesser consequence, or gets a part of the success. A
  lesser consequence is one step down from `risk`: a risk of death leaves an injury, a risk of
  injury leaves a brief hindrance, and so on. Never write the full `risk` on the sheet after a
  setback.
- 5 or more is a success. If success cannot give the actor what they wanted, success gives useful
  information or a new advantage.

Set `risk` before the roll. The `risk` value is what goes wrong for the actor: an injury, a loss, a
cost or an alarm. Write it in a few words. Name only a danger that the story already told the player
about. Do not put a closed way forward in `risk`. Do not put the refusal of the person that the
actor speaks to in `risk`. On a disaster the actor takes `risk` in full. The engine does not write
`risk` on the sheet. Call a tool for each part that lasts. An injury is a hindrance. A fright that
passes and a lost moment are not. Set `deadly` when the risk is death. A disaster then kills the
actor. A setback then maims them. The engine writes that maiming on the sheet. Do not write your
own hindrance for the same wound.

Set `defend_with_id` when the player says what protects the actor: an item that the actor
carries, or a ship function. The named gear protects the actor on a disaster and on a setback.
The gear breaks instead. The `hindrance` value is the smaller thing that the hit leaves behind
after the gear takes it. The `hindrance` value is not `risk`. The `risk` value is only the danger
that the story told the player before the roll. Leave `hindrance` empty for gear that breaks with no
harm. If you give no `defend_with_id`, the consequence above lands in full.

## Gear and credits

Call `gain_item` to add an item. Most items cost ₡1. Call `drop_item` to lose an item
permanently. Call `repair_item` to repair broken gear. Call `spend` for every other payment by
the player, for example a bribe, medical care or passage.

## Defending

Call `defend` for a hit that the story gives outside a roll. One carried item or one ship
function breaks. The hit then becomes a hindrance. Broken gear does not work until somebody
repairs it.

## Hindrances

Call `change_hindrances` when the story gives the actor an injury that lasts.

An injury heals with time and medical attention. Read HINDRANCES before you act. Name in `lost`
each hindrance that time, care or a safe place has now mended. Calm medical care is unhurried
work, so it gets no roll.

One wound is one entry. When a wound gets worse, name the old entry in `lost` in the same call.

The hindrance that broken gear leaves is brief. Remove it when the moment ends. A hindered roll is
a d4, and a d4 cannot reach 5, so an actor who is hindered and not helped cannot succeed. Look for
help before you roll: a friend, a tool or good conditions. Set `helped` when you find it.

The engine does not read the hindrances. Set `hindered` only when an injury or the conditions work
against this action. Name what hinders. A condition that hinders one roll goes in `hindered` only.
The opinion of another person is not a hindrance. More than one bulky item can hinder the actor.

## The ship

THE SHIP lists the seven starship functions of the crew with their ids. Give a function as
`item_id` on `defend` or on `repair_item`. An item or a function marked harmless breaks with no
hindrance. Call `ship_upgrade` to upgrade one function for ₡10. Tell in the story what the
upgrade is.

THE HOLD lists what the crew stored on the ship. Call `lose_hold_item` when a raid, an impound or
a theft takes an item while the crew is away.

## Jobs

Call `job` with `find` and `where` when the player looks for work. Call `spend` to pay ₡1 for a
second `find`.

Call `job` with `take` and `terms` when the player agrees to the work. THE JOB then holds the
terms. The engine refuses a second job while a job is open.

Call `job` with `finish` when the story and the crew close the job. Give one `raises` entry for
the player. Give one `raises` entry for each living hired member. A job that the player never
takes needs no `take` and no `finish`. A `raises` skill that the actor does not have is new and
starts at d8.

## A member's help

A member without a sheet helps through `helped` only. The help of a hired member is `helped_by`.
For that member, set these fields:

- `risk` when the help gives the danger to that member too.
- `deadly` when that risk is death.
- `defend_with_id` when the gear of that member can protect them.
- `hindrance` for what that gear leaves behind.

A hindered helper rolls a d4.

## Hiring

To hire someone, call `join_party` with `terms`. A hired member acts like the player. Give the id
of that member in `actor_id` in every tool that has the field.

## Death and succession

The player can die. The rules then ask the player which hired member leads. The selected member
becomes the player. That member keeps their own name and id. The dead lead stays in the scene as
a body. The game ends when no hired member is alive.
