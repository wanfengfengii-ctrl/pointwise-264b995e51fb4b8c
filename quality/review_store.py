import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class TileCheck:
    round_id: str
    tile_id: str
    revision_id: str
    wet_regions: int
    enclosed_dry_regions: int

    @property
    def key(self) -> tuple[str, str, str]:
        return self.round_id, self.tile_id, self.revision_id


class TileCheckStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def ensure_schema(self) -> None:
        self.db.execute(
            '''CREATE TABLE IF NOT EXISTS tile_checks (
                round_id TEXT NOT NULL,
                tile_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                wet_regions INTEGER NOT NULL CHECK (wet_regions >= 0),
                enclosed_dry_regions INTEGER NOT NULL CHECK (enclosed_dry_regions >= 0),
                PRIMARY KEY (round_id, tile_id, revision_id)
            )'''
        )

    def get(self, round_id: str, tile_id: str, revision_id: str) -> TileCheck | None:
        row = self.db.execute(
            '''SELECT wet_regions, enclosed_dry_regions FROM tile_checks
               WHERE round_id = ? AND tile_id = ? AND revision_id = ?''',
            (round_id, tile_id, revision_id),
        ).fetchone()
        if row is None:
            return None
        return TileCheck(round_id, tile_id, revision_id, *row)

    def save(self, check: TileCheck) -> TileCheck:
        self.db.execute('BEGIN IMMEDIATE')
        with self.db:
            self.db.execute(
                '''INSERT INTO tile_checks VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (round_id, tile_id, revision_id) DO NOTHING''',
                (*check.key, check.wet_regions, check.enclosed_dry_regions),
            )
            saved = self.get(*check.key)
            if saved != check:
                raise ValueError(f'quality review for {check.key!r} already has different counts')
            self.db.commit()
        return saved
