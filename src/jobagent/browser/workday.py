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
            // Live Workday serves these WITHOUT data-automation-id, so every
            // selector came back empty and nothing could be filled. Stamp our
            // own attribute instead: it always exists because we just made it.
            const handle = 'jf' + (i++);
            el.setAttribute('data-jobagent', handle);
            const req = el.required || el.getAttribute('aria-required') === 'true';
            const isWidget = el.tagName === 'BUTTON' ||
                             el.getAttribute('role') === 'combobox' ||
                             el.getAttribute('role') === 'listbox';
            let kind = 'text';
            if (el.tagName === 'SELECT') kind = 'select';
            else if (isWidget) kind = 'dropdown';
            else if (el.type) kind = el.type;
            // A custom widget shows its choice as text, not as .value
            const shown = el.value || (isWidget ? (el.innerText || '').trim() : '');
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
    """Pick `wanted` in a Workday combobox, or report why not.

    Click to open, type to filter, then CLICK the option whose text matches.
    Deliberately never presses Enter: in some forms Enter submits, and this
    tool must have no path that can submit an application.

    Always verifies afterwards by reading the widget back. A dropdown left
    showing the wrong country is the exact failure this is meant to fix, so
    "I clicked something" is not good enough — it has to end up right.
    """
    try:
        await page.click(selector, timeout=4000)
        await page.wait_for_timeout(250)
        # Type into whatever now has focus; Workday moves focus into a
        # filter input when the widget opens.
        await page.keyboard.type(wanted, delay=25)
        await page.wait_for_timeout(600)

        options = page.locator('[role="option"]')
        count = await options.count()
        target = None
        for index in range(min(count, 25)):
            option = options.nth(index)
            text = ((await option.inner_text()) or "").strip()
            if text.lower() == wanted.lower():
                target = option
                break
        if target is None:
            await page.keyboard.press("Escape")
            return False, f"no option exactly matching {wanted!r} among {count} shown"

        await target.click(timeout=4000)
        await page.wait_for_timeout(400)

        shown = (await page.locator(selector).inner_text() or "").strip()
        if wanted.lower() in shown.lower():
            return True, shown
        return False, f"clicked it but the widget still shows {shown!r}"
    except Exception as exc:  # noqa: BLE001 - report, never abort the run
        try:
            await page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
        return False, f"{type(exc).__name__} while selecting"


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
            shown_now = (field.get("current_value") or "").strip()
            if selector and answer.answer.lower() not in shown_now.lower():
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
            filled.append((label, answer.answer))
        except Exception as exc:  # noqa: BLE001 - report, never abort the run
            skipped.append((label, f"could not fill: {type(exc).__name__}"))

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
