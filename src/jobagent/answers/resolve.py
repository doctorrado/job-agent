"""Answer an application-form question from what is already known.

The point of Phase 5's answer bank is that forms ask the same things over and
over. This is the lookup side: given a question, say what the answer is and
where it came from, or say honestly that it is not known.

Three sources, in order of authority:
  1. the bank      — a question Andres has actually answered before
  2. the profile   — years per technology, salary floor, work authorization
  3. nothing       — ask him; never guess

Sensitive and demographic questions are refused outright, the same as in the
bank itself. CLAUDE.md forbids auto-answering them, and a resolver that
declined to store them but happily answered them would defeat the point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jobagent.models.profile import Profile

_YEARS_QUESTION = re.compile(
    r"(how many years|years of|years'? experience|a[nñ]os de experiencia|"
    r"cu[aá]ntos a[nñ]os)",
    re.I,
)
_SPONSORSHIP = re.compile(
    r"(sponsor\w*|visa|work permit|right to work|authorized to work|"
    r"work authorization|requiere patrocinio)",
    re.I,
)
_SALARY = re.compile(
    r"(salary expectation|expected salary|desired salary|compensation "
    r"expectation|pretensi[oó]n salarial|aspiraci[oó]n salarial)",
    re.I,
)
_RELOCATE = re.compile(r"(relocat\w+|willing to move|disponibilidad para mudar)", re.I)


@dataclass(frozen=True)
class ResolvedAnswer:
    answer: str
    source: str
    confident: bool = True


def _mentioned_skill(question: str, profile: Profile) -> str | None:
    """The longest profile skill named in the question.

    Longest wins so "Microsoft SQL Server" is not answered with the years for
    plain "SQL" — a real risk given 65 overlapping skill names.
    """
    text = question.lower()
    hits = [s for s in profile.skills if re.search(rf"\b{re.escape(s.lower())}\b", text)]
    return max(hits, key=len) if hits else None


def resolve(question: str, profile: Profile) -> ResolvedAnswer | None:
    """Answer from the profile alone, or None if it cannot be known."""
    if _YEARS_QUESTION.search(question):
        skill = _mentioned_skill(question, profile)
        if skill is None:
            return None
        years = profile.skill_years.get(skill.lower())
        if years is None:
            # He HAS the skill — it is in the profile — but no duration is
            # recorded. Saying "0" would be a lie and guessing would be worse.
            return ResolvedAnswer(
                answer=f"{skill}: years not recorded in profile.yaml",
                source="profile (incomplete)",
                confident=False,
            )
        return ResolvedAnswer(
            answer=f"{years:g}", source=f"profile.skill_years[{skill.lower()}]"
        )

    if _SPONSORSHIP.search(question):
        authorized = profile.work_authorization.us_authorized
        return ResolvedAnswer(
            answer=(
                "No sponsorship needed for roles based in Colombia. "
                + ("Authorized to work in the US." if authorized else
                   "For US-based roles, sponsorship WOULD be required.")
            ),
            source="profile.work_authorization",
        )

    if _SALARY.search(question):
        target = profile.salary.target_monthly
        floor = profile.salary.minimum_monthly
        if target is None and floor is None:
            return None
        return ResolvedAnswer(
            answer=f"Target COP {target:,}/month; minimum COP {floor:,}/month"
            if target and floor
            else f"COP {(target or floor):,}/month",
            source="profile.salary",
        )

    if _RELOCATE.search(question):
        cities = ", ".join(profile.locations.preferred_cities) or "Colombia"
        return ResolvedAnswer(
            answer=f"Based in Colombia; prefers {cities}. Open to remote.",
            source="profile.locations",
            confident=False,
        )

    return None
