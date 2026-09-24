# job-autofill

A Playwright-based tool that fills out job application forms from your own
profile data, then stops before submitting so you can review. Built for
Python, targets LinkedIn Easy Apply plus generic ATS forms (Greenhouse,
Lever, company career pages). See `NOTES.md` for per-platform limitations
(especially Workday, and radio buttons).

---

## 0. Where to run this: use your WSL terminal, not Windows

You already moved your dev setup into WSL -- stick with that for this
project. Two reasons:

- All the tooling here (`python3`, `pip`, Playwright's browser binaries)
  installs and runs more reliably on native Linux than bridging between
  Windows and WSL's filesystem. Doing everything inside WSL avoids
  path-translation and permission headaches.
- The "Windows is more efficient because I can click through steps"
  feeling doesn't really apply to Claude Code specifically -- it's the
  same AI either way, and it runs terminal commands *for you* whether
  you type to it from claude.exe on Windows or from `claude` inside your
  WSL terminal. The GUI isn't doing anything Claude Code plus a terminal
  can't already do. So: open your WSL terminal, `cd` into this project,
  and run `claude` there. Ask it in plain English to do things
  ("create a venv and install the requirements") and it will run the
  actual commands for you -- you don't need to memorize terminal syntax
  up front.

Terminal survival kit, in case it helps while you're getting comfortable:

| Command | What it does |
|---|---|
| `pwd` | print where you are |
| `ls` | list files in current folder |
| `cd job-autofill` | move into a folder |
| `cd ..` | move up one folder |
| `mkdir foo` | make a folder |
| Tab key | autocompletes file/folder names -- use it constantly |
| Up arrow | cycles through previous commands |
| Ctrl+C | stop whatever's currently running |
| `code .` | open the current folder in VS Code (if installed) |

## 1. One-time setup (inside WSL)

```bash
cd ~/job-autofill   # or wherever you place this project

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
playwright install --with-deps chromium
```

`playwright install --with-deps chromium` downloads a Chromium build and
the OS libraries it needs -- this can take a few minutes.

**About seeing the browser window:** this tool runs with a visible
browser on purpose (`headless=False`) so you can watch it work and step
in when needed. On Windows 11, WSL2 has WSLg built in, so GUI apps like
this Just Work -- a real window should pop up on your Windows desktop.
On Windows 10 you'd need a separate X server (e.g. VcXsrv); if a browser
window doesn't appear when you run the tool, that's the first thing to
check (`wsl --version` tells you your WSL version, or ask Claude Code
"how do I check if WSLg is available").

## 2. Fill in your profile

```bash
cp data/profile.example.yaml data/profile.yaml
```

Edit `data/profile.yaml` with your real info, and put your resume at the
path you set under `resume.file_path` (default `data/resume.pdf`). This
file is gitignored -- it never gets committed or shared anywhere.

## 3. Log into LinkedIn (or any site) once

```bash
python -m autofill login
```

A browser window opens. Log in by hand (this also gets you past any
captcha/2FA). Once you're logged in, press Enter in the terminal to
close it -- the session is saved to `browser_profile/` and every future
run reuses it, so you won't have to log in again.

## 4. Fill out an application

```bash
python -m autofill fill "https://www.linkedin.com/jobs/view/1234567890"
```

or for any other job posting:

```bash
python -m autofill fill "https://boards.greenhouse.io/somecompany/jobs/12345"
```

Watch the terminal for a report of what got filled and what didn't. The
browser window stays open afterward -- review everything, manually fix
anything it missed or matched wrong, and click Submit yourself.

`fill` also adds the posting to `applied_log.csv` automatically (company
and role are a best-effort guess from the URL/page title -- correct them
with `status --list` if they're off), so ad-hoc applications to sites
outside the `search` sources still end up tracked and show up on the
dashboard. Override the guess, or skip tracking entirely:

```bash
python -m autofill fill "<url>" --company "Acme Corp" --role "Backend Engineer"
python -m autofill fill "<url>" --no-track   # just fill it, don't touch applied_log.csv
```

If you re-fill a URL that's already progressed past "found" (e.g. you
already marked it `applied` or `interview`), `fill` won't regress that
status back down -- same protection `mail-check` has.

**A site that needs its own login you haven't set up yet?** Use the same
`login` command from step 3 with that site's login URL:

```bash
python -m autofill login "https://some-company.com/careers/login"
```

Log in by hand once; the session is saved to `browser_profile/` (one
shared profile across every site) and reused automatically by every future
`fill`/`review`/`search` call, no separate credential storage needed --
see `NOTES.md` for why this is deliberately not a password vault.

## 5. Auto-search, review, and dashboard

Instead of pasting one URL at a time, you can search for postings and work
through them as a queue. `data/search_config.yaml` already exists with some
starter values -- edit it directly (it's tracked in git, not gitignored,
since it holds no personal data, just company tokens and keywords).

Edit `data/search_config.yaml`: add your own `greenhouse_tokens` /
`lever_companies` (a company's public API token is usually visible in their
careers page footer, or just try
`https://boards-api.greenhouse.io/v1/boards/<token>/jobs`), and adjust the
`linkedin_searches` / `amazon_searches` / `google_searches` /
`tiktok_searches` keyword lists to match what you're looking for.

```bash
python -m autofill search                  # all sources
python -m autofill search --no-browser-search  # Greenhouse/Lever only, fast, no browser
```

This finds postings, scores them for relevance against your profile and
`search_config.yaml`'s keywords, tags each with a category
(SDE/SRE/IT/Security/Data/Other) and type (Internship/Entry Level/Full
Time), skips anything that looks like it needs real prior experience
(`exclude_senior: true` by default -- see `NOTES.md`), classifies work
location (`autofill/location.py`) into `Remote`, a US region
(Northeast/Midwest/South/West), `US - Unspecified`, `Non-US`, or `Unknown`,
and adds what's left to `applied_log.csv` -- **auto-marked `abandoned`
instead of `found` if the location resolves to `Non-US`**, so non-US
postings never enter the review queue at all. `Unknown` (not enough
location info to tell either way) is left as `found` rather than guessed.

```bash
python -m autofill review                              # newest-found first (default)
python -m autofill review --sort oldest                 # oldest-found first
python -m autofill review --category IT,SRE,Security    # only these categories
python -m autofill review --limit 25                    # show more/fewer in the pre-flight list (0 = show all)
python -m autofill review --no-interleave                # old flat sort, one company at a time
```

`review` first prints a numbered pre-flight list (15 by default) of
everything still `found`/`queued` -- **both fillable (Greenhouse/Lever/
LinkedIn) and manual-apply-only (Amazon/Google/TikTok), each row tagged so
you can see which is which**, since a plain `found` filter doesn't tell you
that on its own. By default these are **round-robin interleaved by
company**, not a flat sort -- a flat sort on `found_at` (day granularity
only) let one high-volume company's whole backlog crowd out everyone else
for the entire batch, confirmed as a real problem, not just a theoretical
one. Then:

```
Enter = review these in order  |  "0,3,5" = just those, in that order  |  q = cancel
```

Enter works through the (interleaved) list as shown; typing specific
indices reviews only those, in the order you list them -- picking a
manual-apply-only index just prints its URL for you to open by hand, it's
not silently dropped. Once a batch is chosen, `review` fills each one,
marks it `filled_pending_review`, and waits for you to actually look at it
and click Submit before moving to the next -- same no-auto-submit rule as
`fill`. At each one, instead of pressing Enter you can also type `s` to put
it back to `found` for later instead of leaving it `filled_pending_review`,
or `a` to mark it `abandoned` (not interested, won't show up in review
again) -- Ctrl+C to stop the batch entirely is always safe too, nothing is
lost either way, since the status write already happened before the prompt.
At the end of a batch, `review` also prints the *total* count of
Amazon/Google/TikTok postings still needing manual apply across everything
tracked, not just what was in this one batch's preview.

**Optional cover letters.** Before filling each posting, `review` checks
`data/cover_letters/<company>-<role>.txt` (matched by slug, e.g.
`stripe-ai-engineer.txt`). If it's there, it gets attached automatically to
any cover-letter upload field the form has. If not, `review` pauses and
tells you to ask Claude Code -- in chat, not this script, so there's no API
key or per-letter cost -- to draft one for that specific posting and save
it to that path, then continue. Set `cover_letters.enabled: false` in
`search_config.yaml` to skip this prompt entirely.

```bash
python -m autofill dashboard
```

Starts a small local web server (127.0.0.1 only, never exposed beyond your
own machine) and opens it in your browser: how many you've applied to
today, how many new postings showed up today, your current queue size,
response rate, breakdowns by category/type/source/status, and the full log
as a sortable table -- with a **real dropdown on every row's Status
column**. Pick a new value and it writes to `applied_log.csv` immediately
and the page refreshes. Stop the server with Ctrl+C in the terminal it's
running in; that never touches your data, it just stops serving the page.

The toolbar above the table has both controls together, and they compose
(filtering just hides non-matching rows, sorting reorders all of them, so
picking a status and a sort order works together correctly): **"Filter
status"** shows only rows matching the status you pick (e.g. just
`Applied`, just `Rejected`) -- pick "All statuses" to clear it. **"Sort by
found date"** is Newest first (the default) or Oldest first. Clicking any
column header (including "Found") still works too and stays in sync with
the dropdown either way.

