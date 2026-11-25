import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from issue.comparison import decode_comparison
from issue.publish import PublicationError, publish, publish_comparison
from receipt.accept import accept
from review.archive import ReportNotFound, read, read_revisit
from review.finalize import SignRejected, sign, sign_revisit
from revisit_samples import prepare
from tests.support import ProjectTest, fail_at_commit, row_count


class RevisitSampleTest(ProjectTest):
    def _world(self, name):
        center = self.center()
        stations = {}
        boxes = {'move': ('west',), 'seam': ('west', 'east')}[name]
        for tile in boxes:
            stations[tile] = self.station(tile, [])
        report_ids, issues = prepare(center, stations, name)
        return center, stations, report_ids, issues

    def _comparisons(self, stations, issues, old_label, new_label, tiles):
        originals = []
        for tile in tiles:
            old_issue = issues[old_label, tile][0]
            new_issue = issues[new_label, tile][0]
            _comparison_id, original = publish_comparison(stations[tile], old_issue, new_issue)
            originals.append(original)
        return originals

    def test_move_scenarios(self):
        center, stations, report_ids, issues = self._world('move')
        kept = self._comparisons(stations, issues, 'old', 'kept', ('west',))
        revisit_id, checklist, origins = sign_revisit(
            center, report_ids['old'], report_ids['kept'], kept
        )
        self.assertEqual(checklist['old_regions'], ((2, 2),))
        self.assertEqual(checklist['new_regions'], ((2, 2),))
        self.assertEqual(checklist['exited'], ())
        self.assertEqual(checklist['added'], ())
        self.assertEqual(
            checklist['overlaps'],
            (((2, 2), (2, 2), 1, ('continue',)),),
        )
        self.assertEqual(origins['old_report_id'], report_ids['old'])
        self.assertEqual(origins['new_report_id'], report_ids['kept'])
        self.assertEqual(len(origins['comparisons']), 1)
        old_issue, new_issue, comparison_id, original = origins['comparisons'][0]
        self.assertEqual(old_issue, issues['old', 'west'][0])
        self.assertEqual(new_issue, issues['kept', 'west'][0])
        self.assertEqual(original, kept[0])
        self.assertEqual(read_revisit(center, revisit_id), (revisit_id, checklist, origins))

        moved = self._comparisons(stations, issues, 'old', 'moved', ('west',))
        _rid, moved_list, _origins = sign_revisit(
            center, report_ids['old'], report_ids['moved'], moved
        )
        self.assertEqual(moved_list['old_regions'], ((2, 2),))
        self.assertEqual(moved_list['new_regions'], ((6, 2),))
        self.assertEqual(moved_list['exited'], ((2, 2),))
        self.assertEqual(moved_list['added'], ((6, 2),))
        self.assertEqual(moved_list['overlaps'], ())

    def test_seam_scenarios(self):
        center, stations, report_ids, issues = self._world('seam')
        tiles = ('west', 'east')

        kept = self._comparisons(stations, issues, 'old', 'kept', tiles)
        _id, checklist, _o = sign_revisit(center, report_ids['old'], report_ids['kept'], kept)
        self.assertEqual(checklist['overlaps'], (((2, 2), (2, 2), 18, ('continue',)),))

        split = self._comparisons(stations, issues, 'old', 'split', tiles)
        _id, checklist, _o = sign_revisit(center, report_ids['old'], report_ids['split'], split)
        self.assertEqual(
            checklist['overlaps'],
            (
                ((2, 2), (2, 2), 6, ('split',)),
                ((2, 2), (5, 2), 9, ('split',)),
            ),
        )

        reverse = self._comparisons(stations, issues, 'split', 'old', tiles)
        _id, checklist, _o = sign_revisit(center, report_ids['split'], report_ids['old'], reverse)
        self.assertEqual(
            tuple(edge[3] for edge in checklist['overlaps']), (('merge',), ('merge',))
        )

        opened = self._comparisons(stations, issues, 'old', 'opened', tiles)
        _id, checklist, _o = sign_revisit(center, report_ids['old'], report_ids['opened'], opened)
        self.assertEqual(checklist['old_regions'], ((2, 2),))
        self.assertEqual(checklist['new_regions'], ())
        self.assertEqual(checklist['exited'], ((2, 2),))
        self.assertEqual(checklist['added'], ())
        self.assertEqual(checklist['overlaps'], ())

        horizontal = self._comparisons(stations, issues, 'split', 'horizontal', tiles)
        _id, checklist, _o = sign_revisit(
            center, report_ids['split'], report_ids['horizontal'], horizontal
        )
        expected = (
            ((2, 2), (2, 2), 2, ('split', 'merge')),
            ((2, 2), (2, 4), 2, ('split', 'merge')),
            ((5, 2), (2, 2), 3, ('split', 'merge')),
            ((5, 2), (2, 4), 3, ('split', 'merge')),
        )
        self.assertEqual(checklist['overlaps'], expected)

    def test_comparison_never_carries_full_grid(self):
        _center, stations, _reports, issues = self._world('move')
        _comparison_id, original = publish_comparison(
            stations['west'], issues['old', 'west'][0], issues['kept', 'west'][0]
        )
        wire = original.decode('utf-8')
        self.assertNotIn('cells', wire)
        decoded = decode_comparison(original)
        self.assertTrue(all(len(region) == 3 for region in decoded.regions))
        # The exported facts never embed the full per-cell classification grid.
        for record in decoded.regions:
            self.assertEqual(len(record[2]), 2)

    def test_delivery_order_does_not_change_checklist(self):
        center, stations, report_ids, issues = self._world('seam')
        comparisons = self._comparisons(stations, issues, 'old', 'split', ('west', 'east'))
        first_id, first, first_origins = sign_revisit(
            center, report_ids['old'], report_ids['split'], comparisons
        )
        second_id, second, second_origins = sign_revisit(
            center, report_ids['old'], report_ids['split'], list(reversed(comparisons))
        )
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(first, second)
        self.assertEqual(first_origins['comparisons'], second_origins['comparisons'])


