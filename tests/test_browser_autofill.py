"""Autofill safety rules, tested without a browser.

The browser half is exercised by hand against a real form; these lock down
the decisions that must never regress — what gets skipped, and why.
"""

from jobagent.answers.form import FilledField, Outcome
from jobagent.browser.workday import _looks_like_password, apply_answers


class _FakePage:
    """Records fill() calls instead of touching a browser."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.filled: list[tuple[str, str]] = []
        self.fail_on = fail_on

    async def fill(self, selector: str, value: str) -> None:
        if self.fail_on and self.fail_on in selector:
            raise RuntimeError("detached")
        self.filled.append((selector, value))


def _field(label, kind="text", value="", selector=None, required=False):
    return {
        "label": label,
        "kind": kind,
        "current_value": value,
        "selector": selector if selector is not None else f"[data-automation-id={label}]",
        "required": required,
    }


def _answer(label, outcome=Outcome.ANSWERED, answer="X"):
    return FilledField(label=label, outcome=outcome, answer=answer)


async def _run(fields, answers, page=None):
    page = page or _FakePage()
    report = await apply_answers(page, fields, answers)
    return page, report


def test_password_fields_are_never_filled():
    import asyncio

    page, report = asyncio.run(
        _run([_field("Password", kind="password")], [_answer("Password", answer="hunter2")])
    )
    assert page.filled == []
    assert "password" in report["skipped"][0][1]
    assert _looks_like_password("Confirm Password", "text")
    assert _looks_like_password("anything", "password")


def test_sensitive_and_unknown_answers_are_not_typed():
    import asyncio

    fields = [_field("Date of Birth"), _field("Years of Terraform")]
    answers = [
        _answer("Date of Birth", Outcome.REFUSED, ""),
        _answer("Years of Terraform", Outcome.UNKNOWN, ""),
    ]
    page, report = asyncio.run(_run(fields, answers))
    assert page.filled == []
    assert len(report["skipped"]) == 2


def test_a_field_the_user_already_filled_is_left_alone():
    import asyncio

    page, report = asyncio.run(
        _run([_field("City", value="Medellin")], [_answer("City", answer="Bogota")])
    )
    assert page.filled == []
    assert "already filled" in report["skipped"][0][1]


def test_dropdowns_and_uploads_are_left_to_the_user():
    import asyncio

    fields = [_field("Country", kind="select"), _field("Resume", kind="file")]
    answers = [_answer("Country", answer="Colombia"), _answer("Resume", answer="x.pdf")]
    page, report = asyncio.run(_run(fields, answers))
    assert page.filled == []
    assert len(report["skipped"]) == 2


def test_required_marker_on_the_page_label_still_matches_the_answer():
    """The page says "First Name*" while the answer is keyed "First Name".
    Matching raw against cleaned missed every required field."""
    import asyncio

    page, report = asyncio.run(
        _run([_field("First Name*", required=True)], [_answer("First Name", answer="Andres")])
    )
    assert report["filled"] == [("First Name*", "Andres")]
    assert page.filled[0][1] == "Andres"


def test_one_broken_field_does_not_abort_the_rest():
    import asyncio

    fields = [_field("A"), _field("B")]
    answers = [_answer("A", answer="1"), _answer("B", answer="2")]
    page, report = asyncio.run(_run(fields, answers, _FakePage(fail_on="A")))
    assert [v for _, v in report["filled"]] == ["2"]
    assert any("could not fill" in why for _, why in report["skipped"])
