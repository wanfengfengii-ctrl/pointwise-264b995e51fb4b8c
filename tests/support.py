import sqlite3
import unittest

from issue.envelope import V1Envelope, encode_v1
from issue.publish import publish
from receipt.accept import accept
from receipt.store import ReceiptStore
from review.report_store import ReportStore
from samples import ROUND
from survey.bootstrap import initialize_survey


def _four(left, right):
    return abs(left[0] - right[0]) + abs(left[1] - right[1]) == 1


def _eight(left, right):
    return max(abs(left[0] - right[0]), abs(left[1] - right[1])) == 1


def _partition(points, adjacent):
    remaining = set(points)
    while remaining:
        first = min(remaining)
        remaining.remove(first)
        component = {first}
        queue = [first]
        for point in queue:
            reached = {other for other in remaining if adjacent(point, other)}
            remaining.difference_update(reached)
            component.update(reached)
            queue.extend(reached)
        yield component


def _exterior(domain):
    neighbors = set()
    for x, y in domain:
        neighbors.update(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
    return neighbors - domain


def _closed(group, exterior):
    return not any(_four(point, off_grid) for point in group for off_grid in exterior)


def reference_counts(domain, wet):
    domain, wet = set(domain), set(wet)
    if not wet <= domain:
        raise ValueError('reference wet cells must belong to the reference domain')
    exterior = _exterior(domain)
    return (
        len(list(_partition(wet, _eight))),
        sum(_closed(group, exterior) for group in _partition(domain - wet, _four)),
    )


def independent_piece(issue_id, tile, revision, bounds, wet, round_id=ROUND):
    x0, y0, x1, y1 = bounds.as_tuple()
    wet = set(wet)
    domain = {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
    exterior = _exterior(domain)
    groups = {
        'dry': list(_partition(domain - wet, _four)),
        'wet': list(_partition(wet, _eight)),
    }
    edge = sorted(
        (point for point in domain if any(_four(point, outer) for outer in exterior)),
        key=lambda point: (point[1], point[0]),
    )
    boundary, links = [], []
    labels = {'wet': {}, 'dry': {}}
    for x, y in edge:
        kind = 'wet' if (x, y) in wet else 'dry'
        number = next(index for index, group in enumerate(groups[kind]) if (x, y) in group)
        boundary.append([x, y, kind])
        links.append(labels[kind].setdefault(number, len(labels[kind])))
    body = {
        'wet_regions': len(groups['wet']),
        'enclosed_dry_regions': sum(_closed(group, exterior) for group in groups['dry']),
        'boundary': boundary,
        'links': links,
    }
    return encode_v1(V1Envelope(issue_id, round_id, tile, revision, bounds, body))


def report_counts(report):
    return report.wet_regions, report.enclosed_dry_regions


def row_count(db, table):
    return db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]


def fail_at_commit(db, table):
    # The trigger inserts a deferred violation after the business row is written.
    # SQLite checks the violation at the actual COMMIT.
    db.executescript(f'''
        CREATE TEMP TABLE commit_parent (id INTEGER PRIMARY KEY);
        CREATE TEMP TABLE commit_violation (
            parent_id INTEGER REFERENCES commit_parent(id) DEFERRABLE INITIALLY DEFERRED
        );
        CREATE TEMP TRIGGER reject_commit AFTER INSERT ON main.{table}
        BEGIN
            INSERT INTO commit_violation VALUES (1);
        END;
    ''')


def resume_commits(db):
    db.execute('DROP TRIGGER temp.reject_commit')


class ProjectTest(unittest.TestCase):
    def database(self, path=':memory:'):
        db = sqlite3.connect(path)
        self.addCleanup(db.close)
        db.execute('PRAGMA foreign_keys = ON')
        return db

    def station(self, name, seeds, path=':memory:'):
        db = self.database(path)
        result = initialize_survey(db, name, seeds)
        self.assertFalse(result.conflicts)
        return db

    def center(self, path=':memory:'):
        db = self.database(path)
        ReceiptStore(db).ensure_schema()
        ReportStore(db).ensure_schema()
        return db

    def publish_to_center(self, source, center, tile, revision, round_id=ROUND):
        issue_id, original = publish(source, round_id=round_id, tile_id=tile, revision_id=revision)
        received = accept(center, round_id, original)
        self.assertEqual(received.envelope.issue_id, issue_id)
        return received

    def assert_pair_count(self, db, expected):
        self.assertEqual(row_count(db, 'reports'), expected)
        self.assertEqual(row_count(db, 'first_receipts'), expected)

    def assert_sources(self, report, expected):
        self.assertEqual(
            [(item.receipt_id, item.issue_id, item.round_id, item.tile_id, item.revision_id)
             for item in report.origins],
            expected,
        )
