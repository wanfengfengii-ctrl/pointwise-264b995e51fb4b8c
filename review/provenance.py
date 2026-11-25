from dataclasses import dataclass

from receipt.selection import ShiftSelection


@dataclass(frozen=True)
class ReportOrigin:
    receipt_id: int
    issue_id: str
    round_id: str
    tile_id: str
    revision_id: str


def snapshot_origin(selection: ShiftSelection) -> tuple[ReportOrigin, ...]:
    origins = []
    for received in selection.receipts:
        envelope = received.envelope
        origins.append(ReportOrigin(
            received.receipt_id, envelope.issue_id, envelope.round_id,
            envelope.tile_id, envelope.revision_id,
        ))
    return tuple(origins)
