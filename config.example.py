"""
config.example.py — default paths for Workup Search (committed template).

On a fresh clone there is no `config.py` (it is gitignored). The app creates
`config.py` from this file automatically on first run, so a clone is runnable
with no manual steps. `config.py` is the per-machine override: once it exists,
pulls never touch it, so you can change paths on one machine without affecting
the repo or other machines.

To change the defaults for every new clone, edit this file and commit it.
"""

import os

# ── Folder of motion "workup" .docx files (indexed corpus) ──────────────────
# Live document set on the SharePoint-synced library.
WORKUPS_FOLDER = r"C:\Users\ZCoderre\Los Angeles Superior Court\Research Attorney and Law Clerk Unit - Zachary Coderre\Workups"

# ── SQLite FTS5 index database ──────────────────────────────────────────────
# MUST stay off any cloud-synced path. SharePoint/OneDrive sync corrupts
# SQLite's atomic writes mid-transaction. %LOCALAPPDATA% is local-only and
# username-independent, so this works on any account without editing.
DATABASE_FILE = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local")),
    "WorkupSearch", "workups_index.db",
)

