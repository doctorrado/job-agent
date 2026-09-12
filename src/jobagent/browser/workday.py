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

import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from jobagent.answers.form import FilledField, Outcome, clean_label
from jobagent.pipeline.extract import strip_accents

CDP_ENDPOINT = "http://localhost:9222"
DEBUG_PORT = 9222

# A dedicated profile directory, not the everyday one. Chrome ignores
# --remote-debugging-port when an instance is ALREADY running on the same
# profile: the new process just hands the URL to the old one and exits, so
# nothing ever listens on the port. A separate --user-data-dir sidesteps that
# entirely, and because the directory persists, logging in to an ATS
# candidate account here is a one-time cost per employer.
DEBUG_PROFILE = Path.home() / ".jobagent-chrome"

_CHROME_CANDIDATES = (
    "/opt/google/chrome-canary/google-chrome-canary",
    "/opt/google/chrome/google-chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/brave-browser",
)


def find_chrome() -> str | None:
    """First Chrome-family browser present on this machine."""
    for candidate in _CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return shutil.which("google-chrome") or shutil.which("chromium")


def debug_port_is_open(port: int = DEBUG_PORT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.6)
        return probe.connect_ex(("127.0.0.1", port)) == 0

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


# Hosts that look like an application rather than a random tab.
_ATS_HOSTS = (
    "myworkdayjobs.com", "greenhouse.io", "lever.co", "ashbyhq.com",
    "smartrecruiters.com", "recruitee.com", "workable.com", "icims.com",
    "taleo.net", "successfactors.com", "oraclecloud.com",
)


def pick_application_tab(pages: list):
    """The tab most likely to BE the application.

    Taking the last tab was a guess that fails the moment a second window is
    open — which it always is. A tab on a known ATS host wins; otherwise the
    last one, which is usually the most recently opened.
    """
    for page in pages:
        if any(host in (page.url or "") for host in _ATS_HOSTS):
            return page
    return pages[-1]


async def describe_fields(page) -> list[dict]:
    """Raw markup of every field, for when detection is guessing wrong.

    Four rounds were spent inferring how Workday marks a combobox. This
    prints what the element actually is instead.
    """
    script = """
      () => Array.from(document.querySelectorAll(
        'input:not([type=hidden]), textarea, select, [role], button'
      )).filter(el => {
        const r = el.getBoundingClientRect();
        return r.width > 0 || r.height > 0;
      }).map(el => ({
        tag: el.tagName.toLowerCase(),
        type: el.type || '',
        role: el.getAttribute('role') || '',
        label: ((el.getAttribute('aria-label') ||
                 (el.labels && el.labels[0] ? el.labels[0].innerText : '') ||
                 '')).trim().slice(0, 44),
        controls: (el.getAttribute('aria-controls') || '').slice(0, 18),
        activedesc: el.getAttribute('aria-activedescendant') ? 'y' : '',
        haspopup: el.getAttribute('aria-haspopup') || '',
        expanded: el.getAttribute('aria-expanded') || '',
        autocomplete: el.getAttribute('aria-autocomplete') || '',
        readonly: el.readOnly ? 'y' : '',
        automation: (el.getAttribute('data-automation-id') || '').slice(0, 30),
        value: (el.value || '').slice(0, 26),
      }))
    """
    out: list[dict] = []
    for frame in page.frames:
        try:
            out.extend(await frame.evaluate(script))
        except Exception:  # noqa: BLE001
            continue
    return out