Prefer a one-shot static file instead (no running process, e.g. to email
someone a snapshot)? `python -m autofill dashboard --static` writes
`dashboard.html` and opens it read-only, same as before.

Terminal shortcuts also still work if you'd rather not open the browser:

```bash
python -m autofill status --list             # see every tracked posting with its index
python -m autofill status 12 pending          # mark index 12 as "pending" (or any status)
python -m autofill status --reset             # bulk-reset every filled_pending_review/pending entry back to 'found'
```

Valid statuses: `found`, `queued`, `pending`, `filled_pending_review`,
`applied`, `interview`, `rejected`, `offer`, `abandoned`. You can also just
open `applied_log.csv` directly in Excel/Sheets and edit the status column
-- it's a plain CSV either way. The dashboard has a "What do the statuses
mean?" panel with a plain-English explanation of each one and what
switching to it actually does.

**Not interested in a posting?** Mark it `abandoned` (via the dashboard
dropdown, or `python -m autofill status <index> abandoned`) -- it drops out
of `review`'s queue and `needs_manual_apply` immediately, and it's
protected the same way `rejected`/`offer` are: `mail-check` and `fill`
won't move it to some other status on their own afterward. `search`
already never re-adds a URL that's already tracked regardless of status, so
an abandoned posting can't come back as a duplicate row either.

