import json
import sqlite3

from survey.grid import CellClass, GridBounds, GridRevision


class RevisionConflict(ValueError):
    pass


class RevisionStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def ensure_schema(self) -> None:
        self.db.execute(
            '''CREATE TABLE IF NOT EXISTS grid_revisions (
                round_id TEXT NOT NULL,
                tile_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                geometry TEXT NOT NULL,
                cells TEXT NOT NULL,
                PRIMARY KEY (round_id, tile_id, revision_id)
            )'''
        )

    def freeze(self, revision: GridRevision) -> tuple[GridRevision, bool]:
        geometry = json.dumps(revision.bounds.as_tuple(), separators=(',', ':'))
        cells = json.dumps(revision.cells, separators=(',', ':'))
        self.db.execute('BEGIN IMMEDIATE')
        with self.db:
            insertion = self.db.execute(
                '''INSERT INTO grid_revisions VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (round_id, tile_id, revision_id) DO NOTHING''',
                (*revision.key, geometry, cells),
            )
            created = insertion.rowcount == 1
            if not created:
                existing = self.get(*revision.key)
                if existing != revision:
                    raise RevisionConflict(f'revision {revision.key!r} has different content')
                revision = existing
            self.db.commit()
        return revision, created

    def get(self, round_id: str, tile_id: str, revision_id: str) -> GridRevision | None:
        row = self.db.execute(
            '''SELECT geometry, cells FROM grid_revisions
               WHERE round_id = ? AND tile_id = ? AND revision_id = ?''',
            (round_id, tile_id, revision_id),
        ).fetchone()
        if row is None:
            return None
        geometry, cells = row
        bounds = GridBounds(*json.loads(geometry))
        records = tuple((x, y, CellClass(kind)) for x, y, kind in json.loads(cells))
        return GridRevision(round_id, tile_id, revision_id, bounds, records)