async def read_fields(page) -> list[PageField]:
    """Every visible, fillable field on the current page, with its label.

    Label resolution is deliberately layered: Workday's own automation id,
    then aria-label, then a <label for>, then placeholder. Real forms use all
    four and a single strategy misses most of them.
    """
    script = """
        () => {
          const out = [];
          // Workday renders most "dropdowns" as custom widgets, not <select>,
          // so a plain input/select query misses them entirely — including
          // Country, which defaults to United States of America. A wrong
          // prefilled value is worse than an empty one: it gets submitted.
          const els = document.querySelectorAll(
            'input:not([type=hidden]):not([type=submit]):not([type=button]), ' +
            'textarea, select, [role=combobox], [role=listbox], ' +
            'button[aria-haspopup]'
          );
          let i = 0;
          for (const el of els) {
            const r = el.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) continue;
            let label = '';
            const autoId = el.getAttribute('data-automation-id');
            if (el.getAttribute('aria-label')) label = el.getAttribute('aria-label');
            if (!label && el.labels && el.labels.length) label = el.labels[0].innerText;
            if (!label && el.getAttribute('placeholder')) label = el.getAttribute('placeholder');
            if (!label && autoId) label = autoId.replace(/([a-z])([A-Z])/g, '$1 $2');
            if (!label) continue;
            // Page chrome, not form fields: the language picker, the account
            // menu, the nav. They showed up as "utility Menu Button" three
            // times and as "main menu".
            if (/^(utility menu|main menu|menu|search|skip to)/i.test(label)) continue;
            if (/^\\d*\\s*items? selected$/i.test(label)) continue;
            // Live Workday serves these WITHOUT data-automation-id, so every
            // selector came back empty and nothing could be filled. Stamp our
            // own attribute instead: it always exists because we just made it.
            const handle = 'jf' + (i++);
            el.setAttribute('data-jobagent', handle);
            const req = el.required || el.getAttribute('aria-required') === 'true';
            // Workday stuffs the current value and "Required" into aria-label:
            // "Country United States of America Required". Left alone, the
            // label never matches an answer and the value pollutes the match.
            label = label.replace(/\\s*Required\\s*$/i, '')
                         .replace(/\\s*Select One\\s*$/i, '')
                         .replace(/\\s*\\(required\\)\\s*$/i, '')
                         .trim();
            // An <input role="combobox"> IS a dropdown, however much it
            // looks like a text box. Country Phone Code is exactly that: text
            // typed into it is never committed, so it kept reverting to
            // Colombia (+57) after being "filled" with the right value.
            const role = el.getAttribute('role');
            const isWidget = el.tagName === 'BUTTON' ||
                             role === 'combobox' ||
                             role === 'listbox' ||
                             el.getAttribute('aria-haspopup') === 'listbox' ||
                             (el.getAttribute('aria-expanded') !== null);
            // NOT aria-autocomplete: City carries it on the real form and is
            // a plain text box that fills correctly. Treating it as a
            // dropdown would break a field that already works.
            let kind = 'text';
            if (el.tagName === 'SELECT') kind = 'select';
            else if (isWidget) kind = 'dropdown';
            else if (el.type) kind = el.type;
            // A checkbox/radio's .value is "on"/"true" whether or not it is
            // ticked; `checked` is the fact anyone cares about.
            // Workday keeps an internal option ID in .value on its
            // comboboxes — "e8106cd6a3534f2dba6fdee2d41db89d" — and shows the
            // real text elsewhere. Reading .value made every already-correct
            // dropdown look unset, so they were re-selected needlessly.
            const looksLikeId = v => /^[0-9a-f]{16,}$/i.test(v || '');
            let shown;
            if (el.type === 'checkbox' || el.type === 'radio') {
              shown = el.checked ? 'checked' : '';
            } else if (isWidget) {
              const text = (el.innerText || '').trim();
              shown = text || (looksLikeId(el.value) ? '' : (el.value || ''));
            } else {
              shown = el.value || '';
            }
            out.push({
              label: label.trim().replace(/\\s+/g, ' '),
              selector: '[data-jobagent="' + handle + '"]',
              kind: kind,
              required: !!req,
              current_value: shown.replace(/\\s+/g, ' ').slice(0, 80),
              automationId: autoId || '',
            });
          }
          return out;
        }
        """
    # Workday renders its form in the main document, but other ATSes use an
    # iframe. Searching every frame costs nothing and avoids "no fields found"
    # on a page that visibly has plenty.
    seen: list[dict] = []
    for frame in page.frames:
        try:
            found = await frame.evaluate(script)
        except Exception:  # noqa: BLE001 - a cross-origin frame is not an error
            continue
        for item in found:
            if item not in seen:
                seen.append(item)
    return seen


