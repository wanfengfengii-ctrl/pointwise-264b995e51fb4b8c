import hashlib
import json
from dataclasses import dataclass

from survey.grid import GridBounds, valid_identifier


class InvalidEnvelope(ValueError):
    pass


@dataclass(frozen=True)
class V1Envelope:
    issue_id: str
    round_id: str
    tile_id: str
    revision_id: str
    bounds: GridBounds
    body: dict


PAYLOAD_FIELDS = {'version', 'issue_id', 'round_id', 'tile_id', 'revision_id', 'bounds', 'body'}


def _json_text(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise InvalidEnvelope(f'duplicate JSON key {key!r}')
        obj[key] = value
    return obj


def _reject_constant(value: str) -> None:
    raise InvalidEnvelope(f'non-finite JSON constant {value!r}')


def _parse(value: str) -> object:
    return json.loads(
        value, object_pairs_hook=_object_without_duplicate_keys, parse_constant=_reject_constant
    )


def _validate_fields(envelope: V1Envelope) -> None:
    identifiers = (envelope.issue_id, envelope.round_id, envelope.tile_id, envelope.revision_id)
    if not all(valid_identifier(value) for value in identifiers):
        raise InvalidEnvelope('invalid issuance or source identity')
    if not isinstance(envelope.bounds, GridBounds) or not isinstance(envelope.body, dict):
        raise InvalidEnvelope('invalid bounds or payload body')


def encode_v1(envelope: V1Envelope) -> bytes:
    _validate_fields(envelope)
    try:
        text = _json_text({
            'version': 1,
            'issue_id': envelope.issue_id,
            'round_id': envelope.round_id,
            'tile_id': envelope.tile_id,
            'revision_id': envelope.revision_id,
            'bounds': envelope.bounds.as_tuple(),
            'body': envelope.body,
        })
    except (TypeError, ValueError, RecursionError) as exc:
        raise InvalidEnvelope('payload is not serializable as V1 JSON') from exc
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    return _json_text({'payload': text, 'digest': digest}).encode('utf-8')


def decode_v1(original: bytes) -> V1Envelope:
    if type(original) is not bytes:
        raise InvalidEnvelope('V1 input must be original bytes')
    try:
        wire = _parse(original.decode('utf-8'))
        if not isinstance(wire, dict) or wire.keys() != {'payload', 'digest'}:
            raise InvalidEnvelope('invalid V1 wrapper')
        text = wire['payload']
        if not isinstance(text, str):
            raise InvalidEnvelope('invalid V1 payload text')
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        if wire['digest'] != digest:
            raise InvalidEnvelope('V1 payload digest mismatch')
        data = _parse(text)
        if not isinstance(data, dict) or data.keys() != PAYLOAD_FIELDS:
            raise InvalidEnvelope('invalid V1 payload fields')
        if type(data['version']) is not int or data['version'] != 1:
            raise InvalidEnvelope('unsupported envelope version')
        coordinates = data['bounds']
        if not isinstance(coordinates, list) or len(coordinates) != 4:
            raise InvalidEnvelope('invalid V1 bounds')
        envelope = V1Envelope(
            data['issue_id'], data['round_id'], data['tile_id'], data['revision_id'],
            GridBounds(*coordinates), data['body'],
        )
        _validate_fields(envelope)
        return envelope
    except InvalidEnvelope:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise InvalidEnvelope('malformed V1 data') from exc
