"""Revisit comparison envelopes issued by a source station.

A comparison binds two ordered V1 issues from different survey rounds that share
the same rectangular bounds.  It carries only the facts needed by the center:
local dry-region anchors, dry boundary ownership and positive overlaps.  The
station keeps the full classified grid; it is never exported here.
"""
import base64
import hashlib
import json
from dataclasses import dataclass

from issue.envelope import V1Envelope, decode_v1
from quality.dry_regions import dry_components
from survey.grid import GridBounds, GridRevision, Point, valid_identifier


class InvalidComparison(ValueError):
    pass


@dataclass(frozen=True)
class ComparisonSide:
    issue_id: str
    round_id: str
    tile_id: str
    revision_id: str
    original: bytes


@dataclass(frozen=True)
class RevisitComparison:
    comparison_id: str
    bounds: GridBounds
    old: ComparisonSide
    new: ComparisonSide
    # (side, region_id, anchor) for every local dry component on each side
    regions: tuple[tuple[str, int, Point], ...]
    # (x, y, old_label or None, new_label or None)
    boundary: tuple[tuple[int, int, int | None, int | None], ...]
    # (old_region_id, new_region_id, positive overlap count)
    overlaps: tuple[tuple[int, int, int], ...]


COMPARISON_KIND = 'revisit-comparison'
PAYLOAD_FIELDS = {'version', 'kind', 'comparison_id', 'bounds', 'sides', 'regions', 'boundary', 'overlaps'}
SIDES = ('old', 'new')