async def choose_option(page, selector: str, wanted: str) -> tuple[bool, str]:
    """Click the dropdown, type the value, press Enter. Then check it took.

    This is literally what Andres does by hand, and it works. Three earlier
    versions tried to be cleverer — scan the options, click the exact match,
    escalate to Enter only under guards — and all three failed on the real
    page, the last one reporting "1 option shown" where a browser shows 251.
    Workday's list is virtualised, so what is in the DOM at any moment is not
    what is on screen, and every strategy built on reading options was
    doomed. Typing filters it down; Enter takes the filtered result.

    The safety property is unchanged and does not depend on reading options:
    we type an EXACT value and then verify the widget ended up showing it. If
    it shows anything else, that is reported as a failure, not a success.
    """
    def matches(shown: str) -> bool:
        # Accent-insensitive: the form says "Bogotá", the file says "Bogota".
        return strip_accents(wanted).casefold() in strip_accents(shown).casefold()

    async def shown_value() -> str:
        """What the widget currently displays.

        An <input> keeps its value in `.value` and has NO inner text, while a
        div-based widget is the opposite. Reading only inner_text made this
        report failure on input-based comboboxes that had in fact been set
        correctly — the same shape of mistake as comparing accents literally.
        """
        try:
            return await page.evaluate(
                """
                (sel) => {
                  const el = document.querySelector(sel);
                  if (!el) return '';
                  const text = (el.innerText || '').trim();
                  const v = el.value || '';
                  // An opaque id is not a displayed value.
                  const isId = /^[0-9a-f]{16,}$/i.test(v);
                  return (text + ' ' + (isId ? '' : v)).trim();
                }
                """,
                selector,
            )
        except Exception:  # noqa: BLE001
            return ""

    # GUARD 1: the element must still be the one we read. Workday is a SPA
    # and re-renders constantly, so a stamped attribute can end up on a
    # different element — or gone — between reading and clicking.
    try:
        handle = page.locator(selector)
        if await handle.count() != 1:
            return False, "the field moved before it could be used — run again"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__} locating the field"

    try:
        await handle.click(timeout=5000)
        await page.wait_for_timeout(600)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__} opening the dropdown"

    # GUARD 2: never type or press Enter unless a dropdown actually opened.
    # Without this, a click that missed sent the keystrokes to whatever had
    # focus — and Enter on the account menu signed Andres out of Workday.
    opened = await page.evaluate(
        """
        (sel) => {
          const el = document.querySelector(sel);
          if (el && el.getAttribute('aria-expanded') === 'true') return true;
          const boxes = document.querySelectorAll('[role=listbox], [role=option]');
          for (const b of boxes) {
            const r = b.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) return true;
          }
          return false;
        }
        """,
        selector,
    )
    if not opened:
        return False, "the dropdown did not open — not typing, not pressing Enter"

    try:
        await page.keyboard.type(wanted, delay=60)
        await page.wait_for_timeout(900)
        # Enter, check, Enter again. Workday's multi-select comboboxes (the
        # ones that read "1 item selected") take one Enter to pick the
        # filtered option and another to close the list and commit it. Andres
        # suggested the second press after watching the first do nothing.
        # Bounded at two: it is already established that the list is open, so
        # these go to the listbox, but more presses would be guessing.
        for attempt in (1, 2):
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(900)
            if matches(await shown_value()):
                return True, f"{await shown_value()} (Enter x{attempt})"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__} while selecting"

    after = await shown_value()
    if matches(after):
        return True, after
    return False, f"typed {wanted!r} and pressed Enter, but it shows {after!r}"


