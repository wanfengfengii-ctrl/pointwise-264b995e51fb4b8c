import sqlite3

from issue.comparison import RevisitComparison, encode_comparison


class ComparisonArchive:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def ensure_schema(self) -> None:
        self.db.execute(
            '''CREATE TABLE IF NOT EXISTS comparison_issues (
                serial INTEGER PRIMARY KEY,
                comparison_id TEXT NOT NULL UNIQUE,
                old_issue_id TEXT NOT NULL,
                new_issue_id TEXT NOT NULL,
                original BLOB NOT NULL
            )'''
        )

    def commit_comparison(
        self, station: str, old_issue_id: str, new_issue_id: str, comparison: RevisitComparison
    ) -> tuple[str, bytes]:
        self.db.execute('BEGIN IMMEDIATE')
        with self.db:
            serial = self.db.execute(
                'SELECT COALESCE(MAX(serial), 0) FROM comparison_issues'
            ).fetchone()[0] + 1
            comparison_id = f'{station}:cmp:{serial}'
            issued = RevisitComparison(
                comparison_id,
                comparison.bounds,
                comparison.old,
                comparison.new,
                comparison.regions,
                comparison.boundary,
                comparison.overlaps,
            )
            original = encode_comparison(issued)
            self.db.execute(
                'INSERT INTO comparison_issues VALUES (?, ?, ?, ?, ?)',
                (serial, comparison_id, old_issue_id, new_issue_id, original),
            )
            self.db.commit()
        return comparison_id, original

    def get_original(self, comparison_id: str) -> bytes | None:
        row = self.db.execute(
            'SELECT original FROM comparison_issues WHERE comparison_id = ?', (comparison_id,)
        ).fetchone()
        return None if row is None else row[0]
