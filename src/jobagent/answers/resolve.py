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

from jobagent.models.profile import Contact, Profile

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
# "Do you CURRENTLY live there" is a factual question, not the address field.
_RESIDENCE = re.compile(
    r"(currently (reside|live|located|based)|do you (reside|live)\b|"
    r"country of residence|are you based|resides? in|actualmente (vives|resides))",
    re.I,
)
_CONTACT_FIELDS = (
    (re.compile(r"\b(e-?mail|correo)\b", re.I), "email"),
    (re.compile(r"\b(phone|tel[eé]fono|mobile|cell)\b", re.I), "phone"),
    (re.compile(r"\blinkedin\b", re.I), "linkedin"),
    (re.compile(r"\b(github|portfolio|personal website)\b", re.I), "github"),
    (re.compile(r"\b(postal|zip)\s*code\b|c[oó]digo postal", re.I), "postal_code"),
    (re.compile(r"\b(city|ciudad)\b", re.I), "city"),
    (re.compile(r"\b(state|province|region|departamento)\b", re.I), "region"),
    (re.compile(r"\b(country|pa[ií]s)\b", re.I), "country"),
    # Workday splits the address across fields, so "Address Line 1" must get
    # the street alone — not the whole thing with city and country repeated.
    (re.compile(r"\baddress\s*line\s*1?\b|\bstreet\b|\bdirecci[oó]n\b", re.I), "address_line"),
    (re.compile(r"\b(address|domicilio)\b", re.I), "full_address"),
    (re.compile(r"\b(first|given)\s*name\b|\bnombres?\b", re.I), "first_name"),
    (re.compile(r"\b(last|family|sur)\s*name\b|\bapellidos?\b", re.I), "last_name"),
    (re.compile(r"\b(full name|nombre completo|your name|legal name)\b", re.I), "full_name"),
)


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


def resolve(
    question: str, profile: Profile, contact: Contact | None = None
) -> ResolvedAnswer | None:
    """Answer from the profile and contact details, or None if unknowable.

    Order matters and is the whole design. Every SEMANTIC question is checked
    before the generic contact-field keywords, because those keywords are
    substrings of real questions: "do you require sponsorship to work in this
    country" contains "country", and once answered "Colombia" — a nonsense
    reply to an important question.
    """
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

    if _RESIDENCE.search(question):
        if contact is None:
            return None
        if contact.currently_resides_in_colombia:
            return ResolvedAnswer(
                answer=f"{contact.city}, {contact.country}", source="contact"
            )
        return ResolvedAnswer(
            answer=contact.relocation_note or "Not currently resident; relocating.",
            source="contact.relocation_note",
            confident=False,
        )

    if _RELOCATE.search(question):
        cities = ", ".join(profile.locations.preferred_cities) or "Colombia"
        if contact is not None and not contact.currently_resides_in_colombia:
            return ResolvedAnswer(
                answer=(
                    f"Yes — already relocating to {contact.city}. "
                    f"Prefers {cities}. Open to remote."
                ),
                source="contact.relocation_note",
                confident=False,
            )
        return ResolvedAnswer(
            answer=f"Based in Colombia; prefers {cities}. Open to remote.",
            source="profile.locations",
            confident=False,
        )

    if contact is not None:
        for pattern, field in _CONTACT_FIELDS:
            if pattern.search(question):
                value = getattr(contact, field)
                if value:
                    return ResolvedAnswer(answer=str(value), source=f"contact.{field}")

    return None