class StationComparisonTest(ProjectTest):
    def _station_with_issues(self):
        center = self.center()
        west = self.station('west', [])
        report_ids, issues = prepare(center, {'west': west}, 'move')
        return west, report_ids, issues

    def test_unknown_issue_and_same_round_and_bounds(self):
        west, _reports, issues = self._station_with_issues()
        with self.assertRaises(PublicationError):
            publish_comparison(west, 'west:99', issues['kept', 'west'][0])
        with self.assertRaises(PublicationError):
            publish_comparison(west, issues['old', 'west'][0], 'west:1')
        with self.assertRaises(PublicationError):
            publish_comparison(west, issues['old', 'west'][0], issues['old', 'west'][0])

    def test_bounds_mismatch_rejected_at_center(self):
        from survey.bootstrap import initialize_survey
        from survey.grid import GridBounds
        # Two reports whose selected frames do not pair up across rounds.
        center = self.center()
        source = self.station('frame-station', [])
        box_a = GridBounds(0, 0, 3, 3)
        box_b = GridBounds(4, 0, 7, 3)
        initialize_survey(source, 'frame-station', [
            ('round-a', 'tile', 'r1', box_a,
             [(x, y, 'dry') for x, y in box_a.coordinates()]),
            ('round-b', 'tile', 'r1', box_b,
             [(x, y, 'dry') for x, y in box_b.coordinates()]),
        ])
        report_ids = {}
        for round_id, box in (('round-a', box_a), ('round-b', box_b)):
            _issue_id, original = publish(
                source, round_id=round_id, tile_id='tile', revision_id='r1'
            )
            received = accept(center, round_id, original)
            report_ids[round_id] = sign(center, round_id, 'shift', [received.receipt_id])[0].report_id
        with self.assertRaises(SignRejected):
            sign_revisit(center, report_ids['round-a'], report_ids['round-b'], [])
        self.assertEqual(row_count(center, 'revisits'), 0)

    def test_order_is_caller_defined_and_distinct_serials(self):
        west, _reports, issues = self._station_with_issues()
        old_issue = issues['old', 'west'][0]
        kept_issue = issues['kept', 'west'][0]
        first_id, first = publish_comparison(west, old_issue, kept_issue)
        second_id, second = publish_comparison(west, kept_issue, old_issue)
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(decode_comparison(first).old.issue_id, old_issue)
        self.assertEqual(decode_comparison(second).old.issue_id, kept_issue)
        self.assertEqual(row_count(west, 'comparison_issues'), 2)

    def test_damaged_source_rejected(self):
        west, _reports, issues = self._station_with_issues()
        from issue.comparison_store import ComparisonArchive
        ComparisonArchive(west).ensure_schema()
        # Break the frozen revision backing one issued original.
        with west:
            west.execute(
                "UPDATE grid_revisions SET cells = '[[]]' WHERE round_id = 'old'"
            )
        with self.assertRaises(PublicationError):
            publish_comparison(west, issues['old', 'west'][0], issues['kept', 'west'][0])
        self.assertEqual(row_count(west, 'comparison_issues'), 0)


