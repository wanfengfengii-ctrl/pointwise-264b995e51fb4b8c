from quality.wet_regions import connected_cells
from survey.grid import CellClass, GridRevision, ORTHOGONAL, Point


def dry_components(grid: GridRevision) -> tuple[tuple[frozenset[Point], bool], ...]:
    points = ((x, y) for x, y, kind in grid.cells if kind == CellClass.DRY)
    return tuple(
        (component, any(grid.bounds.on_boundary(x, y) for x, y in component))
        for component in connected_cells(points, ORTHOGONAL)
    )


def count_enclosed_dry_regions(grid: GridRevision) -> int:
    return sum(not reaches_edge for _, reaches_edge in dry_components(grid))
