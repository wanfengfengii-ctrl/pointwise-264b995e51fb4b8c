import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from issue.envelope import InvalidEnvelope
from receipt.store import ReceiptStore, ReceivedTile
from survey.grid import valid_identifier


class InvalidSelection(ValueError):
    pass


@dataclass(frozen=True)
class ShiftSelection:
    round_id: str
    shift_id: str
    receipts: tuple[ReceivedTile, ...]


def resolve_selection(
    db: sqlite3.Connection, round_id: str, shift_id: str, receipt_ids: Iterable[int]
) -> ShiftSelection:
    if not valid_identifier(round_id) or not valid_identifier(shift_id):
        raise InvalidSelection('invalid survey round or shift identity')
    try:
        requested = iter(receipt_ids)
    except TypeError as exc:
        raise InvalidSelection('expected an iterable of receipt IDs') from exc
    ids = set()
    for receipt_id in requested:
        if type(receipt_id) is not int or receipt_id <= 0:
            raise InvalidSelection(f'invalid receipt ID {receipt_id!r}')
        ids.add(receipt_id)

    store = ReceiptStore(db)
    receipts = []
    for receipt_id in sorted(ids):
        received = store.get(receipt_id)
        if received is None:
            raise InvalidSelection(f'unknown receipt {receipt_id}')
        try:
            delivered_round = received.envelope.round_id
        except InvalidEnvelope as exc:
            raise InvalidSelection(f'invalid archived receipt {receipt_id}') from exc
        if delivered_round != round_id:
            raise InvalidSelection(f'receipt {receipt_id} belongs to survey round {delivered_round!r}')
        receipts.append(received)
    return ShiftSelection(round_id, shift_id, tuple(receipts))
