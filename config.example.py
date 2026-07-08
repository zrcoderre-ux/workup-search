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
# MUST stay off any cloud-synced path AND out of %APPDATA% / %LOCALAPPDATA%.
# Two independent reasons:
#   1. SharePoint/OneDrive sync corrupts SQLite's atomic writes mid-transaction,
#      so the DB can never live on a synced path.
#   2. The Microsoft Store build of Python runs in an app container that
#      transparently redirects writes under %LOCALAPPDATA% into a hidden
#      per-package sandbox (…\AppData\Local\Packages\PythonSoftwareFoundation.
#      Python.<ver>_…\LocalCache\Local\…). The DB still works there, but the
#      path the code prints no longer matches where the file physically lives,
#      and it's silently orphaned on a Python version change (3.12 -> 3.13).
# A folder in the user-profile root is NOT virtualized by the Store sandbox, is
# still local-only (SharePoint/OneDrive don't sync it), and is
# username-independent — so the path the code reports is the real, findable one.
DATABASE_FILE = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")),
    "WorkupSearch", "workups_index.db",
)

