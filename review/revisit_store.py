import base64
import json
import sqlite3


class RevisitStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def ensure_schema(self) -> None:
        self.db.execute(
            '''CREATE TABLE IF NOT EXISTS revisits (
                revisit_id INTEGER PRIMARY KEY,
                record TEXT NOT NULL
            )'''
        )

    def commit(self, record: dict) -> int:
        self.db.execute('BEGIN IMMEDIATE')
        with self.db:
            cursor = self.db.execute(
                'INSERT INTO revisits (record) VALUES (?)',
                (json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=True),),
            )
            self.db.commit()
            return cursor.lastrowid

    def get_record(self, revisit_id: int) -> dict | None:
        row = self.db.execute(
            'SELECT record FROM revisits WHERE revisit_id = ?', (revisit_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])


def encode_origins(
    old_report_id: int,
    new_report_id: int,
    comparisons: list[tuple[str, str, str, bytes]],
) -> dict:
    return {
        'old_report_id': old_report_id,
        'new_report_id': new_report_id,
        'comparisons': [
            {
                'old_issue_id': old_issue_id,
                'new_issue_id': new_issue_id,
                'comparison_id': comparison_id,
                'original': base64.b64encode(original).decode('ascii'),
            }
            for old_issue_id, new_issue_id, comparison_id, original in comparisons
        ],
    }


def decode_origins(record: dict) -> dict:
    return {
        'old_report_id': record['old_report_id'],
        'new_report_id': record['new_report_id'],
        'comparisons': [
            (
                entry['old_issue_id'],
                entry['new_issue_id'],
                entry['comparison_id'],
                base64.b64decode(entry['original'], validate=True),
            )
            for entry in record['comparisons']
        ],
    }