**Gmail tracking.** `python -m autofill mail` lists recent messages
(read-only -- gmail.readonly scope, can never send/delete/modify) from a
dedicated Gmail account set up for job applications, so your personal inbox
doesn't get buried. First run opens a browser once for you to approve
access (needs `data/google_client_secret.json`, a Google Cloud OAuth
"Desktop app" client -- see Google Cloud Console: create a project, enable
the Gmail API, configure the OAuth consent screen as External with the
`gmail.readonly` scope, add yourself as a test user, then create an OAuth
client ID); after that the token is cached to `data/gmail_token.json`
(gitignored, like the client secret) and auto-refreshes. `--query` takes
Gmail search syntax (default `newer_than:3d`), e.g. `--query is:unread`.

```bash
python -m autofill mail-check
```

Fetches recent mail, first drops anything that's obviously account/portal
mechanics rather than an application update (verification codes, "security
alert" login notifications, etc. -- confirmed on real mail: a Greenhouse
verification code matched a "Security Engineer" posting, and a Gmail
account-security alert matched a "Google" posting, both purely by
coincidental keyword/company-name overlap -- see `NON_APPLICATION_MARKERS`
in `autofill/mail_classify.py`), matches what's left against your tracked
companies in `applied_log.csv` (a message from/about an untracked sender --
Panera, subscription receipts, etc. -- is ignored too, the spam filter),
and keyword-classifies matches into a status update (rejection phrasing ->
`rejected`, interview/scheduling phrasing -> `interview`, "received your
application" -> `applied`, etc. -- see `CLASSIFY_RULES`). Status only ever
moves forward, never backward, so a later unrelated match can't undo an
already-recorded interview/rejection.

Anything that matches a tracked company but doesn't clearly fit one of the
keyword rules is printed once for you to read and set manually via
`status`, rather than guessed at. **It's remembered after that** (Gmail
message IDs in `data/mail_seen.json`, gitignored) -- the same ambiguous
email won't clutter every subsequent run just because it's still inside the
`--query` date window. Runs standalone, no API key needed (unlike the
cover-letter feature, which asks Claude Code in chat) -- self-contained the
same way `search` is, so it works unattended via cron.

