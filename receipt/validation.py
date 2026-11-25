from issue.envelope import InvalidEnvelope, V1Envelope, decode_v1
from survey.grid import valid_identifier


class InvalidIncomingTile(ValueError):
    pass


def validate_incoming(expected_round: str, original: bytes) -> V1Envelope:
    if not valid_identifier(expected_round):
        raise InvalidIncomingTile('invalid expected survey round')
    try:
        envelope = decode_v1(original)
    except InvalidEnvelope as exc:
        raise InvalidIncomingTile(str(exc)) from exc
    if envelope.round_id != expected_round:
        raise InvalidIncomingTile(f'expected survey round {expected_round!r}, got {envelope.round_id!r}')
    return envelope
