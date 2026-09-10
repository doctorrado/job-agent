import pytest

from jobagent.storage.db import make_session_factory
from jobagent.storage.repository import ReviewRepository


def _repo(tmp_path):
    return ReviewRepository(make_session_factory(tmp_path / "test.db")())


def test_record_returns_true_for_a_new_verdict(tmp_path):
    reviews = _repo(tmp_path)
    assert reviews.record("linkedin_alerts", "123", "worth_applying", "on target") is True
    assert reviews.count() == 1


def test_a_job_is_never_reviewed_twice(tmp_path):
    reviews = _repo(tmp_path)
    reviews.record("linkedin_alerts", "123", "not_a_fit", "journalism role")
    # a second pass over the same posting must not overwrite or duplicate
    assert reviews.record("linkedin_alerts", "123", "worth_applying", "changed mind") is False
    assert reviews.count() == 1
    assert reviews.verdicts()["linkedin_alerts:123"] == "not_a_fit"


def test_verdicts_are_keyed_to_match_job_dedupe_key(tmp_path):
    reviews = _repo(tmp_path)
    reviews.record("greenhouse", "abc", "unsure", "maybe")
    assert reviews.verdicts() == {"greenhouse:abc": "unsure"}


def test_unknown_verdict_is_rejected(tmp_path):
    reviews = _repo(tmp_path)
    with pytest.raises(ValueError):
        reviews.record("greenhouse", "abc", "maybe_later")


def test_unimported_verdicts_are_detected(tmp_path):
    """A re-export silently wiped a completed 100-job review pass. The guard
    counts verdicts sitting in a file that never reached the database."""
    import json

    from jobagent.cli import _unimported_verdicts

    path = tmp_path / "batch.json"
    path.write_text(
        json.dumps(
            {
                "jobs": [
                    {"source": "greenhouse", "source_job_id": "1", "verdict": "worth_applying"},
                    {"source": "greenhouse", "source_job_id": "2", "verdict": "unsure"},
                    {"source": "greenhouse", "source_job_id": "3", "verdict": ""},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _unimported_verdicts(path, {}) == 2  # blanks don't count
    assert _unimported_verdicts(path, {"greenhouse:1": "worth_applying"}) == 1
    assert _unimported_verdicts(path, {"greenhouse:1": "x", "greenhouse:2": "y"}) == 0
    assert _unimported_verdicts(tmp_path / "missing.json", {}) == 0

    path.write_text("not json", encoding="utf-8")
    assert _unimported_verdicts(path, {}) == 0  # unreadable must not block
