from dataclasses import dataclass

from survey.grid import CellClass, GridRevision


@dataclass(frozen=True)
class BoundaryCell:
    x: int
    y: int
    classification: CellClass


def boundary_cells(grid: GridRevision) -> tuple[BoundaryCell, ...]:
    return tuple(
        BoundaryCell(x, y, classification)
        for x, y, classification in grid.cells
        if grid.bounds.on_boundary(x, y)
    )
