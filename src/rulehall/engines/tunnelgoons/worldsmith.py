from rulehall.engines.hiring import HIRED
from rulehall.engines.tunnelgoons.sheet import ABILITY_POINTS

WORLDSMITH_GUIDANCE = (
    "TUNNEL GOONS AUTHORING\n"
    "Every npc needs `hp`. The `hp` value is the Health of the npc and its Difficulty "
    "Score. Set `hp` to 8 for easy, to 10 for moderate, or to 12 for hard. Use the people "
    "and the monsters of a pack: file one as an npc under a new id. Give a monster the "
    "`hp` that the pack prints."
)
HIRE_GUIDANCE = (
    "TUNNEL GOONS HIRING\n"
    f"Divide {ABILITY_POINTS} points across the three abilities. Brute is hitting things "
    "and acts of strength. Skulker is quiet movement, aiming and balance. Erudite is "
    "reading, perception and speech. Give the abilities only."
)
HIRING = (
    f"{HIRED}Write the three abilities of this character from ENGINE GUIDANCE. Make the "
    "abilities fit the character and the work."
)
