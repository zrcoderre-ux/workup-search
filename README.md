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
| `Workup Search.bat` | Launcher: starts the server windowless, opens the UI |
| `config.example.py` | Template for machine-specific paths (copy to `config.py`) |

The cross-opener Chrome extension lives in its own separate repository and is
not part of this project.

## Setup

1. Install Python (the Microsoft Store build is fine; no admin rights needed).
2. Copy the config template and set your paths:
   ```
   copy config.example.py config.py
   ```
   Edit `config.py` and set `WORKUPS_FOLDER` to your Workups folder.
   `DATABASE_FILE` defaults to `%LOCALAPPDATA%\WorkupSearch\` and normally
   needs no change.
3. Build the index once:
   ```
   python index.py
   ```
4. Launch:
   ```
   "Workup Search.bat"
   ```

## Where things must live

- **This repo folder is relocatable** — put it anywhere *except* inside a
  cloud-synced folder (OneDrive/SharePoint). Git and cloud sync corrupt each
  other's working files. `C:\Users\<you>\Apps\Workup Search` is a good spot.
- **The index database is never in the repo.** It lives in `%LOCALAPPDATA%`
  because SharePoint/OneDrive sync corrupts SQLite mid-write. A fresh clone
  rebuilds it on the first `python index.py` run.
- **The Workups `.docx` corpus** stays on its SharePoint library path; the
  code only needs the path to it (set in `config.py`).

## Citations

Citations are detected at preview time and linked to **live** Westlaw/Lexis
search URLs built on the fly (rot-proof). There is no stored link cache.
