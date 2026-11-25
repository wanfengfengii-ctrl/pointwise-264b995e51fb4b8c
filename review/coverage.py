from dataclasses import dataclass

from receipt.selection import ShiftSelection
from receipt.store import ReceivedTile
from survey.grid import GridBounds


class OverlappingTiles(ValueError):
    pass


@dataclass(frozen=True)
class SelectedCoverage:
    tiles: tuple[tuple[GridBounds, ReceivedTile], ...]

    def tile_at(self, x: int, y: int) -> ReceivedTile | None:
        for bounds, receipt in self.tiles:
            if bounds.contains(x, y):
                return receipt
        return None


def _shares_cell(left: GridBounds, right: GridBounds) -> bool:
    return (
        max(left.min_x, right.min_x) <= min(left.max_x, right.max_x)
        and max(left.min_y, right.min_y) <= min(left.max_y, right.max_y)
    )


def build_coverage(selection: ShiftSelection) -> SelectedCoverage:
    tiles = []
    for receipt in selection.receipts:
        bounds = receipt.envelope.bounds
        for other_bounds, other_receipt in tiles:
            if _shares_cell(bounds, other_bounds):
                raise OverlappingTiles(
                    f'receipts {other_receipt.receipt_id} and {receipt.receipt_id} share a grid cell'
                )
        tiles.append((bounds, receipt))
    return SelectedCoverage(tuple(tiles))
