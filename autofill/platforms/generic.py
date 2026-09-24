"""Generic form filler.

Works reasonably well on plain-HTML ATS forms (Greenhouse, Lever, and most
standalone company career-page forms). Does NOT click submit -- it fills
the form and stops so you can review before sending anything.
"""

from __future__ import annotations

from playwright.sync_api import Locator, Page
from rapidfuzz import fuzz

from ..field_matcher import best_match
from ..profile import Profile

# Runs in-page to find the best human-readable label for an input element,
# trying (in order): aria-label, aria-labelledby, <label for=id>, a wrapping
# <label>, placeholder text, then a nearby label-ish element in the DOM.
_LABEL_JS = r"""
(el) => {
    const clean = (s) => (s || "").replace(/\s+/g, " ").trim();

    if (el.getAttribute("aria-label")) return clean(el.getAttribute("aria-label"));

    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
        const parts = labelledBy.split(" ").map(id => document.getElementById(id));
        const text = parts.filter(Boolean).map(n => n.textContent).join(" ");
        if (clean(text)) return clean(text);
    }

    if (el.id) {
        const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
        if (lbl && clean(lbl.textContent)) return clean(lbl.textContent);
    }

    const parentLabel = el.closest("label");
    if (parentLabel && clean(parentLabel.textContent)) return clean(parentLabel.textContent);

    if (el.placeholder) return clean(el.placeholder);

    let node = el.closest("div, fieldset, li");
    for (let hops = 0; node && hops < 4; hops++, node = node.parentElement) {
        const candidate = node.querySelector("label, legend, .label, [class*='label']");
        if (candidate && clean(candidate.textContent)) return clean(candidate.textContent);
    }
    return "";
}
"""


def _is_typeahead_input(field: Locator) -> bool:
    """Greenhouse (and many other sites, via the popular react-select
    library) render some questions -- School, Degree -- as a text input
    that LOOKS fillable but actually needs a suggestion clicked from a
    dropdown to register; typing alone leaves the underlying form value
    unset. react-select's default generated class names are prefixed
    "select__" (select__input, select__input-container, ...), which is a
    reliable, library-level signal rather than a Greenhouse-specific hack.
    """
    try:
        return field.evaluate(
            "el => el.className.includes('select__') "
            "|| !!el.closest('[class*=\"select__\"]') "
            "|| el.getAttribute('role') === 'combobox' "
            "|| el.getAttribute('aria-autocomplete') !== null"
        )
    except Exception:
        return False


def _own_listbox_options(field: Locator):
    """The option list for a react-select instance isn't reliably reachable
    by searching the whole page/frame for `[role="option"]` -- if more than
    one such widget exists (e.g. a phone country-code picker elsewhere on
    the same form), that grabs a stale, unrelated instance's stale options
    instead. Its actual `[role="listbox"]` renders as a sibling within a
    shared ancestor a few hops up from the input, so walk up from the field
    itself and return the options scoped to the listbox found there.
    """
    try:
        handle = field.element_handle()
        if handle is None:
            return None
        listbox = handle.evaluate_handle(
            """el => {
                let node = el;
                for (let hops = 0; hops < 8; hops++) {
                    node = node.parentElement;
                    if (!node) return null;
                    const lb = node.querySelector('[role="listbox"]');
                    if (lb) return lb;
                }
                return null;
            }"""
        )
        el = listbox.as_element()
        return el.query_selector_all("[role='option']") if el else None
    except Exception:
        return None