class SignRejectTest(ProjectTest):
    def _seam(self):
        center = self.center()
        west = self.station('west', [])
        east = self.station('east', [])
        report_ids, issues = prepare(center, {'west': west, 'east': east}, 'seam')
        comparisons = []
        for tile in ('west', 'east'):
            _id, original = publish_comparison(
                west if tile == 'west' else east,
                issues['old', tile][0], issues['kept', tile][0],
            )
            comparisons.append(original)
        return center, west, east, report_ids, issues, comparisons

    def test_unknown_and_same_round_reports(self):
        center, _w, _e, report_ids, _issues, comparisons = self._seam()
        with self.assertRaises(SignRejected):
            sign_revisit(center, 999, report_ids['kept'], comparisons)
        with self.assertRaises(SignRejected):
            sign_revisit(center, report_ids['old'], report_ids['old'], comparisons)
        self.assertEqual(row_count(center, 'revisits'), 0)

    def test_missing_extra_and_duplicate_comparisons(self):
        center, _w, _e, report_ids, _issues, comparisons = self._seam()
        with self.assertRaises(SignRejected):
            sign_revisit(center, report_ids['old'], report_ids['kept'], comparisons[:1])
        with self.assertRaises(SignRejected):
            sign_revisit(center, report_ids['old'], report_ids['kept'], comparisons * 2)
        with self.assertRaises(SignRejected):
            sign_revisit(center, report_ids['old'], report_ids['kept'], [])
        self.assertEqual(row_count(center, 'revisits'), 0)

    def test_wrong_binding_rejected_even_with_identical_bodies(self):
        # move scene: old, kept and moved share identical V1 bodies, so only the
        # binding to the actual received tiles can distinguish the comparisons.
        with TemporaryDirectory() as tmp:
            center_path = Path(tmp) / 'center.sqlite3'
            station_path = Path(tmp) / 'west.sqlite3'
            center = self.center(center_path)
            west = self.station('west', [], station_path)
            reports, issues = prepare(center, {'west': west}, 'move')
            kept_comparison = publish_comparison(
                west, issues['old', 'west'][0], issues['kept', 'west'][0]
            )[1]
            west.close()

            reopened = self.database(station_path)
            moved_comparison = publish_comparison(
                reopened, issues['old', 'west'][0], issues['moved', 'west'][0]
            )[1]
            reopened.close()

            with self.assertRaises(SignRejected):
                sign_revisit(center, reports['old'], reports['moved'], [kept_comparison])
            revisit_id, checklist, _origins = sign_revisit(
                center, reports['old'], reports['moved'], [moved_comparison]
            )
            self.assertEqual(checklist['exited'], ((2, 2),))
            self.assertEqual(row_count(center, 'revisits'), 1)
            center.close()

    def test_bad_bytes_rejected(self):
        center, _w, _e, report_ids, _issues, comparisons = self._seam()
        damaged = comparisons[0][:-1]
        with self.assertRaises(SignRejected):
            sign_revisit(center, report_ids['old'], report_ids['kept'], [damaged, comparisons[1]])
        self.assertEqual(row_count(center, 'revisits'), 0)

    def test_boundary_semantics_conflict_rejected(self):
        import hashlib
        import json
        center, _w, _e, report_ids, _issues, comparisons = self._seam()
        wire = json.loads(comparisons[0])
        payload = json.loads(wire['payload'])
        # Collapse two distinct old-side dry components onto one label; the V1
        # perimeter still keeps them separate, so the partition check must fail.
        old_labels = sorted({
            entry['old'] for entry in payload['boundary'] if entry['old'] is not None
        })
        self.assertGreaterEqual(len(old_labels), 2)
        target = old_labels[0]
        for entry in payload['boundary']:
            if entry['old'] is not None:
                entry['old'] = target
        text = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        tampered = json.dumps(
            {'payload': text, 'digest': hashlib.sha256(text.encode()).hexdigest()},
            sort_keys=True, separators=(',', ':'),
        ).encode()
        with self.assertRaises(SignRejected):
            sign_revisit(center, report_ids['old'], report_ids['kept'], [tampered, comparisons[1]])
        self.assertEqual(row_count(center, 'revisits'), 0)

    def test_rejection_leaves_existing_results_intact(self):
        center, _w, _e, report_ids, _issues, comparisons = self._seam()
        revisit_id, checklist, origins = sign_revisit(
            center, report_ids['old'], report_ids['kept'], comparisons
        )
        with self.assertRaises(SignRejected):
            sign_revisit(center, report_ids['old'], report_ids['kept'], [])
        self.assertEqual(read_revisit(center, revisit_id), (revisit_id, checklist, origins))
        self.assertEqual(row_count(center, 'revisits'), 1)


