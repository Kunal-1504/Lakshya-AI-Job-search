"""Public employer feeds verified on 7 October 2026; custom lists replace starters."""

from lakshya.config import Settings

STARTER_BOARDS = {
    "greenhouse": ["jumio", "gleanwork"],
    "lever": ["netomi"],
    "ashby": ["ema", "emergence"],
    "recruitee": ["metyisag"],
}


def employer_boards(settings: Settings, source: str) -> list[str]:
    return settings.boards.get(source) or STARTER_BOARDS.get(source, [])
