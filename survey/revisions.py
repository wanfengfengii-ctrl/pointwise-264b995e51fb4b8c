import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from survey.grid import GridBounds, GridRevision, valid_identifier
from survey.store import RevisionConflict, RevisionStore
from survey.validation import InvalidGrid, validate_grid


class RevisionNotFound(LookupError):
    pass


@dataclass(frozen=True)
class IngestResult:
    revision: GridRevision
    created: bool


def ingest(
    db: sqlite3.Connection,
    round_id: str,
    tile_id: str,
    revision_id: str,
    bounds: GridBounds,
    cells: Iterable[object],
) -> IngestResult:
    if not all(valid_identifier(value) for value in (round_id, tile_id, revision_id)):
        raise InvalidGrid('invalid survey revision identity')
    revision = GridRevision(round_id, tile_id, revision_id, bounds, validate_grid(bounds, cells))
    try:
        frozen, created = RevisionStore(db).freeze(revision)
    except RevisionConflict as exc:
        raise InvalidGrid(str(exc)) from exc
    return IngestResult(frozen, created)


def get_revision(
    db: sqlite3.Connection, round_id: str, tile_id: str, revision_id: str
) -> GridRevision:
    key = (round_id, tile_id, revision_id)
    if not all(valid_identifier(value) for value in key):
        raise InvalidGrid('invalid survey revision identity')
    revision = RevisionStore(db).get(*key)
    if revision is None:
        raise RevisionNotFound(f'unknown frozen revision {key!r}')
    return revision
