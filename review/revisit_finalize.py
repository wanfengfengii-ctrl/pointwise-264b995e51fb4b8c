import sqlite3
from collections.abc import Iterable

from issue.comparison import InvalidComparison, decode_comparison
from issue.envelope import decode_v1
from receipt.store import ReceiptStore
from review.finalize import SignRejected
from review.report_store import ReportStore
from review.revisit_store import RevisitStore, decode_origins, encode_origins
from review.revisit_topology import ComparisonConflict, build_tile_facts, compute_global
from survey.grid import Point


def _load_report(db, report_id: int):
    if type(report_id) is not int or not 1 <= report_id < 2**63:
        raise SignRejected(f'invalid report id {report_id!r}')
    pair = ReportStore(db).get_pair(report_id)
    if pair is None:
        raise SignRejected(f'unknown signed report {report_id!r}')
    return pair[0]


def _receipt_map(db, report) -> dict[str, object]:
    store = ReceiptStore(db)
    receipts = {}
    for origin in report.origins:
        received = store.get(origin.receipt_id)
        if received is None:
            raise SignRejected(f'report {report.report_id!r} references missing receipt {origin.receipt_id}')
        receipts[origin.issue_id] = received
    return receipts


def _relation(edges_by_old: dict, edges_by_new: dict, old_anchor: Point, new_anchor: Point) -> tuple[str, ...]:
    split = len(edges_by_old[old_anchor]) > 1
    merge = len(edges_by_new[new_anchor]) > 1
    if split and merge:
        return ('split', 'merge')
    if split:
        return ('split',)
    if merge:
        return ('merge',)
    return ('continue',)


