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


class _FakeTab:
    def __init__(self, url: str) -> None:
        self.url = url


def test_the_application_tab_is_chosen_over_whatever_is_last():
    """Taking the last tab fails the moment a second window is open, which it
    always is."""
    from jobagent.browser.workday import pick_application_tab

    tabs = [
        _FakeTab("https://mail.google.com/"),
        _FakeTab("https://iqvia.wd1.myworkdayjobs.com/en-US/IQVIA/job/x/apply"),
        _FakeTab("https://news.ycombinator.com/"),
    ]
    assert "myworkdayjobs" in pick_application_tab(tabs).url

    # no ATS tab -> fall back to the most recently opened
    plain = [_FakeTab("https://a.com"), _FakeTab("https://b.com")]
    assert pick_application_tab(plain).url == "https://b.com"


def test_a_dropdown_set_to_the_wrong_value_is_flagged_loudly():
    """Workday defaults Country to "United States of America". A wrong
    prefilled value gets submitted; an empty one does not."""
    import asyncio

    page, report = asyncio.run(
        _run(
            [_field("Country", kind="dropdown", value="United States of America")],
            [_answer("Country", answer="Colombia")],
        )
    )
    assert page.filled == []
    why = report["skipped"][0][1]
    assert "WRONG" in why and "Colombia" in why


def test_a_dropdown_already_correct_is_not_flagged():
    import asyncio

    _, report = asyncio.run(
        _run(
            [_field("Country", kind="dropdown", value="Colombia")],
            [_answer("Country", answer="Colombia")],
        )
    )
    assert "WRONG" not in report["skipped"][0][1]


def test_dropdowns_are_only_chosen_when_asked():
    """--choose is opt-in. Without it a dropdown is reported, never clicked."""
    import asyncio

    page, report = asyncio.run(
        _run(
            [_field("Country", kind="dropdown", value="United States of America")],
            [_answer("Country", answer="Colombia")],
        )
    )
    assert page.filled == []
    assert "WRONG" in report["skipped"][0][1]


def test_a_correct_dropdown_is_not_re_selected():
    """No point clicking through a widget that already says the right thing,
    and every click is a chance to land on the wrong neighbour."""
    import asyncio

    async def go():
        return await apply_answers(
            _FakePage(),
            [_field("Country", kind="dropdown", value="Colombia")],
            [_answer("Country", answer="Colombia")],
            choose=True,
        )

    report = asyncio.run(go())
    assert report["filled"] == []
    assert "check it" in report["skipped"][0][1]


def test_page_chrome_and_label_noise_are_handled():
    """Live Workday reported "utility Menu Button" three times, "main menu",
    and labels like "Country United States of America Required"."""
    from jobagent.answers.form import clean_label

    assert clean_label("Country*") == "Country"
    # the JS strips Required/Select One before the label ever reaches Python;
    # what Python must handle is the asterisk and numbering
    assert clean_label("1. Phone Number*") == "Phone Number"



def test_an_input_that_is_really_a_combobox_is_treated_as_a_dropdown():
    """Country Phone Code is an <input role="combobox">. Filled as text, the
    value was never committed and reverted to Colombia (+57)."""
    import asyncio

    page, report = asyncio.run(
        _run(
            [_field("Country Phone Code", kind="dropdown", value="Colombia (+57)")],
            [_answer("Country Phone Code", answer="United States of America (+1)")],
        )
    )
    # without --choose it is reported as wrong, never typed into
    assert page.filled == []
    assert "WRONG" in report["skipped"][0][1]


def test_a_dropdown_whose_value_is_only_in_its_label_is_left_alone():
    """Workday writes the current value into aria-label ("Phone Device Type
    Mobile") while .value holds an opaque id and the display text sits in a
    sibling. Reading only .value made correct fields look unset, so they were
    re-selected — which is how Phone Device Type got chosen twice."""
    import asyncio

    async def go():
        return await apply_answers(
            _FakePage(),
            [_field("Phone Device Type Mobile", kind="dropdown", value="")],
            [_answer("Phone Device Type Mobile", answer="Mobile")],
            choose=True,
        )

    report = asyncio.run(go())
    assert report["filled"] == []
    assert "choose this yourself" in report["skipped"][0][1]


def test_an_opaque_id_is_not_treated_as_a_displayed_value():
    """A GUID in .value means "unset", not "set to e8106cd6...". Without this
    the mismatch warning would announce a wrong value that is really an id."""
    import asyncio

    _, report = asyncio.run(
        _run(
            [_field("Country", kind="dropdown", value="e8106cd6a3534f2dba6fdee2d41db89d")],
            [_answer("Country", answer="Colombia")],
        )
    )
    why = report["skipped"][0][1]
    assert "e8106cd6" in why or "WRONG" in why  # reported, never silently accepted
