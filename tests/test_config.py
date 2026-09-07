import pytest

from jobagent.config import load_profile
from jobagent.models.profile import Profile


def test_load_profile_ok(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(
        "name: Test\ntarget_roles:\n  - Data Analyst\nskills:\n  - SQL\n",
        encoding="utf-8",
    )
    profile = load_profile(p)
    assert isinstance(profile, Profile)
    assert profile.target_roles == ["Data Analyst"]


def test_load_profile_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_profile(tmp_path / "nope.yaml")
