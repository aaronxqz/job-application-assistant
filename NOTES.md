# Platform notes / known limitations

This is a starter project, not a finished product. Realistic expectations
per platform:

**Greenhouse / Lever / plain company forms** -- the generic filler should
handle most standard text/select fields well. Custom question fields
("Why do you want to work here?") only get filled if their wording is
close to something in `common_answers` in your profile -- otherwise they
show up in the "could not confidently match" list and you fill them by
hand. Many companies now embed their Greenhouse form inside an `<iframe>`
(`job-boards.greenhouse.io/embed/job_app`) rather than hosting it directly
-- `fill_generic_form` checks same-page iframes for form fields when the
top-level page has none, so these still get filled. Some fields (School,
sometimes Degree) are react-select typeaheads, not plain inputs -- typing
alone doesn't register a real selection; `_fill_typeahead` in `generic.py`
simulates real keystrokes, retries with a shorter query if the full value
returns no results, and clicks the best-matching option (using the
profile's city to break ties between a multi-campus school's options).

**Fixed: Degree-level vs. major.** Some forms' "Degree" field is actually a
degree-*level* picklist (Bachelor's/Master's/PhD), not a free-text major --
`education.degree` (your full "B.S. Computer Science & ...") doesn't match
either cleanly on those, confirmed on a real Stripe form where it returned
zero autocomplete results. Added `education.degree_level` ("Bachelor's
Degree") to the profile; `_fill_typeahead` tries the major first, then
falls back to the degree level as a last-resort query when the field is a
typeahead and the major search comes up empty -- verified live, correctly
selects "Bachelor's Degree" on that same form.

**Known gap: Yes/No react-select dropdowns.** Boolean-valued questions
(work authorization, sponsorship, etc.) that render as a react-select
typeahead rather than a real `<select>` currently get the literal text
"True"/"False" typed in, which doesn't register as a real Yes/No
selection either (same widget as School/Degree, deliberately not run
through the same fix yet -- "True" isn't a real search query, needs its
own translation to "Yes"/"No" before reusing the typeahead-click
mechanism). Read these before submitting.

**Fixed matching bug, found during testing:** the fuzzy label matcher
(`field_matcher.py`) used to score with `partial_ratio`, which let short
generic aliases like "state" or "phone" false-match against long, unrelated
labels by pure substring/character overlap -- confirmed on a real Stripe
application, "Veteran Status" and "Disability Status" got filled with your
*state* ("NJ"), and a sponsorship question got your phone number. Switched
to `token_set_ratio` (real token-overlap, not character-substring
alignment) with punctuation normalization, verified against a 30-case
regression set (true matches that must keep working + every false match
seen on the real Stripe form) and re-confirmed live on that same form: same
15 legitimate fields filled, zero wrong fills, previously-dangerous fields
now correctly land in "skipped" for manual review. **Still always read
every filled field before submitting** -- this class of bug is fixed, not
guaranteed impossible; the review step is the real safety net, this fix
just makes it need to catch less.

**LinkedIn Easy Apply** -- handled specifically (`autofill/platforms/linkedin.py`).
Multi-step modal, stops at the review screen, never clicks final Submit.

**Workday** -- deliberately NOT special-cased here. Workday renders its own
custom dropdown/combobox widgets (not real `<select>` elements) and often
uses shadow DOM, so the generic label-matching approach mostly won't find
or fill them correctly. If you want Workday support, that's a good next
step: add `autofill/platforms/workday.py` with selectors for Workday's
specific widget classes (inspect one with browser devtools first).

**Radio buttons** -- intentionally left unfilled everywhere. Matching a
label to a *field* is one problem; matching it to the *correct option
among several radios* is a different, harder one, and guessing wrong on
a yes/no legal question (work authorization, felony history, etc.) is
worse than leaving it blank. Fill these by hand.

**EEO / demographic questions** -- the profile template defaults these to
blank on purpose. Leave them blank unless you want to answer, and prefer
"Decline to answer" where the site offers it -- these fields are legally
optional in the US.

## A note on submitting

This tool fills forms; it does not submit them. Two reasons: (1) mistakes
are much cheaper to fix before you've applied than after, and (2) most
platforms' terms of service prohibit fully automated submissions, and
recruiters can often tell when an application was auto-submitted with
mismatched or generic answers. Use this to kill the repetitive-typing
part of applying, then actually look at the form before you hit Submit.
`review` (see README section 5) keeps this rule even when it's working
through a whole queue -- it stops and waits for you before every single
one.

## A note on auto-search

`search` reuses the same "watch, don't submit blind" philosophy: Greenhouse
and Lever are their own public, documented, no-auth JSON APIs, so those are
low-risk. LinkedIn, Amazon, Google, and TikTok don't offer anything like
that for job search -- `search` reads their public job-search pages'
rendered HTML instead, capped and paced (`rate_limit` in
`search_config.yaml`) so it behaves like one slow human page load rather
than a scrape burst. That's a deliberate, signed-off-on tradeoff, not an
oversight: none of these four sites' terms of service explicitly bless
scripted browsing of their search results, even at this pace. If you ever
see a captcha or a "verify you're human" wall from one of them, that's your
signal to dial back how often `search` runs against it, not something to
route around.

Amazon, Google, and TikTok postings are tracked (found, categorized,
logged) but **not** auto-filled -- their application forms are custom,
JS-heavy, and unverified against this tool's generic form-filler, so
`review` deliberately skips them rather than guessing, same reasoning as
Workday above. See README's Phase 2 note for what adding real support would
take.

## A note on review's queue ordering (fixed a real problem, not a hypothetical one)

Reported directly: `review --sort newest` kept serving Stripe posting after
Stripe posting, and the dashboard's "found, newest" filter showed
Amazon/Google postings at the top that never appeared in `review` at all.
Root cause, confirmed rather than assumed: `found_at` only has day
granularity, so on any day `search` ran, everything found that day ties on
the sort key -- and Python's stable sort resolves ties by original list
order (~fetch order), so whichever high-volume source got fetched first
(Stripe, both first in `greenhouse_tokens` and by far the largest -- 300+
postings) sorted as one unbroken block ahead of every other company. The
Amazon/Google half was working as designed (no fill adapter, so `review`
correctly excludes them) but was invisible -- nothing showed you *why* they
weren't there.

Two fixes, both in `tracking.py`/`cli.py`:

- **`_interleave_by_company`** round-robins across companies instead of a
  flat sort -- confirmed against real data: flat sort put 11 straight
  Stripe entries before Airbnb ever appeared; interleaved, the first 20
  rotate cleanly through all 6 companies. On by default (`--no-interleave`
  for the old behavior).
- **`review`'s pre-flight numbered list** (`preview_queue` in
  `tracking.py`) shows both fillable and manual-apply-only postings
  together, each tagged, before any browser opens -- so Amazon/Google/
  TikTok entries are visible with a reason ("manual apply -- no fill
  adapter") instead of silently absent. You can type specific indices to
  pick exactly which ones to review, in what order, rather than always
  taking the list top-to-bottom.

## A note on mail-check matching

**Fixed: same-company disambiguation.** `mail_classify.match_company` used
to score only on company name against the email's `from`/`subject` --
confirmed broken on real mail: two Stripe confirmation emails (different
roles) shared the *identical* subject line ("Thanks for applying to
Stripe!"), with the role name only appearing in the snippet. Company-only
matching silently picked the same (first) Stripe entry for both, so the
second one's status update looked like a no-op ("already applied") even
though it was actually a different, still-unconfirmed posting. Now also
scores role-word overlap against the snippet too, and uses that to
disambiguate between multiple postings at the same company -- verified
against the real two-email case. If you track several roles at the same
company, this is the mechanism keeping them from bleeding into each other;
if a mismatch ever shows up, it likely means the role name in
`applied_log.csv` doesn't share enough words with what the email's snippet
actually says.

**Fixed: account/portal emails matching a posting by coincidence.**
Confirmed on real mail: a Greenhouse "security code for your application"
email (a one-time verification code for the *applicant portal account*,
unrelated to any specific application's status) matched a tracked "Cloud
Security Engineer" posting purely because "security" appears in both, and
a Gmail "Security alert -- Recovery phone was changed" account notification
matched a tracked "Google"-company posting purely because it mentions
Google. Both are about account mechanics, not application status.
`is_non_application_email` (`mail_classify.py`, `NON_APPLICATION_MARKERS`)
filters these out before company matching even runs, checked against both
real examples plus the legitimate confirmation/interview emails to confirm
neither regressed.

**Added: ambiguous emails are remembered, not re-shown every run.**
`mail-check` re-fetches the same `--query` date window every time it runs,
so an email that matched a company but didn't classify cleanly used to
print again on every subsequent run for as long as it stayed inside that
window -- confirmed as real, growing noise after a few days of the cron
job running. Gmail message IDs of anything shown as ambiguous are now
saved to `data/mail_seen.json` (gitignored) and skipped on later runs.
This is separate from the account-email filter above: that filter means
the message is never shown at all (it's not a status signal); this one
means a message WAS shown once as "read this yourself," and isn't repeated
after that. Neither auto-resolves anything -- if you want a specific
ambiguous email's outcome recorded, set it by hand via `status`.

**Fixed: duplicate transition lines when several emails match the same
entry in one run.** `cmd_mail_check` loaded the tracked entries once at the
start and never updated its in-memory copy after writing a status change --
confirmed on real mail: three near-identical Stripe rejection emails
(Gmail had them as separate messages) all matched the same tracked posting,
and each one printed its own "abandoned -> rejected" line even though only
the first one was a real change; the other two were redundant against an
already-stale snapshot. Fixed by updating the in-memory `entry.status`
right after each successful `update_status()` call, so a later message in
the same run sees the current state and silently no-ops instead of
reprinting.

**Known residual risk, not fixed (needs your judgment, not a heuristic):**
that same real example exposed a harder problem. The rejected posting
("Software Engineer, Stripe Tax") was located in Dublin, Ireland --
correctly auto-abandoned as Non-US by `search`, never filled or submitted
through this tool. For a real rejection email to exist for it, an
application must have happened some other way (directly on the company's
site, say) -- `match_company` has no way to tell "this rejection is
genuinely about the one Stripe Tax posting I have tracked" apart from
"this rejection is about a *different*, untracked Stripe Tax posting (e.g.
a US-based duplicate with the same title) that coincidentally shares a
role name with the only candidate I have." When there's exactly one
same-company, same-title candidate, it gets picked regardless of which
case is true. Worth a manual glance any time a status update lands on an
entry you don't remember interacting with.

## A note on why there's no credential/password vault

A site that needs its own account is fully handled by `login` (see README
step 3 / step 4) -- log in by hand once, the session cookie persists in
`browser_profile/` (one shared Chromium profile across every site) and
every future `fill`/`review`/`search` call reuses it automatically. That's
deliberately the *only* mechanism here, not a first version of something
bigger:

- **The cookie already solves the actual problem** ("I don't want to log in
  every time") without ever needing to know or store your password.
- **Storing raw credentials would be a strictly worse security posture** --
  a plaintext (or even encrypted-at-rest) password file is a bigger target
  than a session cookie, and there's no real upside once the cookie already
  covers repeat use.
- **Automating the login *form* itself** (typing a username/password in,
  vs. reusing a session you already established by hand) is a different
  and riskier thing than autofilling a *job application* form -- most
  sites' ToS treat automated login attempts more seriously than a filled-in
  form a human reviews before submitting, and it can't work at all once
  2FA/MFA is involved, which is increasingly the default.

If a specific site's session keeps expiring faster than you'd like, that's
a signal to re-run `login` for it periodically, not to start storing
passwords.

## A note on senior/experienced-role filtering (`autofill/seniority.py`)

`search` now skips postings that look like they need real prior experience
by default (`exclude_senior: true` in `search_config.yaml`) -- title
contains Senior/Staff/Principal/Manager/Director/Lead/Architect/VP (and
isn't also explicitly Intern/Entry Level/Junior/New Grad), or the JD
states "N+ years of experience" with N >= 3.

Calibrated against real tracked data, not guessed: an early version of the
years-of-experience regex matched "18 years of **age**" on Amazon
internship postings (an eligibility line, unrelated to seniority) --
fixed by requiring the specific "years ... experience" phrasing. The
title-keyword list was checked against all 157 unique titles it flagged in
that dataset with zero false positives before it was applied. A one-time
bulk pass also marked 196 already-tracked postings `abandoned` using the
same function -- see the `abandoned` status note above for what that does
and doesn't touch.

Same "don't guess wrong" posture as everywhere else: this is a keyword/
regex heuristic, not a real understanding of the JD, so it can still miss
a senior posting with an unusual title, or (less likely, since the title
keyword list is broad) flag something that isn't really senior. If you
notice either, it's a one-line edit to `SENIOR_TITLE_WORDS` or
`MIN_YEARS_THRESHOLD` in `autofill/seniority.py`.

## A note on location filtering (`autofill/location.py`)

`search` classifies every posting's work location -- `Remote`, a US region
(Northeast/Midwest/South/West, the standard US Census 4-region split),
`US - Unspecified` (a US signal is present but no specific state/region),
`Non-US`, or `Unknown` (not enough signal either way) -- and auto-marks it
`abandoned` instead of `found` when the result is `Non-US`. Calibrated
against 1783 real postings' location strings (592 unique), not guessed.

The one real trap that calibration caught: "Hyderabad, IN" -- if you trust
any "City, ST" pattern as a US state code, "IN" reads as Indiana. Fixed by
only trusting that pattern when no known non-US city/country name is also
present in the string; an explicit "United States"/"USA"/standalone "US"
marker is checked independently and always wins regardless of what else is
in the string -- so "US, Canada" or "Remote in the US, Toronto" (both real
values in the data) correctly stay a US possibility rather than getting
abandoned just because a non-US city is *also* listed as an option.
`Unknown` results (an empty field, "N/A", or a location string with no
recognizable signal either way) are never abandoned -- left as `found` for
you to check, same reasoning as everywhere else that guesses wrong would
cost more than asking.

A one-time pass also backfilled `location`/`location_type` on already-
tracked Greenhouse/Lever postings still sitting at `found`/`queued`/
`pending` by re-fetching the same public APIs and matching by URL (fast,
free, no browser) -- postings no longer live on the board, or from
Amazon/Google/TikTok (which don't offer a cheap way to re-fetch without a
full re-scrape), were left with an empty `location_type` rather than
guessed.
