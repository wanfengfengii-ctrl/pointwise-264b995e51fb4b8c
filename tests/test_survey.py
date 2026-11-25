from pathlib import Path
from tempfile import TemporaryDirectory

from issue.publish import publish
from quality.tile_review import inspect
from receipt.accept import accept
from review.archive import read
from review.finalize import sign
from samples import LEFT, ROUND, SHIFT, WEST_CORRECTION, WEST_INITIAL, seed
from survey.bootstrap import initialize_survey
from survey.grid import CellClass, GridBounds
from survey.revisions import RevisionNotFound, get_revision, ingest
from survey.validation import InvalidGrid
from tests.support import ProjectTest, report_counts, row_count


class SurveyTest(ProjectTest):
    def test_frozen_review(self):
        source = self.station('west', [WEST_INITIAL])
        frozen = get_revision(source, ROUND, 'west', 'a')
        original_check = inspect(source, ROUND, 'west', 'a')
        self.assertEqual(report_counts(original_check), (2, 0))
        original = publish(source, round_id=ROUND, tile_id='west', revision_id='a')
        correction = ingest(source, *WEST_CORRECTION)
        self.assertTrue(correction.created)
        self.assertNotEqual(correction.revision.cells, frozen.cells)
        self.assertEqual(report_counts(inspect(source, ROUND, 'west', 'b')), (2, 0))
        self.assertEqual(get_revision(source, ROUND, 'west', 'a'), frozen)
        self.assertEqual(inspect(source, ROUND, 'west', 'a'), original_check)
        self.assertEqual(publish(source, issue_id=original[0]), original)

    def test_conflicting_cell(self):
        source = self.station('west', [WEST_INITIAL])
        original = inspect(source, ROUND, 'west', 'a')
        records = [(x, y, value) for x, y, value in WEST_INITIAL[-1] if (x, y) != (1, 1)]
        for pair in (((1, 1, 'wet'), (1, 1, 'dry')), ((1, 1, 'dry'), (1, 1, 'wet'))):
            with self.subTest(pair=pair), self.assertRaisesRegex(InvalidGrid, 'conflicting classifications'):
                ingest(source, ROUND, 'west', 'bad', LEFT, [*records, *pair])
        self.assertEqual(row_count(source, 'grid_revisions'), 1)
        self.assertEqual(row_count(source, 'tile_checks'), 1)
        self.assertEqual(inspect(source, ROUND, 'west', 'a'), original)
        with self.assertRaises(RevisionNotFound):
            inspect(source, ROUND, 'west', 'bad')

    def test_exact_ingest_replay(self):
        source = self.station('west', [WEST_INITIAL])
        records = list(reversed(WEST_INITIAL[-1]))
        x, y, kind = records[0]
        records.append((x, y, CellClass(kind)))
        replay = ingest(source, *WEST_INITIAL[:-1], records)
        self.assertFalse(replay.created)
        self.assertEqual(replay.revision, get_revision(source, ROUND, 'west', 'a'))
        with self.assertRaisesRegex(InvalidGrid, 'different content'):
            ingest(source, ROUND, 'west', 'a', LEFT, WEST_CORRECTION[-1])
        self.assertEqual(row_count(source, 'grid_revisions'), 1)

    def test_invalid_bounds_or_cells(self):
        source = self.station('west', [])
        for bounds in ((2, 0, 1, 0), (0, 5, 1, 1), (False, 0, 1, 1), (0, 0, 1.0, 1)):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                GridBounds(*bounds)
        box = GridBounds(0, 0, 0, 0)
        bad_records = ([], [(1, 0, 'wet')], [(False, 0, 'dry')], [(0, 0, '')],
                       [(0, 0, None)], [(0, 0)], None)
        for records in bad_records:
            with self.subTest(records=records), self.assertRaises(InvalidGrid):
                ingest(source, ROUND, 'west', 'bad', box, records)
        with self.assertRaises(InvalidGrid):
            ingest(source, ROUND, 'west', 'bad', (0, 0, 0, 0), [(0, 0, 'wet')])
        self.assertEqual(row_count(source, 'grid_revisions'), 0)
        self.assertEqual(row_count(source, 'tile_checks'), 0)

    def test_bootstrap_replay(self):
        with TemporaryDirectory() as tmp:
            source_path = Path(tmp) / 'station.sqlite3'
            center_path = Path(tmp) / 'center.sqlite3'
            source = self.station('west', [WEST_INITIAL], source_path)
            center = self.center(center_path)
            updated = ingest(source, *WEST_CORRECTION).revision
            check = inspect(source, ROUND, 'west', 'b')
            original = publish(source, round_id=ROUND, tile_id='west', revision_id='b')
            received = accept(center, ROUND, original[1])
            signed = sign(center, ROUND, SHIFT, [received.receipt_id])
            source.close()
            center.close()

            source = self.database(source_path)
            replay = initialize_survey(source, 'west', [WEST_INITIAL])
            self.assertEqual(replay.reused, ((ROUND, 'west', 'a'),))
            self.assertEqual((replay.added, replay.conflicts), ((), ()))
            bad_seed = (ROUND, 'west', 'a', LEFT, WEST_CORRECTION[-1])
            rejected = initialize_survey(source, 'west', [bad_seed])
            self.assertEqual(rejected.conflicts[0][0], (ROUND, 'west', 'a'))
            self.assertEqual((rejected.added, rejected.reused), ((), ()))
            self.assertEqual(get_revision(source, ROUND, 'west', 'b'), updated)
            self.assertEqual(inspect(source, ROUND, 'west', 'b'), check)
            self.assertEqual(publish(source, issue_id=original[0]), original)
            self.assertEqual(row_count(source, 'grid_revisions'), 2)
            self.assertEqual(row_count(source, 'issued_tiles'), 1)
            center = self.center(center_path)
            self.assertEqual(accept(center, ROUND, original[1]), received)
            self.assertEqual(row_count(center, 'received_tiles'), 1)
            self.assertEqual(read(center, signed[0].report_id), signed)
            self.assert_pair_count(center, 1)
            source.close()
            center.close()

    def test_pinned_local_check(self):
        box = GridBounds(0, 0, 2, 2)
        ring = {(0, 1), (1, 0), (1, 2), (2, 1)}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'survey.sqlite3'
            source = self.station('station', [seed('ring', 'r1', box, ring)], path)
            original = inspect(source, ROUND, 'ring', 'r1')
            ingest(source, *seed('ring', 'r2', box, set()))
            changed = inspect(source, ROUND, 'ring', 'r2')
            self.assertEqual(report_counts(original), (1, 1))
            self.assertEqual(report_counts(changed), (0, 0))
            self.assertEqual((original.revision_id, changed.revision_id), ('r1', 'r2'))
            source.close()
            reopened = self.database(path)
            self.assertEqual(inspect(reopened, ROUND, 'ring', 'r2'), changed)
            self.assertEqual(inspect(reopened, ROUND, 'ring', 'r1'), original)
            self.assertEqual(row_count(reopened, 'tile_checks'), 2)
            reopened.close()
