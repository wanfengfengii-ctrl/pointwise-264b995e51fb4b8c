from pathlib import Path
from tempfile import TemporaryDirectory

from review.archive import ReportNotFound, read
from review.finalize import sign
from samples import EAST_INITIAL, ROUND, SHIFT, WEST_CORRECTION, WEST_INITIAL
from survey.revisions import ingest
from tests.support import ProjectTest, report_counts


class ArchiveTest(ProjectTest):
    def test_read_after_revision(self):
        with TemporaryDirectory() as tmp:
            west_path = Path(tmp) / 'west.sqlite3'
            center_path = Path(tmp) / 'center.sqlite3'
            west = self.station('west', [WEST_INITIAL], west_path)
            east = self.station('east', [EAST_INITIAL])
            center = self.center(center_path)
            left = self.publish_to_center(west, center, 'west', 'a')
            right = self.publish_to_center(east, center, 'east', 'a')
            west.close()
            east.close()
            first = sign(center, ROUND, SHIFT, [left.receipt_id, right.receipt_id])

            west = self.database(west_path)
            ingest(west, *WEST_CORRECTION)
            correction = self.publish_to_center(west, center, 'west', 'b')
            west.close()
            second = sign(center, ROUND, SHIFT, [correction.receipt_id, right.receipt_id])
            center.close()

            reopened = self.database(center_path)
            first_id, second_id = first[0].report_id, second[0].report_id
            self.assertNotEqual(first_id, second_id)
            self.assertEqual(report_counts(first[0]), (2, 1))
            self.assertEqual(report_counts(second[0]), (1, 0))
            self.assert_sources(first[0], [
                (left.receipt_id, 'west:1', ROUND, 'west', 'a'),
                (right.receipt_id, 'east:1', ROUND, 'east', 'a'),
            ])
            self.assert_sources(second[0], [
                (right.receipt_id, 'east:1', ROUND, 'east', 'a'),
                (correction.receipt_id, 'west:2', ROUND, 'west', 'b'),
            ])
            for report_id, expected in ((second_id, second), (first_id, first), (second_id, second)):
                self.assertEqual(read(reopened, report_id), expected)
                self.assertEqual(expected[1].report_id, report_id)
                self.assertEqual(expected[1].confirmation_id, f'FIRST-{report_id}')
                self.assertEqual(expected[1].origins, expected[0].origins)
            self.assert_pair_count(reopened, 2)
            with self.assertRaises(ReportNotFound):
                read(reopened, max(first_id, second_id) + 1)
            reopened.close()

    def test_unknown_report(self):
        center = self.center()
        for report_id in (1, 0, True, 2**64):
            with self.subTest(report_id=report_id), self.assertRaises(ReportNotFound):
                read(center, report_id)
        self.assert_pair_count(center, 0)
