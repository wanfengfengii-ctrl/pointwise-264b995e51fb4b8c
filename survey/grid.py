from dataclasses import dataclass
from enum import Enum
from typing import Iterator


Point = tuple[int, int]
GridKey = tuple[str, str, str]
ORTHOGONAL = ((-1, 0), (0, -1), (0, 1), (1, 0))
SURROUNDING = tuple(
    (dx, dy)
    for dy in (-1, 0, 1)
    for dx in (-1, 0, 1)
    if dx != 0 or dy != 0
)


def valid_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and value.isprintable()
    )


class CellClass(str, Enum):
    WET = 'wet'
    DRY = 'dry'


@dataclass(frozen=True)
class GridBounds:
    min_x: int
    min_y: int
    max_x: int
    max_y: int

    def __post_init__(self) -> None:
        if any(type(value) is not int for value in self.as_tuple()):
            raise ValueError('grid bounds require integer coordinates')
        if self.min_x > self.max_x or self.min_y > self.max_y:
            raise ValueError('grid bounds are inverted')

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.min_x, self.min_y, self.max_x, self.max_y

    @property
    def width(self) -> int:
        return self.max_x - self.min_x + 1

    @property
    def height(self) -> int:
        return self.max_y - self.min_y + 1

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def perimeter_size(self) -> int:
        interior = max(0, self.width - 2) * max(0, self.height - 2)
        return self.area - interior

    def contains(self, x: int, y: int) -> bool:
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y

    def on_boundary(self, x: int, y: int) -> bool:
        return self.contains(x, y) and (
            x in (self.min_x, self.max_x) or y in (self.min_y, self.max_y)
        )

    def coordinates(self) -> Iterator[Point]:
        for y in range(self.min_y, self.max_y + 1):
            for x in range(self.min_x, self.max_x + 1):
                yield x, y

    def perimeter_coordinates(self) -> Iterator[Point]:
        for y in range(self.min_y, self.max_y + 1):
            if y in (self.min_y, self.max_y):
                for x in range(self.min_x, self.max_x + 1):
                    yield x, y
            else:
                yield self.min_x, y
                if self.min_x != self.max_x:
                    yield self.max_x, y


Cell = tuple[int, int, CellClass]


@dataclass(frozen=True)
class GridRevision:
    round_id: str
    tile_id: str
    revision_id: str
    bounds: GridBounds
    cells: tuple[Cell, ...]

    @property
    def key(self) -> GridKey:
        return self.round_id, self.tile_id, self.revision_id
