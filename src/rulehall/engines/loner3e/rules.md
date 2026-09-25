# LONER 3E RULES

Loner 3e rules CC BY-SA Roberto Bisceglie, Zotiquest Games — lonersrd.zotiquestgames.com

## The sheet

Every thing in the game is a character: a person, an object, a vehicle or a curse. Each
character has a one-line concept. Each character has tags by kind: skills, frailties, gear and
conditions. Tags are words, not numbers. A living character also has a goal, a motive and a
nemesis.

Luck is not health. Luck shows how long a character holds out in a conflict. The player starts
with 6 luck. Each other character holds out for as long as its own luck pool.

## Tags and drives

Call `change_tags` when the story clearly gives a tag or removes a tag. Call `drive` when play
shows what a character wants, why the character wants it, or who is against the character.

The SPECIAL RULES of the selected pack can give a cost in luck. Then call `spend_luck` with the
printed cost before the `roll` that decides the action. Read that roll as those rules tell you.

## When to roll

Call `roll` when the answer is uncertain and yes and no both change the story. When you are not
sure, roll. A real cost for no is enough. Danger, combat, pursuit, stealth and haste always need
a roll. Roll before you tell the outcome.

Do not roll for a quiet arrival, for plain conversation, or for a certain outcome. A helpless
enemy dies for certain. Call `kill`, or the correct tool, instead. For a dangerous arrival or a
dangerous departure, roll first. Then call `enter` or `leave`.

The actor is the character who does the uncertain thing. If a monster attacks, ask about the
monster.

Set `position` from the story. Set `position` to `advantage` when a skill, a gear tag, a
condition or the situation clearly helps the actor. Set `position` to `disadvantage` when a
frailty, an opposed tag or the situation clearly works against the actor. Set `position` to
`neutral` when no side clearly wins. Many tags together give one edge at most.

## Reading a roll

The engine gives one of six results:

- `yes-and` is success with an extra benefit.
- `yes` is success.
- `yes-but` is success with a cost.
- `no-but` is failure that keeps a chance open.
- `no` is failure. That approach does not work.
- `no-and` is failure with a worse situation.

Keep an answered question settled. A new approach is a new question. If a result does not fit
easily, show a complication or a deeper truth that makes the result fit. If no result fits, use
`yes-but` with a small complication.

## Conflicts

A conflict has two active sides, for example a fight, a chase, a hunt or an argument. You decide
how much detail a conflict gets.

One question can settle a whole conflict. Leave `target_id` null, ask if the actor wins the
conflict, and keep the answer. Use one question when the opposition is minor, or when the story
needs the conflict to end in one line.

A series of questions plays the key actions. Leave `target_id` null and roll each question. Use a
series when the steps are important but endurance is not.

Luck exchanges run a contest of endurance. Set `target_id`. Use luck exchanges when both sides
can lose ground across several exchanges, and when endurance is the point. A person, a vehicle, a
machine and a cursed object all resist in the same way. Run one exchange each turn. The engine
takes luck from the result. A strong yes costs the opponent more luck. A strong no costs the
acting side more luck. Do not add a second effect for a hit.

A new approach can change `position`. The same approach again keeps `position`. To break away
costs nothing: roll the escape with no opponent. Call `leave` for an opponent who walks away. The
player leaves a place through `next_scene`.

A character at 0 luck loses the conflict. Tell how the conflict ends for that character. The
character can be captured, injured, driven off, cornered, or forced to concede. Defeat does not
mean death. Write a lasting mark now with `change_tags`. This is the only point in a conflict
where a lasting mark is correct. The engine fills the luck of both sides and marks the loser
defeated.

A defeated character takes no new luck exchange. Call `restore_luck` when the defeat is behind
the character and a new contest starts: `restore_luck` clears the mark. Also call `restore_luck`
after a conflict ends in another way and the character has had a rest.

## Twists

The engine gives a twist subject and a twist action after 3 tied rolls outside a conflict. Use
the pair as a complication that arrives this turn. Apply each lasting change with a tool. Keep
the pair. Do not roll the pair again.

## The end of the adventure

When the whole adventure ends, ask the player what their character learned. Then write the change
one time. Call `change_tags` for a new or changed skill, gear or frailty. Call `drive` for a new
nemesis. Do not increase skills or frailties before the adventure ends.

## A member's help

A member rolls only as the actor of their own uncertain action. In all other cases, the help of a
member sets `position` or names the `edge`.
