from dataclasses import dataclass

from receipt.selection import ShiftSelection
from receipt.store import ReceivedTile
from review.coverage import SelectedCoverage
from survey.grid import ORTHOGONAL, SURROUNDING, Point


class InsufficientEvidence(ValueError):
    pass


@dataclass(frozen=True)
class TopologyCounts:
    wet_regions: int
    enclosed_dry_regions: int


Component = tuple[int, str, int]
OFFSETS = {'wet': SURROUNDING, 'dry': ORTHOGONAL}
BODY_FIELDS = {'wet_regions', 'enclosed_dry_regions', 'boundary', 'links'}


class _Components:
    def __init__(self, nodes: set[Component]):
        self.parent = {node: node for node in nodes}
        self.size = dict.fromkeys(nodes, 1)

    def root(self, node: Component) -> Component:
        while self.parent[node] != node:
            parent = self.parent[node]
            self.parent[node] = self.parent[parent]
            node = self.parent[node]
        return node

    def join(self, left: Component, right: Component) -> None:
        left_root = self.root(left)
        right_root = self.root(right)
        if left_root == right_root:
            return
        if self.size[left_root] < self.size[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        self.size[left_root] += self.size[right_root]


def _read_evidence(receipt: ReceivedTile) -> tuple[dict[Point, Component], int, int]:
    envelope = receipt.envelope
    bounds = envelope.bounds
    body = envelope.body
    prefix = f'receipt {receipt.receipt_id}'
    if body.keys() != BODY_FIELDS:
        raise InsufficientEvidence(f'{prefix} lacks the required topology fields')
    wet_count = body['wet_regions']
    dry_count = body['enclosed_dry_regions']
    if any(type(value) is not int or value < 0 for value in (wet_count, dry_count)):
        raise InsufficientEvidence(f'{prefix} has invalid local counts')
    cells, links = body['boundary'], body['links']
    if (
        not isinstance(cells, list)
        or not isinstance(links, list)
        or len(cells) != bounds.perimeter_size
        or len(links) != len(cells)
    ):
        raise InsufficientEvidence(f'{prefix} lacks a complete labelled perimeter')

    edge = {}
    labels = {'wet': set(), 'dry': set()}
    for point, cell, label in zip(bounds.perimeter_coordinates(), cells, links, strict=True):
        if (
            not isinstance(cell, list)
            or len(cell) != 3
            or type(cell[0]) is not int
            or type(cell[1]) is not int
            or (cell[0], cell[1]) != point
            or type(cell[2]) is not str
            or cell[2] not in OFFSETS
        ):
            raise InsufficientEvidence(f'{prefix} has an invalid perimeter cell')
        kind = cell[2]
        known = labels[kind]
        if type(label) is not int or label < 0 or label > len(known):
            raise InsufficientEvidence(f'{prefix} has an invalid component label')
        known.add(label)
        edge[point] = (receipt.receipt_id, kind, label)

    interior_wet = wet_count - len(labels['wet'])
    if interior_wet < 0 or interior_wet + dry_count > bounds.area - len(cells):
        raise InsufficientEvidence(f'{prefix} has inconsistent local counts')
    for (x, y), component in edge.items():
        kind = component[1]
        for dx, dy in OFFSETS[kind]:
            neighbor = edge.get((x + dx, y + dy))
            if neighbor is not None and neighbor[1] == kind and neighbor != component:
                raise InsufficientEvidence(f'{prefix} splits adjacent cells into separate components')
    return edge, interior_wet, dry_count


def count_selected_regions(selection: ShiftSelection, coverage: SelectedCoverage) -> TopologyCounts:
    perimeter = {}
    unexposed_wet = 0
    enclosed_within_tiles = 0
    for receipt in selection.receipts:
        edge, interior_wet, interior_dry = _read_evidence(receipt)
        perimeter.update(edge)
        unexposed_wet += interior_wet
        enclosed_within_tiles += interior_dry

    nodes = set(perimeter.values())
    components = _Components(nodes)
    exterior = set()
    for (x, y), component in perimeter.items():
        receipt_id, kind, _ = component
        for dx, dy in OFFSETS[kind]:
            target = x + dx, y + dy
            neighbor = perimeter.get(target)
            if neighbor is not None:
                if neighbor[0] != receipt_id and neighbor[1] == kind:
                    components.join(component, neighbor)
            elif kind == 'dry' and coverage.tile_at(*target) is None:
                exterior.add(component)

    wet_roots = {components.root(node) for node in nodes if node[1] == 'wet'}
    dry_roots = {components.root(node) for node in nodes if node[1] == 'dry'}
    exterior_roots = {components.root(node) for node in exterior}
    return TopologyCounts(
        unexposed_wet + len(wet_roots),
        enclosed_within_tiles + len(dry_roots - exterior_roots),
    )
