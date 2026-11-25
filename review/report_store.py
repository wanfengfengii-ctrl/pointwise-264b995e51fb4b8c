import json
import sqlite3
from dataclasses import asdict, dataclass

from review.provenance import ReportOrigin


@dataclass(frozen=True)
class SignedReport:
    report_id: int
    round_id: str
    shift_id: str
    wet_regions: int
    enclosed_dry_regions: int
    origins: tuple[ReportOrigin, ...]


@dataclass(frozen=True)
class FirstReceipt:
    report_id: int
    confirmation_id: str
    origins: tuple[ReportOrigin, ...]


def _decode_origins(text: str) -> tuple[ReportOrigin, ...]:
    return tuple(ReportOrigin(**record) for record in json.loads(text))


class ReportStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def ensure_schema(self) -> None:
        self.db.execute(
            '''CREATE TABLE IF NOT EXISTS reports (
                report_id INTEGER PRIMARY KEY,
                round_id TEXT NOT NULL,
                shift_id TEXT NOT NULL,
                wet_regions INTEGER NOT NULL CHECK (wet_regions >= 0),
                enclosed_dry_regions INTEGER NOT NULL CHECK (enclosed_dry_regions >= 0),
                origins TEXT NOT NULL
            )'''
        )
        self.db.execute(
            '''CREATE TABLE IF NOT EXISTS first_receipts (
                report_id INTEGER PRIMARY KEY REFERENCES reports(report_id),
                confirmation_id TEXT NOT NULL UNIQUE,
                origins TEXT NOT NULL
            )'''
        )

    def commit_pair(
        self,
        round_id: str,
        shift_id: str,
        wet_regions: int,
        enclosed_dry_regions: int,
        origins: tuple[ReportOrigin, ...],
    ) -> tuple[SignedReport, FirstReceipt]:
        saved_origins = json.dumps([asdict(origin) for origin in origins], separators=(',', ':'))
        self.db.execute('BEGIN IMMEDIATE')
        with self.db:
            cursor = self.db.execute(
                '''INSERT INTO reports (round_id, shift_id, wet_regions, enclosed_dry_regions, origins)
                   VALUES (?, ?, ?, ?, ?)''',
                (round_id, shift_id, wet_regions, enclosed_dry_regions, saved_origins),
            )
            report_id = cursor.lastrowid
            confirmation_id = f'FIRST-{report_id}'
            self.db.execute(
                'INSERT INTO first_receipts VALUES (?, ?, ?)',
                (report_id, confirmation_id, saved_origins),
            )
            self.db.commit()
        return (
            SignedReport(report_id, round_id, shift_id, wet_regions, enclosed_dry_regions, origins),
            FirstReceipt(report_id, confirmation_id, origins),
        )

    def get_pair(self, report_id: int) -> tuple[SignedReport, FirstReceipt] | None:
        if type(report_id) is not int or not 1 <= report_id < 2**63:
            return None
        row = self.db.execute(
            '''SELECT r.round_id, r.shift_id, r.wet_regions, r.enclosed_dry_regions,
                      r.origins, f.confirmation_id, f.origins
               FROM reports AS r JOIN first_receipts AS f ON r.report_id = f.report_id
               WHERE r.report_id = ?''',
            (report_id,),
        ).fetchone()
        if row is None:
            return None
        round_id, shift_id, wet, dry, report_origins, confirmation_id, receipt_origins = row
        return (
            SignedReport(report_id, round_id, shift_id, wet, dry, _decode_origins(report_origins)),
            FirstReceipt(report_id, confirmation_id, _decode_origins(receipt_origins)),
        )
