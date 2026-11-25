import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from issue.envelope import decode_v1
from issue.publish import PublicationError, publish
from samples import LEFT, ROUND, WEST_CORRECTION, WEST_INITIAL
from survey.revisions import ingest
from tests.support import ProjectTest, fail_at_commit, resume_commits, row_count


class IssueTest(ProjectTest):
    def test_publish_rollback(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'issue.sqlite3'
            source = self.station('west', [WEST_INITIAL, WEST_CORRECTION], path)
            original = publish(source, round_id=ROUND, tile_id='west', revision_id='a')
            fail_at_commit(source, 'issued_tiles')
            with self.assertRaises(PublicationError) as failure:
                publish(source, round_id=ROUND, tile_id='west', revision_id='b')
            self.assertIsInstance(failure.exception.__cause__, sqlite3.IntegrityError)
            self.assertFalse(source.in_transaction)
            self.assertEqual(row_count(source, 'issued_tiles'), 1)
            observer = self.database(path)
            self.assertEqual(row_count(observer, 'issued_tiles'), 1)
            self.assertEqual(publish(observer, issue_id=original[0]), original)
            with self.assertRaises(PublicationError):
                publish(observer, issue_id='west:2')
            resume_commits(source)
            committed = publish(source, round_id=ROUND, tile_id='west', revision_id='b')
            self.assertEqual(decode_v1(committed[1]).revision_id, 'b')
            self.assertEqual(publish(observer, issue_id=committed[0]), committed)
            self.assertEqual(row_count(observer, 'issued_tiles'), 2)
            observer.close()
            source.close()

    def test_original_bytes(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'issue.sqlite3'
            source = self.station('west', [WEST_INITIAL], path)
            issued = publish(source, round_id=ROUND, tile_id='west', revision_id='a')
            ingest(source, *WEST_CORRECTION)
            source.close()
            reopened = self.database(path)
            self.assertEqual(publish(reopened, issue_id=issued[0]), issued)
            envelope = decode_v1(issued[1])
            self.assertEqual((envelope.round_id, envelope.tile_id, envelope.revision_id), (ROUND, 'west', 'a'))
            self.assertEqual(envelope.bounds, LEFT)
            self.assertEqual(len(envelope.body['boundary']), 20)
            self.assertNotIn([3, 3, 'wet'], envelope.body['boundary'])
            self.assertEqual(row_count(reopened, 'issued_tiles'), 1)
            reopened.close()

    def test_missing_or_invalid_source(self):
        source = self.station('west', [WEST_INITIAL])
        with self.assertRaises(PublicationError):
            publish(source, round_id=ROUND, tile_id='another-tile', revision_id='a')
        with self.assertRaises(PublicationError):
            publish(source, issue_id='west:1', tile_id='west')
        with source:
            source.execute('UPDATE grid_revisions SET cells = ?', ('[]',))
        with self.assertRaisesRegex(PublicationError, 'does not cover'):
            publish(source, round_id=ROUND, tile_id='west', revision_id='a')
        self.assertEqual(row_count(source, 'issued_tiles'), 0)
