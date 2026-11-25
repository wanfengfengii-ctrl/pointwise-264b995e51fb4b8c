import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from issue.publish import publish
from quality.tile_review import inspect
from receipt.accept import accept
from receipt.store import ReceiptStore
from review.archive import read
from review.finalize import sign
from review.report_store import ReportStore
from samples import EAST_INITIAL, ROUND, SHIFT, WEST_CORRECTION, WEST_INITIAL
from survey.bootstrap import initialize_survey
from survey.revisions import ingest


def scenario(case_id, expected, pair, saved_pair, expected_sources):
    report, receipt = pair
    saved_report, saved_receipt = saved_pair
    actual = [report.wet_regions, report.enclosed_dry_regions]
    if actual != expected:
        raise SystemExit(f'BASIN_HOLE_COUNT_MISMATCH expected={expected} actual={actual}')

    saved_sources = [
        [origin.receipt_id, origin.issue_id, origin.tile_id, origin.revision_id]
        for origin in saved_report.origins
    ]
    downstream_expected = {
        'report_id': report.report_id,
        'confirmation_id': f'FIRST-{report.report_id}',
        'sources': expected_sources,
    }
    downstream_actual = {
        'report_id': saved_report.report_id,
        'confirmation_id': saved_receipt.confirmation_id,
        'sources': saved_sources,
    }
    if saved_pair != pair or downstream_actual != downstream_expected or receipt.origins != report.origins:
        raise RuntimeError('the center did not retain the signed report and its original sources')
    record = {
        'case_id': case_id,
        'input': {'round_id': ROUND, 'shift_id': SHIFT, 'sources': expected_sources},
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': ['issue/publish.py', 'receipt/accept.py', 'review/topology.py',
                       'review/finalize.py', 'review/archive.py'],
        'oracle': '手算上下湿臂、两侧闭合与孤立湿格，出处按实际交来的固定修订核对',
    }
    print('POINTWISE_SCENARIO ' + json.dumps(record, ensure_ascii=False, sort_keys=True))


def main():
    with TemporaryDirectory(prefix='qingcha-') as temporary:
        directory = Path(temporary)
        west_path = directory / 'west.sqlite3'
        east_path = directory / 'east.sqlite3'
        center_path = directory / 'center.sqlite3'
        with closing(sqlite3.connect(center_path)) as center:
            ReceiptStore(center).ensure_schema()
            ReportStore(center).ensure_schema()
            with closing(sqlite3.connect(west_path)) as west, closing(sqlite3.connect(east_path)) as east:
                initialize_survey(west, 'west-station', [WEST_INITIAL])
                initialize_survey(east, 'east-station', [EAST_INITIAL])
                west_check = inspect(west, ROUND, 'west', 'a')
                east_check = inspect(east, ROUND, 'east', 'a')
                if (west_check.wet_regions, west_check.enclosed_dry_regions) != (2, 0):
                    raise RuntimeError('unexpected west tile review')
                if (east_check.wet_regions, east_check.enclosed_dry_regions) != (1, 0):
                    raise RuntimeError('unexpected east tile review')
                west_id, original_west = publish(west, round_id=ROUND, tile_id='west', revision_id='a')
                east_id, original_east = publish(east, round_id=ROUND, tile_id='east', revision_id='a')
                left = accept(center, ROUND, original_west)
                right = accept(center, ROUND, original_east)

            original = sign(center, ROUND, SHIFT, [right.receipt_id, left.receipt_id])
            left_only, _ = sign(center, ROUND, SHIFT, [left.receipt_id])
            if (left_only.wet_regions, left_only.enclosed_dry_regions) != (2, 0):
                raise RuntimeError('unexpected left-only counts')

            with closing(sqlite3.connect(west_path)) as west:
                ingest(west, *WEST_CORRECTION)
                replay = initialize_survey(west, 'west-station', [WEST_INITIAL])
                if replay.added or replay.conflicts or replay.reused != ((ROUND, 'west', 'a'),):
                    raise RuntimeError('bootstrap did not reuse the original seed')
                if publish(west, issue_id=west_id) != (west_id, original_west):
                    raise RuntimeError('original west issue changed after correction')
                correction_id, corrected_west = publish(west, round_id=ROUND, tile_id='west', revision_id='b')
            correction = accept(center, ROUND, corrected_west)
            revised = sign(center, ROUND, SHIFT, [correction.receipt_id, right.receipt_id])

        with closing(sqlite3.connect(center_path)) as center:
            original_saved = read(center, original[0].report_id)
            revised_saved = read(center, revised[0].report_id)
        scenario('enclosed_after_join', [2, 1], original, original_saved, [
            [left.receipt_id, west_id, 'west', 'a'], [right.receipt_id, east_id, 'east', 'a'],
        ])
        scenario('historical_read', [1, 0], revised, revised_saved, [
            [right.receipt_id, east_id, 'east', 'a'], [correction.receipt_id, correction_id, 'west', 'b'],
        ])


if __name__ == '__main__':
    main()
