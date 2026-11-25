"""Center-side verification of revisit comparisons and global dry topology."""
from dataclasses import dataclass

from issue.comparison import RevisitComparison
from issue.envelope import V1Envelope
from survey.grid import ORTHOGONAL, Point


class ComparisonConflict(ValueError):
    pass


@dataclass(frozen=True)
class TileFacts:
    side: str
    comparison: RevisitComparison
    envelope: V1Envelope
    labels: dict[Point, int]
    anchors: dict[int, Point]
    overlaps: dict[int, dict[int, int]]
    interior_count: int


def build_tile_facts(
    side: str, comparison: RevisitComparison, envelope: V1Envelope
) -> TileFacts:
    if envelope.bounds != comparison.bounds:
        raise ComparisonConflict(f'{side} comparison frame does not match its V1 original')

    labels: dict[Point, int] = {}
    for x, y, old_label, new_label in comparison.boundary:
        label = old_label if side == 'old' else new_label
        if label is not None:
            labels[x, y] = label

    anchors: dict[int, Point] = {}
    for recorded_side, region_id, anchor in comparison.regions:
        if recorded_side == side:
            anchors[region_id] = anchor
    overlaps: dict[int, dict[int, int]] = {}
    for old_id, new_id, count in comparison.overlaps:
        own_id, partner_id = (old_id, new_id) if side == 'old' else (new_id, old_id)
        overlaps.setdefault(own_id, {})[partner_id] = count
    if set(anchors) != set(range(len(anchors))):
        raise ComparisonConflict(f'{side} comparison is missing local dry regions')
    other_side = 'new' if side == 'old' else 'old'
    other_regions = {
        region_id for recorded_side, region_id, _anchor in comparison.regions
        if recorded_side == other_side
    }
    for own_id, partners in overlaps.items():
        if own_id not in anchors or any(other not in other_regions for other in partners):
            raise ComparisonConflict(f'{side} overlap references an unknown local region')
        if any(count <= 0 for count in partners.values()):
            raise ComparisonConflict(f'{side} overlap counts must be positive integers')

    interior_count = _verify_against_v1(side, comparison, envelope, labels, anchors)
    return TileFacts(side, comparison, envelope, labels, anchors, overlaps, interior_count)


def _verify_against_v1(
    side: str,
    comparison: RevisitComparison,
    envelope: V1Envelope,
    labels: dict[Point, int],
    anchors: dict[int, Point],
) -> int:
    body = envelope.body
    required = {'wet_regions', 'enclosed_dry_regions', 'boundary', 'links'}
    if not isinstance(body, dict) or body.keys() != required:
        raise ComparisonConflict(f'{side} V1 original lacks the required topology body')
    bounds = envelope.bounds
    cells, links = body['boundary'], body['links']
    if (
        not isinstance(cells, list)
        or not isinstance(links, list)
        or len(cells) != bounds.perimeter_size
        or len(links) != len(cells)
    ):
        raise ComparisonConflict(f'{side} V1 original lacks a complete labelled perimeter')

    v1_dry: dict[Point, int] = {}
    wet_numbers: set[int] = set()
    for point, cell, link in zip(bounds.perimeter_coordinates(), cells, links, strict=True):
        if (
            not isinstance(cell, list) or len(cell) != 3
            or type(cell[0]) is not int or type(cell[1]) is not int
            or (cell[0], cell[1]) != point or cell[2] not in ('wet', 'dry')
            or type(link) is not int or link < 0
        ):
            raise ComparisonConflict(f'{side} V1 original has an invalid perimeter row')
        if cell[2] == 'wet':
            wet_numbers.add(link)
        else:
            v1_dry[point] = link

    dry_numbers = set(v1_dry.values())
    if dry_numbers != set(range(len(dry_numbers))) or wet_numbers != set(range(len(wet_numbers))):
        raise ComparisonConflict(f'{side} V1 component labels are not contiguous')

    # The comparison's dry boundary cells must be exactly the V1 dry perimeter cells,
    # and both sources must induce the same connectivity partition over them.
    if set(labels) != set(v1_dry):
        raise ComparisonConflict(f'{side} dry boundary cells conflict with the V1 perimeter')
    for point in v1_dry:
        x, y = point
        for dx, dy in ORTHOGONAL:
            neighbor = x + dx, y + dy
            if neighbor in v1_dry:
                same_v1 = v1_dry[point] == v1_dry[neighbor]
                same_comparison = labels[point] == labels[neighbor]
                if same_v1 != same_comparison:
                    raise ComparisonConflict(
                        f'{side} dry boundary partition conflicts with the V1 component labels'
                    )

    enclosed = body['enclosed_dry_regions']
    if type(enclosed) is not int or enclosed < 0:
        raise ComparisonConflict(f'{side} V1 original has an invalid enclosed dry count')
    edge_regions = set(labels.values())
    interior_count = len(anchors) - len(edge_regions)
    if interior_count != enclosed:
        raise ComparisonConflict(f'{side} enclosed dry region count does not match V1')
    return interior_count


class _UnionFind:
    def __init__(self, nodes):
        self.parent = {node: node for node in nodes}
        self.size = dict.fromkeys(nodes, 1)

    def root(self, node):
        while self.parent[node] != node:
            parent = self.parent[node]
            self.parent[node] = self.parent[parent]
            node = self.parent[node]
        return node

    def join(self, left, right):
        left_root = self.root(left)
        right_root = self.root(right)
        if left_root == right_root:
            return
        if self.size[left_root] < self.size[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        self.size[left_root] += self.size[right_root]


@dataclass(frozen=True)
class GlobalRegions:
    # local region node (receipt_id, local region id) -> enclosed global anchor
    global_of: dict[tuple[int, int], Point]


def compute_global(tiles: list[tuple[int, TileFacts]]) -> GlobalRegions:
    nodes = set()
    anchors: dict[tuple[int, int], Point] = {}
    boundary_labels: dict[Point, tuple[int, int]] = {}
    for receipt_id, facts in tiles:
        for region_id, anchor in facts.anchors.items():
            node = (receipt_id, region_id)
            nodes.add(node)
            anchors[node] = anchor
        for point, region_id in facts.labels.items():
            boundary_labels[point] = (receipt_id, region_id)

    union = _UnionFind(nodes)
    exterior: set[tuple[int, int]] = set()
    for point, node in boundary_labels.items():
        receipt_id, _region_id = node
        x, y = point
        for dx, dy in ORTHOGONAL:
            target = x + dx, y + dy
            neighbor = boundary_labels.get(target)
            if neighbor is not None:
                if neighbor[0] != receipt_id:
                    union.join(node, neighbor)
            elif _outside_coverage(target, tiles):
                exterior.add(node)

    grouped: dict[object, list[tuple[int, int]]] = {}
    for node in nodes:
        grouped.setdefault(union.root(node), []).append(node)
    exterior_roots = {union.root(node) for node in exterior}

    global_of: dict[tuple[int, int], Point] = {}
    for root, members in grouped.items():
        if root in exterior_roots:
            continue
        anchor = min(anchors[node] for node in members)
        for node in members:
            global_of[node] = anchor
    return GlobalRegions(global_of)


def _outside_coverage(point: Point, tiles: list[tuple[int, TileFacts]]) -> bool:
    x, y = point
    for _receipt_id, facts in tiles:
        if facts.envelope.bounds.contains(x, y):
            return False
    return True
