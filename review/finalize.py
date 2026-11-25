import sqlite3
from collections.abc import Iterable

from receipt.selection import InvalidSelection, resolve_selection
from review.coverage import OverlappingTiles, build_coverage
from review.provenance import snapshot_origin
from review.report_store import FirstReceipt, ReportStore, SignedReport
from review.topology import InsufficientEvidence, count_selected_regions


class SignRejected(ValueError):
    pass


def sign(
    db: sqlite3.Connection, round_id: str, shift_id: str, receipt_ids: Iterable[int]
) -> tuple[SignedReport, FirstReceipt]:
    try:
        selection = resolve_selection(db, round_id, shift_id, receipt_ids)
        coverage = build_coverage(selection)
        counts = count_selected_regions(selection, coverage)
        origins = snapshot_origin(selection)
        return ReportStore(db).commit_pair(
            selection.round_id, selection.shift_id, counts.wet_regions,
            counts.enclosed_dry_regions, origins,
        )
    except (InvalidSelection, OverlappingTiles, InsufficientEvidence, sqlite3.Error) as exc:
        raise SignRejected(str(exc)) from exc


def sign_revisit(db, old_report_id: int, new_report_id: int, originals: Iterable[bytes]):
    # Imported lazily so the V1 module graph stays unchanged for existing callers.
    from review.revisit_finalize import sign_revisit as _sign_revisit

    return _sign_revisit(db, old_report_id, new_report_id, originals)