def _fill_typeahead(
    page: Page, field: Locator, value: str, hint: str = "", extra_candidates: list[str] | None = None
) -> bool:
    """react-select-style widgets (Greenhouse's School/Degree, and similar
    on many other sites) don't register a real selection from `.fill()` --
    confirmed live: `.fill()` never even triggers their debounced search,
    while simulated keystrokes (`press_sequentially`) do. And searching with
    the full profile value often returns zero results (the backend does
    prefix/token matching against its own catalog, e.g. "Rutgers University"
    finds nothing while "Rutgers" alone surfaces "Rutgers, The State
    University of New Jersey - New Brunswick") -- so try the full value
    first, then fall back to just its first word, then any `extra_candidates`
    (e.g. a "Degree" field that's actually asking for degree *level* --
    "Bachelor's Degree" -- rather than your major finds nothing for "B.S.
    Computer Science...", but does for the level string as a fallback
    query). Clicks whichever returned option best fuzzy-matches the
    intended value (plus `hint`, if given --
    e.g. a multi-campus university's options can only be told apart by
    which one mentions the profile's city, since "Rutgers University" alone
    scores near-identically against every "Rutgers ... - <campus>" option).
    Returns whether a real selection was clicked; on failure the typed text
    is left in place (identical to the old behavior), so this can only
    help, never regress.
    """
    # Short, explicit timeouts throughout: this runs on every react-select-
    # classed field on a form (there can be a dozen), so one stuck field
    # must fail in ~seconds, not eat Playwright's default 30s-per-action
    # budget and stall the whole review queue.
    ACTION_TIMEOUT = 4000

    try:
        field.click(timeout=ACTION_TIMEOUT)
        field.fill("", timeout=ACTION_TIMEOUT)
    except Exception:
        return False

    # Each candidate carries its own scoring target: a shortened query
    # derived from `value` (the first-word fallback) is still searching for
    # the same entity, so options should score against the full `value`
    # (+hint) to keep e.g. the right campus winning. But an entry from
    # `extra_candidates` represents a different target entirely (a degree
    # *level* is not a shortened form of a major) -- scoring that against
    # the original `value` was the actual bug here: "Bachelor's Degree"
    # scores 35 against "B.S. Computer Science & ..." by character overlap
    # alone, well under threshold, even though it's exactly the right
    # answer to what was actually searched for.
    value_target = f"{value} {hint}".strip().lower() if hint else value.lower()
    candidates: list[tuple[str, str]] = [(value, value_target)]
    first_word = value.split()[0] if value.split() else ""
    if first_word and first_word.lower() != value.lower():
        candidates.append((first_word, value_target))
    seen = {value.lower(), first_word.lower()}
    for extra in extra_candidates or []:
        if extra and extra.lower() not in seen:
            candidates.append((extra, extra.lower()))
            seen.add(extra.lower())

    matched = False
    try:
        for query, score_target in candidates:
            field.fill("", timeout=ACTION_TIMEOUT)
            field.press_sequentially(query, delay=50, timeout=ACTION_TIMEOUT)
            page.wait_for_timeout(900)
            options = _own_listbox_options(field)
            if not options:
                continue

            best_idx, best_score = -1, 0.0
            for i, opt in enumerate(options[:30]):
                try:
                    text = (opt.inner_text() or "").strip()
                except Exception:
                    continue
                if not text:
                    continue
                score = fuzz.partial_ratio(score_target, text.lower())
                if score > best_score:
                    best_score, best_idx = score, i

            if best_idx >= 0 and best_score >= 60:
                try:
                    options[best_idx].click(timeout=ACTION_TIMEOUT)
                    matched = True
                    break
                except Exception:
                    pass
            field.fill("", timeout=ACTION_TIMEOUT)
    except Exception:
        pass

    if not matched:
        # Nothing matched well enough -- leave the full value typed, same
        # fallback behavior as before this fix existed.
        try:
            field.fill(value, timeout=ACTION_TIMEOUT)
        except Exception:
            pass

    # Always dismiss any menu left open -- an open dropdown can visually
    # and functionally block clicks/fills on whatever field comes next.
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    return matched


class FillResult:
    def __init__(self) -> None:
        self.filled: list[str] = []
        self.skipped: list[str] = []

    def report(self) -> str:
        lines = [f"Filled {len(self.filled)} field(s):"]
        lines += [f"  [x] {f}" for f in self.filled] or ["  (none)"]
        lines.append(f"Could not confidently match {len(self.skipped)} field(s) -- fill these yourself:")
        lines += [f"  [ ] {f}" for f in self.skipped] or ["  (none)"]
        return "\n".join(lines)


