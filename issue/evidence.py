from issue.boundary import boundary_cells
from quality.dry_regions import dry_components
from quality.wet_regions import wet_components
from survey.grid import CellClass, GridRevision, Point


def build_evidence(grid: GridRevision) -> dict:
    wet = wet_components(grid)
    dry = dry_components(grid)
    edge = boundary_cells(grid)

    groups_at: dict[Point, int] = {}
    for groups in (wet, tuple(group for group, _ in dry)):
        for group_index, group in enumerate(groups):
            for x, y in group:
                if grid.bounds.on_boundary(x, y):
                    groups_at[x, y] = group_index

    labels: dict[CellClass, dict[int, int]] = {kind: {} for kind in CellClass}
    links = []
    for cell in edge:
        labels_for_class = labels[cell.classification]
        links.append(labels_for_class.setdefault(groups_at[cell.x, cell.y], len(labels_for_class)))

    return {
        'wet_regions': len(wet),
        'enclosed_dry_regions': sum(not reaches_edge for _, reaches_edge in dry),
        'boundary': [[cell.x, cell.y, cell.classification.value] for cell in edge],
        'links': links,
    }
