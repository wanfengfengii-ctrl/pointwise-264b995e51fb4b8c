import sqlite3

from review.report_store import FirstReceipt, ReportStore, SignedReport


class ReportNotFound(LookupError):
    pass


def read(db: sqlite3.Connection, report_id: int) -> tuple[SignedReport, FirstReceipt]:
    saved = ReportStore(db).get_pair(report_id)
    if saved is None:
        raise ReportNotFound(f'unknown signed report {report_id!r}')
    return saved
