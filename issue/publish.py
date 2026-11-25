import sqlite3

from issue.archive import IssueArchive
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
