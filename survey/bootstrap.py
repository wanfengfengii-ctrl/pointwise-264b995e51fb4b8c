import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from issue.archive import IssueArchive
from quality.review_store import TileCheckStore
from survey.grid import GridBounds, GridKey
from survey.revisions import ingest
from survey.store import RevisionStore
from survey.validation import InvalidGrid


SeedGrid = tuple[str, str, str, GridBounds, Iterable[object]]


@dataclass(frozen=True)
class InitializationResult:
    added: tuple[GridKey, ...]
    reused: tuple[GridKey, ...]
    conflicts: tuple[tuple[GridKey, str], ...]


def initialize_survey(
    db: sqlite3.Connection, station: str, seeds: Iterable[SeedGrid]
) -> InitializationResult:
    IssueArchive(db).ensure_schema(station)
    RevisionStore(db).ensure_schema()
    TileCheckStore(db).ensure_schema()
    added = []
    reused = []
    conflicts = []
    for round_id, tile_id, revision_id, bounds, cells in seeds:
        key = (round_id, tile_id, revision_id)
        try:
            result = ingest(db, *key, bounds, cells)
        except InvalidGrid as exc:
            conflicts.append((key, str(exc)))
        else:
            destination = added if result.created else reused
            destination.append(result.revision.key)
    return InitializationResult(tuple(added), tuple(reused), tuple(conflicts))
