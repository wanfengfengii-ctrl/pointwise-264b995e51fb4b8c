import sqlite3
from dataclasses import dataclass

from issue.envelope import V1Envelope, decode_v1


class ReceiptConflict(ValueError):
    pass


@dataclass(frozen=True)
class ReceivedTile:
    receipt_id: int
    original: bytes

    @property
    def envelope(self) -> V1Envelope:
        return decode_v1(self.original)


class ReceiptStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def ensure_schema(self) -> None:
        self.db.execute(
            '''CREATE TABLE IF NOT EXISTS received_tiles (
                receipt_id INTEGER PRIMARY KEY,
                issue_id TEXT NOT NULL UNIQUE,
                original BLOB NOT NULL
            )'''
        )

    def register(self, envelope: V1Envelope, original: bytes) -> ReceivedTile:
        self.db.execute('BEGIN IMMEDIATE')
        with self.db:
            self.db.execute(
                '''INSERT INTO received_tiles (issue_id, original) VALUES (?, ?)
                   ON CONFLICT (issue_id) DO NOTHING''',
                (envelope.issue_id, original),
            )
            receipt_id, registered = self.db.execute(
                'SELECT receipt_id, original FROM received_tiles WHERE issue_id = ?',
                (envelope.issue_id,),
            ).fetchone()
            if registered != original:
                raise ReceiptConflict(f'issue {envelope.issue_id!r} is already bound to different bytes')
            self.db.commit()
        return ReceivedTile(receipt_id, registered)

    def get(self, receipt_id: int) -> ReceivedTile | None:
        if type(receipt_id) is not int or not 1 <= receipt_id < 2**63:
            return None
        row = self.db.execute(
            'SELECT original FROM received_tiles WHERE receipt_id = ?', (receipt_id,)
        ).fetchone()
        return None if row is None else ReceivedTile(receipt_id, row[0])
