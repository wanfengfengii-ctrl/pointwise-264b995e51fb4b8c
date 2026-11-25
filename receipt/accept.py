import sqlite3

from receipt.store import ReceiptConflict, ReceiptStore, ReceivedTile
from receipt.validation import InvalidIncomingTile, validate_incoming


class ReceiptRejected(ValueError):
    pass


def accept(db: sqlite3.Connection, expected_round: str, original: bytes) -> ReceivedTile:
    try:
        envelope = validate_incoming(expected_round, original)
        return ReceiptStore(db).register(envelope, original)
    except (InvalidIncomingTile, ReceiptConflict, sqlite3.Error) as exc:
        raise ReceiptRejected(str(exc)) from exc
