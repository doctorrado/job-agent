"""Answer a whole application form at once.

The intelligence of Phase 7 is not clicking fields — it is knowing what to
type. That part needs no browser, so it is built and tested first: give it
the labels off a form and it returns an answer per label, with the source, or
says plainly that it does not know.

Three outcomes per field, and the distinction between the last two matters:
  ANSWERED   we know it, and where from
  UNKNOWN    nobody knows it yet — ask Andres, then bank it
  REFUSED    demographic or sensitive; never answered automatically
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from jobagent.answers.resolve import ResolvedAnswer, resolve
from jobagent.models.profile import Contact, Profile

# Form labels carry noise a banked question does not: a trailing colon, a
# required-field asterisk, "(optional)", stray numbering.
_LABEL_NOISE = re.compile(r"^\s*[\d.)\-•*]+\s*|\s*[*:]+\s*$|\(\s*optional\s*\)", re.I)


class Outcome(StrEnum):
    ANSWERED = "answered"
    UNKNOWN = "unknown"
    REFUSED = "refused"


@dataclass(frozen=True)
class FilledField:
    label: str
    outcome: Outcome
    answer: str = ""
    source: str = ""
    confident: bool = True


def clean_label(label: str) -> str:
    """Strip form chrome so a label matches a banked question."""
    return _LABEL_NOISE.sub("", label).strip()


def fill_form(
    labels: list[str],
    profile: Profile,
    contact: Contact | None = None,
    banked: dict[str, ResolvedAnswer] | None = None,
) -> list[FilledField]:
    """One answer per label, in the order the form asks them."""
    from jobagent.storage.repository import is_sensitive

    banked = banked or {}
    filled: list[FilledField] = []
    for raw in labels:
        label = clean_label(raw)
        if not label:
            continue
        if is_sensitive(label):
            filled.append(FilledField(label=label, outcome=Outcome.REFUSED))
            continue
        found = banked.get(label) or resolve(label, profile, contact)
        if found is None:
            filled.append(FilledField(label=label, outcome=Outcome.UNKNOWN))
            continue
        filled.append(
            FilledField(
                label=label,
                outcome=Outcome.ANSWERED,
                answer=found.answer,
                source=found.source,
                confident=found.confident,
            )
        )
    return filled
