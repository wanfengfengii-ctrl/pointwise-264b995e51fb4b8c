import sqlite3

from issue.envelope import V1Envelope, encode_v1
from survey.grid import GridBounds, valid_identifier


class IssueArchive:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def ensure_schema(self, station: str) -> None:
        if not valid_identifier(station):
            raise ValueError('invalid station issuance namespace')
        self.db.execute('BEGIN IMMEDIATE')
        with self.db:
            self.db.execute(
                '''CREATE TABLE IF NOT EXISTS issue_station (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    station TEXT NOT NULL
                )'''
            )
            self.db.execute(
                '''CREATE TABLE IF NOT EXISTS issued_tiles (
                    serial INTEGER PRIMARY KEY,
                    issue_id TEXT NOT NULL UNIQUE,
                    original BLOB NOT NULL
                )'''
            )
            self.db.execute(
                '''INSERT INTO issue_station VALUES (1, ?)
                   ON CONFLICT (singleton) DO NOTHING''',
                (station,),
            )
            saved = self.db.execute('SELECT station FROM issue_station WHERE singleton = 1').fetchone()
            if saved[0] != station:
                raise ValueError('station database belongs to a different issuance namespace')
            self.db.commit()

    def commit_issue(
        self, round_id: str, tile_id: str, revision_id: str, bounds: GridBounds, body: dict
    ) -> tuple[str, bytes]:
        self.db.execute('BEGIN IMMEDIATE')
        with self.db:
            station = self.db.execute('SELECT station FROM issue_station WHERE singleton = 1').fetchone()
            if station is None:
                raise ValueError('station issuance namespace has not been initialized')
            serial = self.db.execute('SELECT COALESCE(MAX(serial), 0) FROM issued_tiles').fetchone()[0] + 1
            issue_id = f'{station[0]}:{serial}'
            original = encode_v1(V1Envelope(issue_id, round_id, tile_id, revision_id, bounds, body))
            self.db.execute('INSERT INTO issued_tiles VALUES (?, ?, ?)', (serial, issue_id, original))
            self.db.commit()
        return issue_id, original

    def get_original(self, issue_id: str) -> bytes | None:
        row = self.db.execute('SELECT original FROM issued_tiles WHERE issue_id = ?', (issue_id,)).fetchone()
        return None if row is None else row[0]
