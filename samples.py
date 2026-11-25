from collections.abc import Iterable

from survey.bootstrap import SeedGrid
from survey.grid import GridBounds, Point


ROUND = 'QC-17'
SHIFT = 'night-1'
LEFT = GridBounds(0, 0, 4, 6)
RIGHT = GridBounds(5, 0, 9, 6)
WHOLE = GridBounds(0, 0, 9, 6)
LEFT_ARMS = frozenset((x, y) for x in range(1, 5) for y in (1, 5))
LEFT_WET = LEFT_ARMS | {(1, y) for y in range(1, 6)} | {(3, 3)}
RIGHT_WET = frozenset((x, y) for x in range(5, 9) for y in (1, 5)) | {
    (8, y) for y in range(1, 6)
}


def seed(
    tile_id: str,
    revision_id: str,
    bounds: GridBounds,
    wet: Iterable[Point],
    round_id: str = ROUND,
) -> SeedGrid:
    wet = frozenset(wet)
    cells = tuple((x, y, 'wet' if (x, y) in wet else 'dry') for x, y in bounds.coordinates())
    return round_id, tile_id, revision_id, bounds, cells


WEST_INITIAL = seed('west', 'a', LEFT, LEFT_WET)
WEST_CORRECTION = seed('west', 'b', LEFT, LEFT_ARMS)
EAST_INITIAL = seed('east', 'a', RIGHT, RIGHT_WET)