**Running `search` and `mail-check` automatically once a day:** since the LinkedIn/Amazon/
Google/TikTok portion needs a visible browser window (these sites'
bot-detection specifically watches for headless traffic, so `browser.py`
never runs headless), a cron job only fully succeeds while your WSL/WSLg
session is up -- Greenhouse/Lever still work either way since they're plain
HTTP calls (`mail-check` is unaffected either way -- it's a plain API call,
not a browser). A typical crontab (installed, in this project, via
`crontab -l`):

```
0 9 * * * cd /home/YOU/job-autofill && .venv/bin/python -m autofill search >> search.log 2>&1
15 9 * * * cd /home/YOU/job-autofill && .venv/bin/python -m autofill mail-check >> mail.log 2>&1
```

Check `search.log`/`mail.log` after they've run to see whether the
browser-based sources succeeded that day and what (if anything)
`mail-check` updated. Both also work as one-off manual commands any time,
same as `search` does -- run `python -m autofill mail-check` yourself
whenever you don't want to wait for 9:15am.

## Project layout

```
job-autofill/
  data/
    profile.example.yaml   # template -- copy to profile.yaml and edit
    search_config.yaml     # company tokens + search keywords, tracked in git
  autofill/
    profile.py             # loads profile.yaml
    search_config.py       # loads search_config.yaml
    browser.py              # persistent (stays-logged-in) browser launcher
    field_matcher.py        # fuzzy-matches form labels -> your profile data
    relevance.py            # "is this posting kinda related to me" filter
    classify.py             # tags postings with category + employment type
    tracking.py             # applied_log.csv read/write, review queue
    dashboard.py            # stats + HTML rendering (static or interactive)
    dashboard_server.py     # localhost server for the live editable dashboard
    mailwatch.py             # read-only Gmail API access
    mail_classify.py         # keyword rules: match mail to tracked apps, classify
    cli.py                  # `python -m autofill ...` entry point
    sources/
      greenhouse.py, lever.py            # public JSON APIs, no browser
      linkedin_search.py, amazon.py,     # Playwright DOM scraping,
      google.py, tiktok.py               # rate-limited
    platforms/
      generic.py            # works on most plain HTML forms
      linkedin.py            # LinkedIn Easy Apply, multi-step modal
  NOTES.md                  # per-platform limitations, read this
  requirements.txt
```

## Extending it

The field-matching table lives in `autofill/field_matcher.py` --
`FIELD_TABLE`. If a site asks a question the tool doesn't recognize, add
a `FieldSpec` there with a few phrasings of that question as aliases and
it'll start matching automatically everywhere, not just on that one site.

To add real Workday support (see `NOTES.md` for why it's not included
yet), create `autofill/platforms/workday.py` following the same shape as
`linkedin.py`, and register it in `autofill/platforms/__init__.py`.

## Roadmap

- **Phase 2 -- Amazon/Google/TikTok auto-fill.** `autofill/sources/{amazon,google,tiktok}.py`
  already find and track postings from these three; they just don't have a
  fill adapter yet (see `NOTES.md`). Add `autofill/platforms/amazon.py` etc.
  following `linkedin.py`'s shape, built after inspecting each site's actual
  application form live, and register them in `autofill/platforms/__init__.py`
  and `autofill/tracking.py`'s `SUPPORTED_FILL_SOURCES`.
- **Phase 3 -- Gmail confirmation/interview detection.** Requires setting up
  a Google Cloud OAuth app first (client ID/secret, consent screen, Gmail
  API scope) -- a credential step outside this repo. Once available, a new
  `autofill/gmail.py` would poll for messages matching sender/subject
  heuristics per `applied_log.csv` company and call `tracking.update_status()`
  automatically instead of you hand-editing the status column.
