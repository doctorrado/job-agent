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

from jobagent.models.profile import Contact, History, Profile

_YEARS_QUESTION = re.compile(
    r"(how many years|years of|years'? experience|a[nñ]os de experiencia|"
    r"cu[aá]ntos a[nñ]os)",
    re.I,
)
_SPONSORSHIP = re.compile(
    r"(sponsor\w*|visa|work permit|right to work|authorized to work|"
    r"work authorization|requiere patrocinio|patrocinio|"
    # verbatim from IQVIA's Workday form, which asks it only in Spanish
    r"posibilidad para ser empleado|permiso para trabajar|"
    r"autorizaci[oó]n para trabajar)",
    re.I,
)
_PASSWORD_FIELD = re.compile(r"\b(password|contrase[ñn]a)\b", re.I)
_RESUME_FIELD = re.compile(r"(upload a file|resume|cv\b|curr[ií]culum|hoja de vida)", re.I)
_SKILLS_FIELD = re.compile(r"(type to add skills|list your skills|^skills?$|habilidades)", re.I)
_LEGAL_AGE = re.compile(r"(edad legal m[ií]nima|legal(ly)? (minimum )?age|of legal age)", re.I)
_HISTORY_FIELDS = (
    (re.compile(r"\b(job title|puesto|cargo)\b", re.I), "employment", "job_title"),
    (re.compile(r"\b(company|employer|empresa)\b", re.I), "employment", "company"),
    (re.compile(r"\brole description|responsibilities\b", re.I), "employment", "description"),
    (re.compile(r"^\s*location\s*$|work location", re.I), "employment", "location"),
    (re.compile(r"^\s*from\s*$|start date|fecha de inicio", re.I), "employment", "start"),
    (re.compile(r"^\s*to\s*$|end date|fecha de fin", re.I), "employment", "end"),
    (re.compile(r"\bschool or university\b|\buniversity\b|\bschool\b|universidad", re.I),
     "education", "school"),
    (re.compile(r"\bfield of study\b|[aá]rea de estudio", re.I), "education", "field_of_study"),
    (re.compile(r"\bdegree\b|t[ií]tulo", re.I), "education", "degree"),
    (re.compile(r"\bgpa\b|promedio", re.I), "education", "gpa"),
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
    # Order matters: "Phone Extension" and "Country Phone Code" both contain
    # "phone", and a generic match put the full number into all three boxes.
    (re.compile(r"\b(extension|ext\.?)\b", re.I), "__skip__"),
    (re.compile(r"country\s*phone\s*code|c[oó]digo de pa[ií]s", re.I), "phone_country_code"),
    # Workday splits the dialling code into its own box, so a field named
    # "Phone Number" wants the national part only.
    (re.compile(r"phone\s*number|n[uú]mero de tel[eé]fono", re.I), "phone_national"),
    (re.compile(r"\b(phone|tel[eé]fono|mobile|cell)\b", re.I), "phone"),
    (re.compile(r"\blinkedin\b", re.I), "linkedin"),
    (re.compile(r"\b(github|portfolio|personal website)\b", re.I), "github"),
    (re.compile(r"\b(postal|zip)\s*code\b|c[oó]digo postal", re.I), "postal_code"),
    (re.compile(r"\b(city|ciudad)\b", re.I), "city"),
    (re.compile(r"\b(state|province|region|departamento)\b", re.I), "region"),
    (re.compile(r"\b(country|pa[ií]s)\b", re.I), "country"),
    # Workday splits the address across fields, so "Address Line 1" must get
    # the street alone — not the whole thing with city and country repeated.
    # "address line 1?" also matched "Address Line 2", which put his street
    # address into the second line as well. The 1 is now required, and line 2
    # is explicitly nothing — he has no second line.
    (re.compile(r"\baddress\s*line\s*2\b", re.I), "__skip__"),
    (re.compile(r"\baddress\s*line\s*1\b|\bstreet\b|\bdirecci[oó]n\b", re.I), "address_line"),
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
    question: str,
    profile: Profile,
    contact: Contact | None = None,
    history: History | None = None,
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

    if _PASSWORD_FIELD.search(question):
        # Deliberately not printed. The value belongs in .env; echoing it puts
        # a reusable credential into terminal scrollback that gets pasted into
        # chats. Pointing at it is as helpful as printing it.
        return ResolvedAnswer(
            answer="use APPLICATION_PASSWORD from .env (not printed here)",
            source=".env",
            confident=False,
        )

    if _RESUME_FIELD.search(question):
        return ResolvedAnswer(
            answer="attach the tailored resume from data/tailored/ "
            "(jobagent tailor --write generates it)",
            source="data/tailored",
            confident=False,
        )

    if _SKILLS_FIELD.search(question.strip()):
        if not profile.skills:
            return None
        return ResolvedAnswer(
            answer=", ".join(profile.skills),
            source=f"profile.skills ({len(profile.skills)})",
            # Workday's own guidance says to list only RELEVANT skills, so
            # dumping all 63 is a starting point to trim, not an answer.
            confident=False,
        )

    if _LEGAL_AGE.search(question):
        # Born 2002; of legal working age everywhere. Trivially true, and the
        # form makes it required.
        return ResolvedAnswer(answer="Yes / Sí", source="date of birth")

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

    if history is not None:
        for pattern, section, field in _HISTORY_FIELDS:
            if not pattern.search(question):
                continue
            entries = getattr(history, section)
            if not entries:
                continue
            value = getattr(entries[0], field)
            if value:
                return ResolvedAnswer(
                    answer=str(value).strip(),
                    source=f"history.{section}[0].{field}",
                    # Forms repeat these sections; entry 1 is only the first
                    # of several, so the answer is a starting point.
                    confident=len(entries) == 1,
                )

    if contact is not None:
        for pattern, field in _CONTACT_FIELDS:
            if pattern.search(question):
                if field == "__skip__":
                    return None  # deliberately has no answer
                value = getattr(contact, field)
                if value:
                    return ResolvedAnswer(answer=str(value), source=f"contact.{field}")

    return None