async def apply_answers(
    page, fields: list[dict], answers: list[FilledField], choose: bool = False
) -> dict:
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
        # Kind first: a radio's label is its OPTION ("Yes"/"No"), never a
        # question, so reporting it as "not known" is noise rather than a
        # to-do. Say what it actually is.
        kind = field.get("kind", "")
        if kind in ("select", "dropdown") and choose and answer is not None \
                and answer.outcome is Outcome.ANSWERED:
            selector = field.get("selector") or ""
            # Two sources for "what does it say now". Workday writes the
            # current value into the aria-label ("Phone Device Type Mobile",
            # "Country Colombia"), which is often the ONLY readable copy: the
            # element's own .value is an opaque id and the display text can
            # live in a sibling node. Missing this re-selected fields that
            # were already correct.
            shown_now = " ".join(
                [(field.get("current_value") or ""), label]
            ).strip()
            if selector and strip_accents(answer.answer).casefold() \
                    not in strip_accents(shown_now).casefold():
                if kind == "select":
                    try:
                        await page.select_option(selector, label=answer.answer)
                        filled.append((label, answer.answer))
                        continue
                    except Exception:  # noqa: BLE001 - fall through to report
                        skipped.append((label, f"could not select {answer.answer!r}"))
                        continue
                ok, detail = await choose_option(page, selector, answer.answer)
                if ok:
                    filled.append((label, detail))
                else:
                    skipped.append((label, f"could not choose {answer.answer!r}: {detail}"))
                continue

        if kind in ("select", "file", "checkbox", "radio", "dropdown"):
            shown = (field.get("current_value") or "").strip()
            # The important case: a dropdown that is already set to something
            # WRONG. Workday defaults Country to United States of America, and
            # a wrong prefilled value gets submitted while an empty one does
            # not. Say so loudly rather than listing it as a neutral skip.
            if (
                answer is not None
                and answer.outcome is Outcome.ANSWERED
                and shown
                and answer.answer.lower() not in shown.lower()
            ):
                skipped.append(
                    (label, f"WRONG: shows {shown!r}, should be {answer.answer!r} — fix this")
                )
            elif shown:
                skipped.append((label, f"{kind}, currently {shown!r} — check it"))
            else:
                skipped.append((label, f"{kind} — choose this yourself"))
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

        selector = field.get("selector") or ""
        if not selector:
            skipped.append((label, "no stable selector"))
            continue
        try:
            await page.fill(selector, answer.answer)
        except Exception as exc:  # noqa: BLE001 - report, never abort the run
            skipped.append((label, f"could not fill: {type(exc).__name__}"))
            continue

        # Did it stick? Some Workday fields LOOK like text boxes and are
        # really comboboxes — Country Phone Code is a multi-select listbox
        # whose typed value is discarded unless it is committed. Four rounds
        # were spent trying to identify those from their markup; checking
        # whether the value survived is simpler and works whatever they are.
        stuck = await page.evaluate(
            "(sel) => { const el = document.querySelector(sel);"
            " return el ? (el.value || '') : ''; }",
            selector,
        )
        if strip_accents(answer.answer).casefold() in strip_accents(stuck).casefold():
            filled.append((label, answer.answer))
            continue
        if not choose:
            skipped.append((label, f"typed it but it did not stick (shows {stuck!r})"))
            continue
        ok, detail = await choose_option(page, selector, answer.answer)
        if ok:
            filled.append((label, detail))
        else:
            skipped.append((label, f"typed it, did not stick, and {detail}"))

    return {"filled": filled, "skipped": skipped}


def launch_debug_browser(port: int = DEBUG_PORT) -> tuple[bool, str]:
    """Start Chrome with debugging on, in its own profile. (started, message)"""
    if debug_port_is_open(port):
        return True, f"Chrome is already listening on port {port}."
    chrome = find_chrome()
    if chrome is None:
        return False, "No Chrome-family browser found on this machine."
    DEBUG_PROFILE.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            chrome,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={DEBUG_PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True, f"Started {Path(chrome).name} on port {port} (profile: {DEBUG_PROFILE})."
