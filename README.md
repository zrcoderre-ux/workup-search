# Workup Search

A local browser-based search interface for motion "workup" `.docx` documents.
Indexes the documents into SQLite FTS5, serves them from a small local Python
HTTP server, and provides search, filtering, preview, one-click open in Word,
and automatic legal-citation hyperlinking (live Westlaw/Lexis search links).

## Files

| File | Role |
|------|------|
| `workups.html` | Single-page browser UI (open as a local file) |
| `app.py` | Local HTTP server on port 54321 |
| `index.py` | Scans the Workups folder, extracts text/HTML, builds the index |
| `citation_extractor.py` | Citation detection engine |
| `Workup Search.bat` | Launcher: kills any old server, starts it windowless, opens the UI |
| `Workup Search.vbs` | Silent wrapper that runs the sibling `.bat` with no console window; the desktop shortcut points here |
| `config.example.py` | Committed path template, auto-copied to `config.py` on first run |

The cross-opener Chrome extension lives in its own separate repository and is
not part of this project.

## Setup

With the auto-pull tool, setup is hands-off: add the repo to `pull-extensions.ps1`
(`Reload = $false`, no `OnUpdate` hook), run the pull shortcut, and it clones to
`C:\Users\ZCoderre\Apps\Workup Search`. The first launch does the rest:

- `config.py` is created automatically from `config.example.py` on the first
  run of `index.py` or `app.py` (it is gitignored and never pushed; it is the
  per-machine override).
- Build the document index once with `python index.py`. This writes the
  database to `%USERPROFILE%\WorkupSearch\` (i.e. `C:\Users\<you>\WorkupSearch\`).
  Re-run it whenever you add or change workup documents.

So after the clone: run `python index.py` once, then launch via the desktop
shortcut (or `Workup Search.vbs` / `Workup Search.bat` directly). The desktop
shortcut should target `wscript.exe "…\Workup Search\Workup Search.vbs"` so it
opens with no console flash. Edit `WORKUPS_FOLDER` in `config.py` only if your
Workups folder differs from the baked-in default.

Manual setup (no pull tool) is the same, minus the clone: drop the files in a
folder outside OneDrive/SharePoint and run `Workup Search.bat`.

Requires Python (the Microsoft Store build is fine; no admin rights needed).

## Pushing to GitHub

Push everything **except** `config.py`, `workups_index.db`, and
`workup_debug.log` (all gitignored). In a push-first workflow these won't exist
yet anyway — `config.py` is created on the first local run after cloning.

## Where things must live

- **This repo folder is relocatable** — put it anywhere *except* inside a
  cloud-synced folder (OneDrive/SharePoint). Git and cloud sync corrupt each
  other's working files. `C:\Users\<you>\Apps\Workup Search` is a good spot.
- **The index database is never in the repo.** It lives in `%USERPROFILE%\WorkupSearch\`
  (a plain folder in your user directory). It is kept off any synced path
  because SharePoint/OneDrive sync corrupts SQLite mid-write, **and** out of
  `%LOCALAPPDATA%` because the Microsoft Store build of Python silently
  redirects `AppData\Local` writes into a hidden per-package sandbox — which
  makes the DB unfindable at the printed path and orphans it on a Python
  version bump. The user-profile root avoids both traps. A fresh clone rebuilds
  the DB on the first `python index.py` run (note: user-created tags live only
  in this DB and are *not* rebuilt from the `.docx` files, so preserve it when
  moving machines or upgrading Python).
- **The Workups `.docx` corpus** stays on its SharePoint library path; the
  code only needs the path to it (set in `config.py`).

## Citations

Citations are detected at preview time and linked to **live** Westlaw/Lexis
search URLs built on the fly (rot-proof). There is no stored link cache.
