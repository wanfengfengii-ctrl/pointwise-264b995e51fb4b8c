import argparse
import json
import sqlite3
from contextlib import ExitStack, closing
from pathlib import Path
from tempfile import TemporaryDirectory

from issue.envelope import decode_v1
from issue.publish import publish
from receipt.accept import accept
from receipt.store import ReceiptStore
from review.archive import read
from review.finalize import sign
from review.report_store import ReportStore
from survey.bootstrap import initialize_survey
from survey.grid import GridBounds


def wet_ring(x0, y0, x1, y1):
    box = GridBounds(x0, y0, x1, y1)
    return frozenset(box.perimeter_coordinates())


def scene(name):
    if name == "move":
        original = wet_ring(1, 1, 3, 3)
        return {"west": GridBounds(0, 0, 8, 4)}, {
            "old": original, "kept": original, "moved": wet_ring(5, 1, 7, 3),
        }
    if name == "seam":
        original = wet_ring(1, 1, 8, 5)
        return {"west": GridBounds(0, 0, 4, 6), "east": GridBounds(5, 0, 9, 6)}, {
            "old": original,
            "kept": original,
            "split": original | {(4, y) for y in range(2, 5)},
            "opened": original - {(2, 1)},
            "horizontal": original | {(x, 3) for x in range(2, 8)},
        }
    raise ValueError(f"unknown sample {name!r}")


def prepare(center, stations, name):
    boxes, pictures = scene(name)
    if stations.keys() != boxes.keys():
        raise ValueError("station connections must match sample tiles")
    ReceiptStore(center).ensure_schema()
    ReportStore(center).ensure_schema()
    for tile, box in boxes.items():
        seeds = []
        for round_id, wet in pictures.items():
            cells = [(x, y, "wet" if (x, y) in wet else "dry") for x, y in box.coordinates()]
            seeds.append((round_id, tile, "frozen", box, cells))
        result = initialize_survey(stations[tile], tile, seeds)
        if result.conflicts:
            raise RuntimeError(result.conflicts)

    report_ids, issues = {}, {}
    for round_id in pictures:
        selected = []
        for tile, station in stations.items():
            issue_id, original = publish(station, round_id=round_id, tile_id=tile, revision_id="frozen")
            issues[round_id, tile] = (issue_id, original)
            selected.append(accept(center, round_id, original).receipt_id)
        report, _ = sign(center, round_id, "dispatch", selected)
        report_ids[round_id] = report.report_id
    return report_ids, issues


def check_scene(name, directory=None):
    def connect(role):
        path = ":memory:" if directory is None else directory / f"{name}-{role}.sqlite3"
        return sqlite3.connect(path)

    boxes, _ = scene(name)
    with closing(connect("center")) as center:
        with ExitStack() as active:
            stations = {tile: active.enter_context(closing(connect(tile))) for tile in boxes}
            report_ids, issues = prepare(center, stations, name)
        signed = {label: read(center, report_id) for label, report_id in report_ids.items()}
    if directory is not None:
        with closing(connect("center")) as center:
            if {label: read(center, report_id) for label, report_id in report_ids.items()} != signed:
                raise RuntimeError("V1 reports changed on reopen")

    counts = {label: (pair[0].wet_regions, pair[0].enclosed_dry_regions) for label, pair in signed.items()}
    if name == "move":
        bodies = [decode_v1(original).body for _, original in issues.values()]
        if bodies[0] != bodies[1] or bodies[0] != bodies[2]:
            raise RuntimeError("expected identical V1 bodies for the three single tiles")
        expected = dict.fromkeys(report_ids, (1, 1))
    else:
        expected = {"old": (1, 1), "kept": (1, 1), "split": (1, 2), "opened": (1, 0), "horizontal": (1, 2)}
    if counts != expected:
        raise RuntimeError(f"unexpected V1 counts in {name}: {counts!r}")
    print(json.dumps({"scene": name, "v1_counts": counts}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description="Prepare and check the V1 inputs for the revisit examples")
    parser.add_argument("--disk", action="store_true", help="use separate temporary databases and reopen the center")
    args = parser.parse_args()
    if args.disk:
        with TemporaryDirectory(prefix="revisit-sample-") as temporary:
            for name in ("move", "seam"):
                check_scene(name, Path(temporary))
    else:
        for name in ("move", "seam"):
            check_scene(name)


if __name__ == "__main__":
    main()
