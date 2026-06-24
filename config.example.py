"""
config.example.py — machine-specific paths for Workup Search.

SETUP: copy this file to `config.py` (which is gitignored) and edit the
values below for this machine. The repo itself never contains real paths,
so the working tree stays clean and relocatable.

    copy config.example.py config.py      (Windows: copy / PowerShell: cp)

Nothing else needs editing to move the project folder — the launcher and
the Python scripts resolve their own location automatically.
"""

import os

# ── Folder of motion "workup" .docx files (indexed corpus) ──────────────────
# This is your live document set on the SharePoint-synced library. Point it at
# wherever the Workups folder actually lives on this machine.
WORKUPS_FOLDER = r"C:\Users\<USERNAME>\Los Angeles Superior Court\Research Attorney and Law Clerk Unit - <USERNAME>\Workups"

# ── SQLite FTS5 index database ──────────────────────────────────────────────
# MUST live on a NON cloud-synced path. SharePoint/OneDrive sync corrupts
# SQLite's atomic writes mid-transaction. %LOCALAPPDATA% is local-only and
# username-independent, so this default works for any account without editing.
DATABASE_FILE = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local")),
    "WorkupSearch", "workups_index.db",
)