def _json_text(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise InvalidComparison(f'duplicate JSON key {key!r}')
        obj[key] = value
    return obj


def _reject_constant(value: str) -> None:
    raise InvalidComparison(f'non-finite JSON constant {value!r}')


def _parse(value: str) -> object:
    return json.loads(
        value, object_pairs_hook=_object_without_duplicate_keys, parse_constant=_reject_constant
    )


def _side_from_envelope(envelope: V1Envelope, original: bytes) -> dict:
    return {
        'issue_id': envelope.issue_id,
        'round_id': envelope.round_id,
        'tile_id': envelope.tile_id,
        'revision_id': envelope.revision_id,
        'original': base64.b64encode(original).decode('ascii'),
    }


def _dry_edge(grid: GridRevision) -> dict[Point, int]:
    edge: dict[Point, int] = {}
    for region_id, (component, _reaches) in enumerate(dry_components(grid)):
        for point in component:
            if grid.bounds.on_boundary(*point):
                edge[point] = region_id
    return edge


def build_comparison(
    comparison_id: str,
    old_grid: GridRevision,
    new_grid: GridRevision,
    old_original: bytes,
    new_original: bytes,
) -> RevisitComparison:
    if old_grid.bounds != new_grid.bounds:
        raise InvalidComparison('comparison requires identical rectangular bounds')
    old_envelope = decode_v1(old_original)
    new_envelope = decode_v1(new_original)
    if old_envelope.round_id == new_envelope.round_id:
        raise InvalidComparison('comparison sides must come from different survey rounds')
    bounds = old_grid.bounds

    old_components = dry_components(old_grid)
    new_components = dry_components(new_grid)
    old_edge = _dry_edge(old_grid)
    new_edge = _dry_edge(new_grid)

    regions: list[tuple[str, int, Point]] = []
    for side, components in (('old', old_components), ('new', new_components)):
        for region_id, (component, _reaches) in enumerate(components):
            regions.append((side, region_id, min(component)))

    boundary = []
    for point in bounds.perimeter_coordinates():
        old_label = old_edge.get(point)
        new_label = new_edge.get(point)
        if old_label is None and new_label is None:
            continue
        boundary.append((point[0], point[1], old_label, new_label))

    overlaps = []
    for old_id, (old_component, _) in enumerate(old_components):
        for new_id, (new_component, _) in enumerate(new_components):
            shared = len(old_component & new_component)
            if shared > 0:
                overlaps.append((old_id, new_id, shared))

    return RevisitComparison(
        comparison_id,
        bounds,
        ComparisonSide(
            old_envelope.issue_id, old_envelope.round_id, old_envelope.tile_id,
            old_envelope.revision_id, old_original,
        ),
        ComparisonSide(
            new_envelope.issue_id, new_envelope.round_id, new_envelope.tile_id,
            new_envelope.revision_id, new_original,
        ),
        tuple(regions),
        tuple(boundary),
        tuple(overlaps),
    )


def _encode_side(side: ComparisonSide) -> dict:
    return {
        'issue_id': side.issue_id,
        'round_id': side.round_id,
        'tile_id': side.tile_id,
        'revision_id': side.revision_id,
        'original': base64.b64encode(side.original).decode('ascii'),
    }


def encode_comparison(comparison: RevisitComparison) -> bytes:
    if not valid_identifier(comparison.comparison_id):
        raise InvalidComparison('invalid comparison issuance id')
    if not isinstance(comparison.bounds, GridBounds):
        raise InvalidComparison('invalid comparison bounds')
    payload = {
        'version': 1,
        'kind': COMPARISON_KIND,
        'comparison_id': comparison.comparison_id,
        'bounds': comparison.bounds.as_tuple(),
        'sides': {'old': _encode_side(comparison.old), 'new': _encode_side(comparison.new)},
        'regions': [
            {'side': side, 'region': region_id, 'anchor': list(anchor)}
            for side, region_id, anchor in comparison.regions
        ],
        'boundary': [
            {'x': x, 'y': y, 'old': old_label, 'new': new_label}
            for x, y, old_label, new_label in comparison.boundary
        ],
        'overlaps': [list(entry) for entry in comparison.overlaps],
    }
    try:
        text = _json_text(payload)
    except (TypeError, ValueError, RecursionError) as exc:
        raise InvalidComparison('comparison payload is not serializable as JSON') from exc
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    return _json_text({'payload': text, 'digest': digest}).encode('utf-8')


def _decode_side(raw: object) -> ComparisonSide:
    if not isinstance(raw, dict) or raw.keys() != {'issue_id', 'round_id', 'tile_id', 'revision_id', 'original'}:
        raise InvalidComparison('invalid comparison side record')
    identifiers = (raw['issue_id'], raw['round_id'], raw['tile_id'], raw['revision_id'])
    if not all(valid_identifier(value) for value in identifiers):
        raise InvalidComparison('invalid comparison side identity')
    if not isinstance(raw['original'], str):
        raise InvalidComparison('comparison side original must be base64 text')
    try:
        original = base64.b64decode(raw['original'], validate=True)
    except (ValueError, TypeError) as exc:
        raise InvalidComparison('comparison side original is not valid base64') from exc
    envelope = decode_v1(original)
    if (
        envelope.issue_id != raw['issue_id']
        or envelope.round_id != raw['round_id']
        or envelope.tile_id != raw['tile_id']
        or envelope.revision_id != raw['revision_id']
    ):
        raise InvalidComparison('comparison side identity does not match its V1 original')
    return ComparisonSide(*identifiers, original)


def decode_comparison(original: bytes) -> RevisitComparison:
    if type(original) is not bytes:
        raise InvalidComparison('comparison input must be original bytes')
    try:
        wire = _parse(original.decode('utf-8'))
        if not isinstance(wire, dict) or wire.keys() != {'payload', 'digest'}:
            raise InvalidComparison('invalid comparison wrapper')
        text = wire['payload']
        if not isinstance(text, str):
            raise InvalidComparison('invalid comparison payload text')
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        if wire['digest'] != digest:
            raise InvalidComparison('comparison payload digest mismatch')
        data = _parse(text)
        if not isinstance(data, dict) or data.keys() != PAYLOAD_FIELDS:
            raise InvalidComparison('invalid comparison payload fields')
        if type(data['version']) is not int or data['version'] != 1 or data['kind'] != COMPARISON_KIND:
            raise InvalidComparison('unsupported comparison version or kind')
        if not valid_identifier(data['comparison_id']):
            raise InvalidComparison('invalid comparison issuance id')
        coordinates = data['bounds']
        if not isinstance(coordinates, list) or len(coordinates) != 4:
            raise InvalidComparison('invalid comparison bounds')
        bounds = GridBounds(*coordinates)

        sides_raw = data['sides']
        if not isinstance(sides_raw, dict) or set(sides_raw) != set(SIDES):
            raise InvalidComparison('comparison must bind ordered old and new sides')
        sides = {name: _decode_side(sides_raw[name]) for name in SIDES}
        if sides['old'].round_id == sides['new'].round_id:
            raise InvalidComparison('comparison sides must come from different survey rounds')
        for side in sides.values():
            if decode_v1(side.original).bounds != bounds:
                raise InvalidComparison('comparison side bounds do not match the shared frame')

        regions_raw = data['regions']
        if not isinstance(regions_raw, list):
            raise InvalidComparison('invalid comparison region records')
        seen: dict[str, set[int]] = {'old': set(), 'new': set()}
        regions = []
        for record in regions_raw:
            if not isinstance(record, dict) or record.keys() != {'side', 'region', 'anchor'}:
                raise InvalidComparison('invalid comparison region record')
            side = record['side']
            region_id = record['region']
            anchor = record['anchor']
            if side not in seen or type(region_id) is not int or region_id < 0:
                raise InvalidComparison('invalid comparison region identity')
            if region_id in seen[side]:
                raise InvalidComparison('duplicate comparison region id')
            seen[side].add(region_id)
            if (
                not isinstance(anchor, list) or len(anchor) != 2
                or any(type(value) is not int for value in anchor)
                or not bounds.contains(*anchor)
            ):
                raise InvalidComparison('comparison region anchor must be a cell inside the frame')
            regions.append((side, region_id, (anchor[0], anchor[1])))
        for side, ids in seen.items():
            if ids != set(range(len(ids))):
                raise InvalidComparison(f'{side} comparison region ids must be contiguous from zero')

        boundary_raw = data['boundary']
        if not isinstance(boundary_raw, list):
            raise InvalidComparison('invalid comparison boundary records')
        boundary_points = set()
        boundary = []
        for record in boundary_raw:
            if not isinstance(record, dict) or record.keys() != {'x', 'y', 'old', 'new'}:
                raise InvalidComparison('invalid comparison boundary record')
            x, y = record['x'], record['y']
            if type(x) is not int or type(y) is not int or not bounds.contains(x, y) or not bounds.on_boundary(x, y):
                raise InvalidComparison('comparison boundary cell must lie on the frame perimeter')
            if (x, y) in boundary_points:
                raise InvalidComparison('duplicate comparison boundary cell')
            boundary_points.add((x, y))
            labels = {}
            for side in SIDES:
                label = record[side]
                if label is not None and (type(label) is not int or label not in seen[side]):
                    raise InvalidComparison(f'comparison boundary labels an unknown {side} region')
                labels[side] = label
            if labels['old'] is None and labels['new'] is None:
                raise InvalidComparison('comparison boundary cell is dry on neither side')
            boundary.append((x, y, labels['old'], labels['new']))

        overlaps_raw = data['overlaps']
        if not isinstance(overlaps_raw, list):
            raise InvalidComparison('invalid comparison overlap records')
        overlap_keys = set()
        overlaps = []
        for entry in overlaps_raw:
            if not isinstance(entry, list) or len(entry) != 3 or any(type(value) is not int for value in entry):
                raise InvalidComparison('invalid comparison overlap record')
            old_id, new_id, count = entry
            if old_id not in seen['old'] or new_id not in seen['new'] or count <= 0:
                raise InvalidComparison('comparison overlap must reference real regions with a positive count')
            if (old_id, new_id) in overlap_keys:
                raise InvalidComparison('duplicate comparison overlap pair')
            overlap_keys.add((old_id, new_id))
            overlaps.append((old_id, new_id, count))

        return RevisitComparison(
            data['comparison_id'], bounds, sides['old'], sides['new'],
            tuple(regions), tuple(boundary), tuple(overlaps),
        )
    except InvalidComparison:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise InvalidComparison('malformed comparison data') from exc
