from collections.abc import Iterable

from survey.grid import CellClass, GridRevision, Point, SURROUNDING


def connected_cells(
    points: Iterable[Point], offsets: tuple[Point, ...]
) -> tuple[frozenset[Point], ...]:
    unseen = set(points)
    groups = []
    for first in sorted(unseen, key=lambda point: (point[1], point[0])):
        if first not in unseen:
            continue
        unseen.remove(first)
        pending = [first]
        component = {first}
        while pending:
            x, y = pending.pop()
            for dx, dy in offsets:
                neighbor = x + dx, y + dy
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    component.add(neighbor)
                    pending.append(neighbor)
        groups.append(frozenset(component))
    return tuple(groups)


def wet_components(grid: GridRevision) -> tuple[frozenset[Point], ...]:
    points = ((x, y) for x, y, kind in grid.cells if kind == CellClass.WET)
    return connected_cells(points, SURROUNDING)


def count_wet_regions(grid: GridRevision) -> int:
    return len(wet_components(grid))
