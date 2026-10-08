from rulehall.core.prompt import Sections
from rulehall.engines.packs import Pack
from rulehall.engines.pokemon.dex import avatars


class ChampionsPack(Pack):
    def sections(self, *, opening: bool) -> Sections:
        return (
            *super().sections(opening=opening),
            ("TRAINER LOOKS", avatars().npc_group_lines()),
        )