def fill_generic_form(page: Page, profile: Profile, scope: Page | Locator | None = None) -> FillResult:
    """Fill visible form fields within `scope` (defaults to the whole page)."""
    scope = scope or page
    result = FillResult()

    field_selector = "input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select"
    inputs = scope.locator(field_selector)
    count = inputs.count()

    if count == 0:
        # Some Greenhouse/Lever-backed career pages (Stripe's, for example)
        # show a job listing with an "Apply" button and only reveal the
        # actual form after it's clicked -- try that once before giving up.
        apply_btn = scope.locator("button:has-text('Apply'), a:has-text('Apply')").first
        try:
            if apply_btn.count() > 0 and apply_btn.is_visible():
                apply_btn.click()
                page.wait_for_timeout(1500)
                inputs = scope.locator(field_selector)
                count = inputs.count()
        except Exception:
            pass

    if count == 0 and scope is page:
        # Greenhouse's current standard embed serves the actual form inside
        # an <iframe> (job-boards.greenhouse.io/embed/job_app) rather than on
        # the host page itself -- same for some Lever embeds. Check each
        # same-page iframe for form fields and fill inside the first one
        # that has any, rather than reporting "nothing found".
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                frame_inputs = frame.locator(field_selector)
                frame_count = frame_inputs.count()
            except Exception:
                continue
            if frame_count > 0:
                scope = frame
                inputs = frame_inputs
                count = frame_count
                break

    for i in range(count):
        field = inputs.nth(i)
        try:
            if not field.is_visible():
                continue
        except Exception:
            continue

        tag = field.evaluate("el => el.tagName.toLowerCase()")
        input_type = (field.get_attribute("type") or "").lower()

        try:
            label_text = field.evaluate(_LABEL_JS)
        except Exception:
            label_text = ""

        if input_type == "file":
            match = best_match(label_text or "resume", profile)
            if match and match[0].kind == "file":
                path = profile.resume_path()
                if path.exists():
                    field.set_input_files(str(path))
                    result.filled.append(f"[file] {label_text or '(unlabeled upload)'} -> {path.name}")
                    continue
            result.skipped.append(f"[file] {label_text or '(unlabeled upload)'}")
            continue

        match = best_match(label_text, profile)
        if not match:
            if label_text:
                result.skipped.append(f"[{tag}] {label_text}")
            continue

        spec, value = match
        try:
            if tag == "select":
                field.select_option(label=value)
            elif input_type == "checkbox":
                if str(value).strip().lower() in ("true", "yes", "1"):
                    field.check()
            elif input_type == "radio":
                # Radios need option-level (not field-level) matching --
                # left unfilled for manual review rather than guessing.
                result.skipped.append(f"[radio] {label_text}")
                continue
            elif _is_typeahead_input(field) and value.strip().lower() not in ("true", "false", "yes", "no"):
                # Boolean-valued answers ("True"/"False") aren't real search
                # queries for a react-select instance's catalog search, and
                # trying still leaves it correctly falling through to a
                # plain .fill() below -- known limitation, tracked
                # separately, not worth the extra round-trip on every
                # Yes/No-style question on the form.
                city_hint = str(profile.get("personal.city", "") or "") if spec.profile_path == "education.school" else ""
                degree_level_candidate = (
                    [str(profile.get("education.degree_level", "") or "")]
                    if spec.profile_path == "education.degree"
                    else None
                )
                _fill_typeahead(page, field, value, hint=city_hint, extra_candidates=degree_level_candidate)
            else:
                field.fill(value)
            result.filled.append(f"[{tag}] {label_text} -> {value}")
        except Exception as e:
            result.skipped.append(f"[{tag}] {label_text} (error: {e})")

    return result
