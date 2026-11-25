import sqlite3
from itertools import product
from pathlib import Path
from tempfile import TemporaryDirectory

from issue.envelope import decode_v1
from issue.publish import publish
from receipt.accept import accept
from review.archive import read
from review.finalize import SignRejected, sign
from samples import (
    EAST_INITIAL, LEFT, LEFT_ARMS, LEFT_WET, RIGHT, RIGHT_WET, ROUND, SHIFT,
    WEST_CORRECTION, WEST_INITIAL, WHOLE, seed,
)
from survey.grid import GridBounds
from tests.support import (
    ProjectTest, fail_at_commit, independent_piece, reference_counts, report_counts,
    resume_commits,
)


class HandoffTest(ProjectTest):
    def test_closed_after_join(self):
        west = self.station('west', [WEST_INITIAL])
        east = self.station('east', [EAST_INITIAL])
        center = self.center()
        left = self.publish_to_center(west, center, 'west', 'a')
        right = self.publish_to_center(east, center, 'east', 'a')
        west.close()
        east.close()

        expected = reference_counts(WHOLE.coordinates(), LEFT_WET | RIGHT_WET)
        self.assertEqual(expected, (2, 1))
        report, receipt = sign(center, ROUND, SHIFT, [right.receipt_id, left.receipt_id])
        self.assertEqual(report_counts(report), expected)
        self.assert_sources(report, [
            (left.receipt_id, 'west:1', ROUND, 'west', 'a'),
            (right.receipt_id, 'east:1', ROUND, 'east', 'a'),
        ])
        self.assertEqual(receipt.origins, report.origins)
        self.assertEqual(read(center, report.report_id), (report, receipt))

        single, _ = sign(center, ROUND, SHIFT, [left.receipt_id])
        self.assertEqual(report_counts(single), (2, 0))
        self.assertEqual(report_counts(single), reference_counts(LEFT.coordinates(), LEFT_WET))
        self.assertEqual(single.origins, report.origins[:1])
        self.assert_pair_count(center, 2)

    def test_same_summary_control(self):
        west = self.station('west', [WEST_INITIAL, WEST_CORRECTION])
        center = self.center()
        issue_a, original_a = publish(west, round_id=ROUND, tile_id='west', revision_id='a')
        issue_b, original_b = publish(west, round_id=ROUND, tile_id='west', revision_id='b')
        west.close()
        a, b = decode_v1(original_a).body, decode_v1(original_b).body
        for field in ('boundary', 'wet_regions', 'enclosed_dry_regions'):
            self.assertEqual(a[field], b[field])
        self.assertEqual((a['wet_regions'], a['enclosed_dry_regions']), (2, 0))
        left_a = accept(center, ROUND, original_a)
        right = accept(center, ROUND, independent_piece('east:1', 'east', 'a', RIGHT, RIGHT_WET))
        left_b = accept(center, ROUND, original_b)

        selected = ((left_a, issue_a, 'a', LEFT_WET, (2, 1)), (left_b, issue_b, 'b', LEFT_ARMS, (1, 0)))
        for left, issue_id, revision, west_wet, hand_count in selected:
            with self.subTest(revision=revision):
                report, receipt = sign(center, ROUND, SHIFT, [left.receipt_id, right.receipt_id])
                self.assertEqual(report_counts(report), hand_count)
                self.assertEqual(report_counts(report), reference_counts(WHOLE.coordinates(), west_wet | RIGHT_WET))
                self.assert_sources(report, sorted([
                    (left.receipt_id, issue_id, ROUND, 'west', revision),
                    (right.receipt_id, 'east:1', ROUND, 'east', 'a'),
                ]))
                self.assertEqual(receipt.origins, report.origins)
        self.assert_pair_count(center, 2)

    def test_recuts_and_corner(self):
        wet = LEFT_WET | RIGHT_WET
        rectangles = (WHOLE, LEFT, RIGHT, GridBounds(0, 0, 9, 2), GridBounds(0, 3, 9, 6))
        seeds = [seed(f'cut-{index}', 'r', box, wet) for index, box in enumerate(rectangles)]
        source = self.station('cut-station', seeds)
        center = self.center()
        parts = [self.publish_to_center(source, center, item[1], item[2]) for item in seeds]
        source.close()
        expected = reference_counts(WHOLE.coordinates(), wet)
        self.assertEqual(expected, (2, 1))
        for indexes in ((0,), (1, 2), (4, 3)):
            with self.subTest(indexes=indexes):
                receipts = [parts[index] for index in indexes]
                pair = sign(center, ROUND, SHIFT, [received.receipt_id for received in receipts])
                self.assertEqual(report_counts(pair[0]), expected)
                self.assert_sources(pair[0], sorted([
                    (parts[index].receipt_id, f'cut-station:{index + 1}', ROUND, f'cut-{index}', 'r')
                    for index in indexes
                ]))
        # A second cut has contact only at a corner.
        corner = ((0, 0), (1, 1))
        with_tiles = []
        for index, point in enumerate(corner):
            box = GridBounds(*point, *point)
            piece = independent_piece(f'diagonal:{index}', f'diagonal-{index}', 'r', box, [point])
            with_tiles.append(accept(center, ROUND, piece).receipt_id)
        report, _ = sign(center, ROUND, SHIFT, with_tiles)
        self.assertEqual(report_counts(report), (1, 0))

    def test_four_tile_corner(self):
        box = GridBounds(0, 0, 1, 1)
        wet = {(0, 0), (1, 1)}
        points = list(box.coordinates())
        tiles = [seed(f'p{index}', 'r', GridBounds(*point, *point), wet) for index, point in enumerate(points)]
        source = self.station('corner', [*tiles, seed('whole', 'r', box, wet)])
        center = self.center()
        cut = [self.publish_to_center(source, center, tile[1], 'r') for tile in tiles]
        whole = self.publish_to_center(source, center, 'whole', 'r')
        source.close()
        for selected in ([item.receipt_id for item in reversed(cut)], [whole.receipt_id]):
            report, receipt = sign(center, ROUND, SHIFT, selected)
            self.assertEqual(report_counts(report), (1, 0))
            self.assertEqual(report_counts(report), reference_counts(points, wet))
            self.assertEqual([origin.receipt_id for origin in report.origins], sorted(selected))
            self.assertEqual(receipt.origins, report.origins)

    def test_exterior_neighborhood(self):
        center = self.center()
        wet = {(0, 1), (1, 0), (1, 2), (2, 1)}
        domain = wet | {(1, 1)}
        by_point = {}
        for index, point in enumerate(sorted(domain)):
            piece = independent_piece(
                f'exterior:{index}', f'p{index}', 'r', GridBounds(*point, *point), {point} & wet
            )
            by_point[point] = accept(center, ROUND, piece).receipt_id
        for selected_domain, expected in ((domain, (1, 1)), (domain - {(1, 0)}, (1, 0))):
            with self.subTest(domain=selected_domain):
                selected = [by_point[point] for point in sorted(selected_domain)]
                report, _ = sign(center, ROUND, SHIFT, selected)
                self.assertEqual(reference_counts(selected_domain, selected_domain & wet), expected)
                self.assertEqual(report_counts(report), expected)
                self.assertEqual([origin.receipt_id for origin in report.origins], sorted(selected))

        ring_cover = GridBounds(0, 0, 4, 4)
        boundary = {(x, y) for x, y in ring_cover.coordinates() if x in (0, 4) or y in (0, 4)}
        selected_domain = set(ring_cover.coordinates()) - {(2, 2)}
        selected = []
        for index, point in enumerate(sorted(selected_domain)):
            piece = independent_piece(
                f'gap:{index}', f'gap-{index}', 'r', GridBounds(*point, *point), {point} & boundary
            )
            selected.append(accept(center, ROUND, piece).receipt_id)
        report, _ = sign(center, ROUND, SHIFT, selected)
        self.assertEqual(reference_counts(selected_domain, boundary), (1, 0))
        self.assertEqual(report_counts(report), (1, 0))

    def test_empty_and_reordered(self):
        center = self.center()
        ids = [
            accept(center, ROUND, independent_piece('standalone:a', 'left', 'a', LEFT, LEFT_WET)).receipt_id,
            accept(center, ROUND, independent_piece('standalone:b', 'right', 'a', RIGHT, RIGHT_WET)).receipt_id,
        ]
        empty = sign(center, ROUND, SHIFT, [])
        self.assertEqual(report_counts(empty[0]), (0, 0))
        self.assertEqual((empty[0].origins, empty[1].origins), ((), ()))
        first, _ = sign(center, ROUND, SHIFT, ids)
        reordered, _ = sign(center, ROUND, SHIFT, iter([ids[1], ids[0], ids[1]]))
        self.assertEqual(report_counts(first), (2, 1))
        self.assertEqual(report_counts(reordered), report_counts(first))
        self.assertEqual(reordered.origins, first.origins)
        self.assertNotEqual(reordered.report_id, first.report_id)
        self.assertEqual(read(center, empty[0].report_id), empty)

    def test_overlap_rejected(self):
        center = self.center()
        tiles = (GridBounds(0, 0, 1, 1), GridBounds(1, 0, 2, 1), GridBounds(2, 0, 3, 1))
        ids = []
        for index, bounds in enumerate(tiles):
            piece = independent_piece(f'overlap:{index}', f't{index}', 'r', bounds, set(bounds.coordinates()))
            ids.append(accept(center, ROUND, piece).receipt_id)
        with self.assertRaisesRegex(SignRejected, 'share a grid cell'):
            sign(center, ROUND, SHIFT, ids[:2])
        self.assert_pair_count(center, 0)
        adjacent, receipt = sign(center, ROUND, SHIFT, [ids[0], ids[2]])
        self.assertEqual(report_counts(adjacent), (1, 0))
        self.assertEqual(adjacent.origins, receipt.origins)
        self.assert_pair_count(center, 1)

    def test_report_commit_failure(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'center.sqlite3'
            center = self.center(path)
            received = accept(center, ROUND, independent_piece('partner:1', 'west', 'a', LEFT, LEFT_WET))
            ids = [received.receipt_id]
            first = sign(center, ROUND, SHIFT, ids)
            center.execute('''CREATE TEMP TRIGGER fail_first_receipt BEFORE INSERT ON main.first_receipts
                              BEGIN SELECT RAISE(ABORT, 'first receipt write failed'); END''')
            with self.assertRaisesRegex(SignRejected, 'first receipt write failed'):
                sign(center, ROUND, SHIFT, ids)
            self.assert_pair_count(center, 1)
            center.execute('DROP TRIGGER temp.fail_first_receipt')

            fail_at_commit(center, 'first_receipts')
            with self.assertRaises(SignRejected) as failure:
                sign(center, ROUND, SHIFT, ids)
            self.assertIsInstance(failure.exception.__cause__, sqlite3.IntegrityError)
            self.assertFalse(center.in_transaction)
            self.assert_pair_count(center, 1)
            observer = self.database(path)
            self.assert_pair_count(observer, 1)
            self.assertEqual(read(observer, first[0].report_id), first)
            resume_commits(center)
            retry = sign(center, ROUND, SHIFT, ids)
            self.assertNotEqual(retry[0].report_id, first[0].report_id)
            self.assertEqual(report_counts(retry[0]), (2, 0))
            self.assertEqual(read(observer, retry[0].report_id), retry)
            self.assertEqual(read(observer, first[0].report_id), first)
            self.assert_pair_count(observer, 2)
            observer.close()
            center.close()

    def test_degenerate_grids_and_exact_coordinates(self):
        base = 2**80
        horizontal = GridBounds(base, -7, base + 2, -7)
        vertical = GridBounds(base + 2, -6, base + 2, -4)
        wet = {(base, -7), (base + 2, -7), (base + 2, -6), (base + 2, -5), (base + 2, -4)}
        source = self.station('extreme', [seed('row', 'r', horizontal, wet), seed('col', 'r', vertical, wet)])
        center = self.center()
        row = self.publish_to_center(source, center, 'row', 'r')
        col = self.publish_to_center(source, center, 'col', 'r')
        source.close()
        self.assertEqual(row.envelope.bounds, horizontal)
        self.assertEqual(col.envelope.bounds, vertical)
        report, _ = sign(center, ROUND, SHIFT, [row.receipt_id, col.receipt_id])
        self.assertEqual(report_counts(report), (2, 0))
        self.assertEqual(report_counts(report), reference_counts(
            set(horizontal.coordinates()) | set(vertical.coordinates()), wet
        ))

    def test_exhaustive_small_selected_domains(self):
        center = self.center()
        points = ((-1, -1), (0, -1), (-1, 0), (0, 0))
        seeds = [
            seed(f'cell-{index}', kind, GridBounds(*point, *point), [point] if kind == 'wet' else [])
            for index, point in enumerate(points) for kind in ('wet', 'dry')
        ]
        source = self.station('tiny', seeds)
        ids = {
            (index, kind): self.publish_to_center(source, center, f'cell-{index}', kind).receipt_id
            for index in range(len(points)) for kind in ('wet', 'dry')
        }
        source.close()
        for states in product(('outside', 'wet', 'dry'), repeat=len(points)):
            with self.subTest(states=states):
                domain = {point for point, state in zip(points, states) if state != 'outside'}
                wet = {point for point, state in zip(points, states) if state == 'wet'}
                selected = [ids[index, state] for index, state in enumerate(states) if state != 'outside']
                report, receipt = sign(center, ROUND, SHIFT, selected)
                self.assertEqual(report_counts(report), reference_counts(domain, wet))
                self.assertEqual([origin.receipt_id for origin in report.origins], sorted(selected))
                self.assertEqual(receipt.origins, report.origins)