def sign_revisit(
    db,
    old_report_id: int,
    new_report_id: int,
    originals: Iterable[bytes],
) -> tuple[int, dict, dict]:
    try:
        RevisitStore(db).ensure_schema()
        old_report = _load_report(db, old_report_id)
        new_report = _load_report(db, new_report_id)
        if old_report.round_id == new_report.round_id:
            raise SignRejected('revisit requires reports from two different survey rounds')

        old_receipts = _receipt_map(db, old_report)
        new_receipts = _receipt_map(db, new_report)

        try:
            incoming = list(originals)
        except TypeError as exc:
            raise SignRejected('comparison originals must be an iterable of bytes') from exc
        if any(type(item) is not bytes for item in incoming):
            raise SignRejected('comparison originals must be bytes')

        # Empty selection is allowed only when both rounds selected nothing.
        if not incoming:
            if old_receipts or new_receipts:
                raise SignRejected('missing comparisons for the selected tiles')
            empty_checklist = {
                'old_regions': [], 'new_regions': [],
                'exited': [], 'added': [], 'overlaps': [],
            }
            return _commit(db, old_report_id, new_report_id, empty_checklist, [])

        if len(incoming) != len(set(incoming)):
            raise SignRejected('duplicate comparison originals')

        # Bounds pairing: actual selections must match frame by frame.
        old_by_bounds = {}
        new_by_bounds = {}
        for issue_id, received in old_receipts.items():
            bounds = decode_v1(received.original).bounds
            if bounds in old_by_bounds:
                raise SignRejected('old report selections do not form disjoint frames')
            old_by_bounds[bounds] = (issue_id, received)
        for issue_id, received in new_receipts.items():
            bounds = decode_v1(received.original).bounds
            if bounds in new_by_bounds:
                raise SignRejected('new report selections do not form disjoint frames')
            new_by_bounds[bounds] = (issue_id, received)
        if set(old_by_bounds) != set(new_by_bounds):
            raise SignRejected('tile frames of the two reports do not pair up')
        if len(incoming) != len(old_by_bounds):
            raise SignRejected('each frame pair requires exactly one comparison')

        parsed = []
        seen_frames = set()
        for original in incoming:
            try:
                comparison = decode_comparison(original)
            except InvalidComparison as exc:
                raise SignRejected(f'bad comparison original: {exc}') from exc
            frame = comparison.bounds
            if frame in seen_frames:
                raise SignRejected('duplicate frame pair among comparisons')
            seen_frames.add(frame)
            if frame not in old_by_bounds:
                raise SignRejected('comparison frame is not part of the signed selections')

            old_issue_id, old_received = old_by_bounds[frame]
            new_issue_id, new_received = new_by_bounds[frame]
            if comparison.old.original != old_received.original:
                raise SignRejected('old side comparison is not bound to the report\'s actual tile')
            if comparison.new.original != new_received.original:
                raise SignRejected('new side comparison is not bound to the report\'s actual tile')
            if (
                comparison.old.issue_id != old_issue_id
                or comparison.new.issue_id != new_issue_id
            ):
                raise SignRejected('comparison is bound to the wrong issues')

            old_envelope = decode_v1(old_received.original)
            new_envelope = decode_v1(new_received.original)
            old_facts = build_tile_facts('old', comparison, old_envelope)
            new_facts = build_tile_facts('new', comparison, new_envelope)
            parsed.append((frame, old_received.receipt_id, new_received.receipt_id,
                           comparison, old_facts, new_facts))

        old_tiles = [(old_receipt_id, old_facts)
                     for _frame, old_receipt_id, _new_id, _cmp, old_facts, _new_facts in parsed]
        new_tiles = [(new_receipt_id, new_facts)
                     for _frame, _old_id, new_receipt_id, _cmp, _old_facts, new_facts in parsed]
        old_global = compute_global(old_tiles)
        new_global = compute_global(new_tiles)

        old_enclosed = sorted(set(old_global.global_of.values()))
        new_enclosed = sorted(set(new_global.global_of.values()))

        # Sum positive enclosed-to-enclosed overlap cells per global region pair.
        totals: dict[tuple[Point, Point], int] = {}
        for _frame, old_receipt_id, new_receipt_id, comparison, _old_facts, _new_facts in parsed:
            for old_local, new_local, count in comparison.overlaps:
                old_node = (old_receipt_id, old_local)
                new_node = (new_receipt_id, new_local)
                if old_node not in old_global.global_of or new_node not in new_global.global_of:
                    continue
                key = (old_global.global_of[old_node], new_global.global_of[new_node])
                totals[key] = totals.get(key, 0) + count

        edges_by_old: dict[Point, list] = {}
        edges_by_new: dict[Point, list] = {}
        for (old_anchor, new_anchor) in totals:
            edges_by_old.setdefault(old_anchor, []).append(new_anchor)
            edges_by_new.setdefault(new_anchor, []).append(old_anchor)

        edges = []
        for (old_anchor, new_anchor), count in totals.items():
            relation = _relation(edges_by_old, edges_by_new, old_anchor, new_anchor)
            edges.append((old_anchor, new_anchor, count, relation))
        edges.sort(key=lambda edge: (edge[0], edge[1]))

        old_with_edges = set(edges_by_old)
        new_with_edges = set(edges_by_new)
        checklist = {
            'old_regions': [point for point in old_enclosed],
            'new_regions': [point for point in new_enclosed],
            'exited': [point for point in old_enclosed if point not in old_with_edges],
            'added': [point for point in new_enclosed if point not in new_with_edges],
            'overlaps': edges,
        }

        comparison_origins = sorted(
            (
                comparison.old.issue_id,
                comparison.new.issue_id,
                comparison.comparison_id,
                original,
            )
            for original, (_frame, _o, _n, comparison, _of, _nf) in zip(incoming, parsed, strict=True)
        )
        return _commit(db, old_report_id, new_report_id, checklist, comparison_origins)
    except SignRejected:
        raise
    except (
        InvalidComparison, ComparisonConflict, ValueError, TypeError, sqlite3.Error,
    ) as exc:
        raise SignRejected(str(exc)) from exc


def _commit(
    db,
    old_report_id: int,
    new_report_id: int,
    checklist,
    comparison_origins,
) -> tuple[int, dict, dict]:
    origins = encode_origins(old_report_id, new_report_id, comparison_origins)
    record = {
        'old_report_id': old_report_id,
        'new_report_id': new_report_id,
        'checklist': _jsonable(checklist),
        'origins': origins,
    }
    revisit_id = RevisitStore(db).commit(record)
    return revisit_id, _tupleize(checklist), {
        'old_report_id': old_report_id,
        'new_report_id': new_report_id,
        'comparisons': decode_origins(origins)['comparisons'],
    }


def _jsonable(value):
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _tupleize(checklist: dict) -> dict:
    result = {}
    for key, value in checklist.items():
        if key == 'overlaps':
            result[key] = tuple(
                (tuple(edge[0]), tuple(edge[1]), edge[2], tuple(edge[3])) for edge in value
            )
        else:
            result[key] = tuple(tuple(point) for point in value)
    return result