class CrossTileTopologyTest(ProjectTest):
    def test_global_anchor_merges_local_enclosures_across_seam(self):
        from survey.bootstrap import initialize_survey
        from survey.grid import GridBounds
        center = self.center()
        west = self.station('seam-west', [])
        east = self.station('seam-east', [])
        whole = GridBounds(0, 0, 3, 2)
        wet = set(whole.perimeter_coordinates())
        box_west = GridBounds(0, 0, 1, 2)
        box_east = GridBounds(2, 0, 3, 2)

        def records(box):
            return [(x, y, 'wet' if (x, y) in wet else 'dry') for x, y in box.coordinates()]

        initialize_survey(west, 'seam-west', [
            ('r-a', 't', 'f', box_west, records(box_west)),
            ('r-b', 't', 'f', box_west, records(box_west)),
        ])
        initialize_survey(east, 'seam-east', [
            ('r-a', 't', 'f', box_east, records(box_east)),
            ('r-b', 't', 'f', box_east, records(box_east)),
        ])
        report_ids = {}
        for round_id in ('r-a', 'r-b'):
            receipt_ids = []
            for station in (west, east):
                _issue_id, original = publish(
                    station, round_id=round_id, tile_id='t', revision_id='f'
                )
                receipt_ids.append(accept(center, round_id, original).receipt_id)
            report_ids[round_id] = sign(center, round_id, 's', receipt_ids)[0].report_id
        comparisons = [
            publish_comparison(west, 'seam-west:1', 'seam-west:2')[1],
            publish_comparison(east, 'seam-east:1', 'seam-east:2')[1],
        ]
        _revisit_id, checklist, _origins = sign_revisit(
            center, report_ids['r-a'], report_ids['r-b'], comparisons
        )
        self.assertEqual(checklist['old_regions'], ((1, 1),))
        self.assertEqual(checklist['new_regions'], ((1, 1),))
        self.assertEqual(
            checklist['overlaps'], (((1, 1), (1, 1), 2, ('continue',)),)
        )


class EmptySelectionTest(ProjectTest):
    def test_empty_reports_allow_empty_checklist(self):
        center = self.center()
        first = sign(center, 'round-a', 'shift', [])
        second = sign(center, 'round-b', 'shift', [])
        revisit_id, checklist, origins = sign_revisit(
            center, first[0].report_id, second[0].report_id, []
        )
        self.assertTrue(revisit_id > 0)
        self.assertEqual(
            set(checklist), {'old_regions', 'new_regions', 'exited', 'added', 'overlaps'}
        )
        self.assertTrue(all(value == () for value in checklist.values()))
        self.assertEqual(origins['comparisons'], [])
        self.assertEqual(read_revisit(center, revisit_id)[1], checklist)

    def test_empty_against_nonempty_rejected(self):
        center, _w, _e, report_ids, _issues, comparisons = SignRejectTest._seam(self)
        empty = sign(center, 'lonely-round', 'shift', [])
        with self.assertRaises(SignRejected):
            sign_revisit(center, empty[0].report_id, report_ids['kept'], comparisons)


class PersistenceTest(ProjectTest):
    def test_sign_after_stations_closed_and_reopen_center(self):
        with TemporaryDirectory() as tmp:
            center_path = Path(tmp) / 'center.sqlite3'
            west_path = Path(tmp) / 'west.sqlite3'
            center = self.center(center_path)
            west = self.station('west', [], west_path)
            report_ids, issues = prepare(center, {'west': west}, 'move')
            _comparison_id, comparison = publish_comparison(
                west, issues['old', 'west'][0], issues['kept', 'west'][0]
            )
            west.close()

            revisit_id, checklist, origins = sign_revisit(
                center, report_ids['old'], report_ids['kept'], [comparison]
            )
            # V1 reports remain readable alongside revisit results.
            v1 = read(center, report_ids['old'])
            center.close()

            reopened = self.database(center_path)
            self.assertEqual(read_revisit(reopened, revisit_id), (revisit_id, checklist, origins))
            self.assertEqual(read(reopened, report_ids['old']), v1)
            with self.assertRaises(ReportNotFound):
                read_revisit(reopened, revisit_id + 100)
            reopened.close()

    def test_commit_failure_rolls_back_and_retry_succeeds(self):
        center, _w, _e, report_ids, _issues, comparisons = SignRejectTest._seam(self)
        from review.revisit_store import RevisitStore
        RevisitStore(center).ensure_schema()
        fail_at_commit(center, 'revisits')
        with self.assertRaises(SignRejected):
            sign_revisit(center, report_ids['old'], report_ids['kept'], comparisons)
        self.assertFalse(center.in_transaction)
        self.assertEqual(row_count(center, 'revisits'), 0)
        from tests.support import resume_commits
        resume_commits(center)
        revisit_id, checklist, origins = sign_revisit(
            center, report_ids['old'], report_ids['kept'], comparisons
        )
        self.assertEqual(read_revisit(center, revisit_id), (revisit_id, checklist, origins))
