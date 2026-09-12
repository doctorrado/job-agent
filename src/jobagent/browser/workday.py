"""Fill an application form in Andres's own browser.

This attaches to a Chrome he has already started and logged into, rather than
launching its own. That matters three ways:

  * no credential handling — he is already signed in to the candidate account
  * it is his real browser and profile, not an automation-flavoured one
  * he keeps navigation and, crucially, the submit button

Nothing here clicks Submit, and nothing fills a field the answer layer marked
sensitive. On anything it cannot answer it stops and reports, rather than
guessing — a wrong answer on an application is worse than a blank one.

Workday is the primary target because it is ONE product: its DOM carries
`data-automation-id` attributes, so the same selectors work across every
employer's tenant.
"""

from __future__ import annotations

from dataclasses import dataclass

from jobagent.answers.form import FilledField, Outcome, clean_label

CDP_ENDPOINT = "http://localhost:9222"

# Workday marks its inputs with data-automation-id; other ATSes use plain
# labels. Both paths are tried, most specific first.
_FIELD_SELECTOR = (
    "input:not([type=hidden]):not([type=submit]):not([type=button]), "
    "textarea, select"
)

# Never typed into, whatever the answer layer says.
_NEVER_FILL = ("password", "creditcard", "ssn", "social security")


@dataclass
class PageField:
    label: str
    selector: str
    kind: str  # text | select | checkbox | radio | file
    required: bool
    current_value: str = ""


def _looks_like_password(label: str, kind: str) -> bool:
    lowered = label.lower()
    return kind == "password" or any(word in lowered for word in _NEVER_FILL)


async def read_fields(page) -> list[PageField]:
    """Every visible, fillable field on the current page, with its label.

    Label resolution is deliberately layered: Workday's own automation id,
    then aria-label, then a <label for>, then placeholder. Real forms use all
    four and a single strategy misses most of them.
    """
    return await page.evaluate(
        """
        () => {
          const out = [];
          const els = document.querySelectorAll(
            'input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select'
          );
          for (const el of els) {
            const r = el.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) continue;
            let label = '';
            const id = el.getAttribute('data-automation-id');
            if (el.getAttribute('aria-label')) label = el.getAttribute('aria-label');
            if (!label && el.labels && el.labels.length) label = el.labels[0].innerText;
            if (!label && el.getAttribute('placeholder')) label = el.getAttribute('placeholder');
            if (!label && id) label = id.replace(/([a-z])([A-Z])/g, '$1 $2');
            if (!label) continue;
            const req = el.required || el.getAttribute('aria-required') === 'true';
            out.push({
              label: label.trim().replace(/\\s+/g, ' '),
              selector: id ? `[data-automation-id="${id}"]` : '',
              kind: el.tagName === 'SELECT' ? 'select' : (el.type || 'text'),
              required: !!req,
              current_value: el.value || '',
              automationId: id || '',
            });
          }
          return out;
        }
        """
    )


async def apply_answers(page, fields: list[dict], answers: list[FilledField]) -> dict:
    """Type the answers we have into the fields we found.

    Returns a report rather than a boolean: which fields were filled, which
    were skipped and why. The skipped list is the useful half — it is exactly
    what Andres still has to do himself before submitting.
    """
    # Key on the CLEANED label both sides. A page label reads "First Name*"
    # while the answer is keyed "First Name", so matching raw against cleaned
    # silently missed every required field — the ones that matter most.
    by_label = {clean_label(a.label).lower(): a for a in answers}
    filled, skipped = [], []

    for field in fields:
        label = field["label"]
        answer = by_label.get(clean_label(label).lower())

        if _looks_like_password(label, field.get("kind", "")):
            skipped.append((label, "password field — never auto-filled"))
            continue
        if answer is None or answer.outcome is Outcome.UNKNOWN:
            skipped.append((label, "not known"))
            continue
        if answer.outcome is Outcome.REFUSED:
            skipped.append((label, "sensitive — answer this yourself"))
            continue
        if field.get("current_value"):
            skipped.append((label, "already filled in"))
            continue
        if field.get("kind") in ("select", "file", "checkbox", "radio"):
            # Dropdowns and uploads need a real choice, not a typed string.
            skipped.append((label, f"{field['kind']} — choose this yourself"))
            continue

        selector = field.get("selector") or ""
        if not selector:
            skipped.append((label, "no stable selector"))
            continue
        try:
            await page.fill(selector, answer.answer)
            filled.append((label, answer.answer))
        except Exception as exc:  # noqa: BLE001 - report, never abort the run
            skipped.append((label, f"could not fill: {type(exc).__name__}"))

    return {"filled": filled, "skipped": skipped}
