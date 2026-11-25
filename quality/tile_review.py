import sqlite3

from quality.dry_regions import count_enclosed_dry_regions
from quality.review_store import TileCheck, TileCheckStore
from quality.wet_regions import count_wet_regions
from survey.revisions import get_revision


def inspect(db: sqlite3.Connection, round_id: str, tile_id: str, revision_id: str) -> TileCheck:
    grid = get_revision(db, round_id, tile_id, revision_id)
    store = TileCheckStore(db)
    saved = store.get(*grid.key)
    if saved is not None:
        return saved
    return store.save(TileCheck(*grid.key, count_wet_regions(grid), count_enclosed_dry_regions(grid)))
