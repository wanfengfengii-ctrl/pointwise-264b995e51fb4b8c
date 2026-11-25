import sqlite3

from issue.archive import IssueArchive
from issue.comparison import InvalidComparison, build_comparison
from issue.comparison_store import ComparisonArchive
from issue.envelope import InvalidEnvelope, decode_v1
from issue.evidence import build_evidence
from survey.grid import valid_identifier
from survey.revisions import RevisionNotFound, get_revision
from survey.validation import InvalidGrid, validate_grid


class PublicationError(ValueError):
    pass


def publish(
    db: sqlite3.Connection,
    *,
    round_id: str | None = None,
    tile_id: str | None = None,
    revision_id: str | None = None,
    issue_id: str | None = None,
) -> tuple[str, bytes]:
    archive = IssueArchive(db)
    key = (round_id, tile_id, revision_id)
    try:
        if issue_id is not None:
            if any(part is not None for part in key) or not valid_identifier(issue_id):
                raise PublicationError('reissue requires only a valid issue_id')
            original = archive.get_original(issue_id)
            if original is None:
                raise PublicationError(f'unknown issue {issue_id!r}')
            return issue_id, original

        revision = get_revision(db, *key)
        if revision.cells != validate_grid(revision.bounds, revision.cells):
            raise InvalidGrid('stored survey grid is not in canonical form')
        evidence = build_evidence(revision)
        return archive.commit_issue(*revision.key, revision.bounds, evidence)
    except PublicationError:
        raise
    except (RevisionNotFound, ValueError, TypeError, sqlite3.Error) as exc:
        raise PublicationError(str(exc)) from exc


def _load_issue_original(archive: IssueArchive, issue_id: str) -> bytes:
    if not valid_identifier(issue_id):
        raise PublicationError(f'invalid issue id {issue_id!r}')
    original = archive.get_original(issue_id)
    if original is None:
        raise PublicationError(f'unknown issue {issue_id!r}')
    return original


def publish_comparison(
    db: sqlite3.Connection, old_issue_id: str, new_issue_id: str
) -> tuple[str, bytes]:
    try:
        issue_archive = IssueArchive(db)
        station_row = db.execute(
            'SELECT station FROM issue_station WHERE singleton = 1'
        ).fetchone()
        if station_row is None:
            raise PublicationError('station issuance namespace has not been initialized')
        station = station_row[0]

        old_original = _load_issue_original(issue_archive, old_issue_id)
        new_original = _load_issue_original(issue_archive, new_issue_id)
        old_envelope = decode_v1(old_original)
        new_envelope = decode_v1(new_original)
        if old_envelope.round_id == new_envelope.round_id:
            raise PublicationError('comparison requires issues from different survey rounds')
        if old_envelope.bounds != new_envelope.bounds:
            raise PublicationError('comparison requires identical rectangular bounds')

        old_revision = get_revision(
            db, old_envelope.round_id, old_envelope.tile_id, old_envelope.revision_id
        )
        new_revision = get_revision(
            db, new_envelope.round_id, new_envelope.tile_id, new_envelope.revision_id
        )
        if old_revision.bounds != old_envelope.bounds or new_revision.bounds != new_envelope.bounds:
            raise PublicationError('stored revision bounds do not back the issued original')

        comparison = build_comparison(
            '', old_revision, new_revision, old_original, new_original
        )
        comparison_archive = ComparisonArchive(db)
        comparison_archive.ensure_schema()
        return comparison_archive.commit_comparison(
            station, old_issue_id, new_issue_id, comparison
        )
    except PublicationError:
        raise
    except (InvalidComparison, InvalidEnvelope, RevisionNotFound, ValueError, TypeError,
            sqlite3.Error) as exc:
        raise PublicationError(str(exc)) from exc
