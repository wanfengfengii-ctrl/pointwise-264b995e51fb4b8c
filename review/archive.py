import sqlite3

from review.report_store import FirstReceipt, ReportStore, SignedReport
from review.revisit_store import RevisitStore, decode_origins


class ReportNotFound(LookupError):
    pass


def read(db: sqlite3.Connection, report_id: int) -> tuple[SignedReport, FirstReceipt]:
    saved = ReportStore(db).get_pair(report_id)
    if saved is None:
        raise ReportNotFound(f'unknown signed report {report_id!r}')
    return saved


def read_revisit(db: sqlite3.Connection, revisit_id: int):
    if type(revisit_id) is not int or not 1 <= revisit_id < 2**63:
        raise ReportNotFound(f'unknown revisit {revisit_id!r}')
    record = RevisitStore(db).get_record(revisit_id)
    if record is None:
        raise ReportNotFound(f'unknown revisit {revisit_id!r}')

    def as_point(value):
        return tuple(value)

    checklist_raw = record['checklist']
    checklist = {}
    for key, value in checklist_raw.items():
        if key == 'overlaps':
            checklist[key] = tuple(
                (tuple(edge[0]), tuple(edge[1]), edge[2], tuple(edge[3])) for edge in value
            )
        else:
            checklist[key] = tuple(as_point(point) for point in value)
    origins_raw = record['origins']
    origins = {
        'old_report_id': origins_raw['old_report_id'],
        'new_report_id': origins_raw['new_report_id'],
        'comparisons': decode_origins(origins_raw)['comparisons'],
    }
    return revisit_id, checklist, origins
