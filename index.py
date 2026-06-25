"""
index.py - Workup Document Indexer
"""

import os
import sys
import sqlite3
import zipfile
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime

# First run after a fresh clone has no config.py — create it from the template.
import shutil
_HERE = os.path.dirname(os.path.abspath(__file__))
if not os.path.isfile(os.path.join(_HERE, "config.py")):
    _example = os.path.join(_HERE, "config.example.py")
    if os.path.isfile(_example):
        shutil.copyfile(_example, os.path.join(_HERE, "config.py"))
try:
    from config import WORKUPS_FOLDER, DATABASE_FILE
except ImportError:
    sys.exit("Missing config.py and config.example.py — restore them from the repo.")

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def long_path(p):
    prefix = "\\\\?\\"
    if p.startswith(prefix):
        return p
    return prefix + os.path.abspath(p)


def is_locally_available(path):
    """Return True only if the file is fully present on local disk.
    OneDrive Files On-Demand cloud-only placeholders report as existing via
    os.path.exists() but carry special reparse-point attributes. We check for
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS (0x400000) and
    FILE_ATTRIBUTE_RECALL_ON_OPEN (0x40000) to detect them.
    Falls back to True on any error so we never accidentally delete a good record.
    """
    try:
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(long_path(path))
        if attrs == -1:      # INVALID_FILE_ATTRIBUTES — file genuinely not found
            return False
        if attrs & 0x400000: # RECALL_ON_DATA_ACCESS — cloud-only placeholder
            return False
        if attrs & 0x40000:  # RECALL_ON_OPEN — older placeholder flag
            return False
        return True
    except Exception:
        return True          # safe fallback: don't delete if we can't tell


def extract_text_from_docx(path):
    """Extract plain text for FTS indexing (no formatting)."""
    try:
        with zipfile.ZipFile(path, "r") as z:
            if "word/document.xml" not in z.namelist():
                return ""
            with z.open("word/document.xml") as f:
                tree = ET.parse(f)
        root = tree.getroot()
        paragraphs = []
        for para in root.iter(f"{WORD_NS}p"):
            runs = [node.text for node in para.iter(f"{WORD_NS}t") if node.text]
            text = "".join(runs).strip()
            if text:
                paragraphs.append(text)
        return "\n".join(paragraphs)
    except Exception as e:
        return f"[Error reading file: {e}]"


def extract_html_from_docx(path):
    """Extract document content as HTML, preserving paragraphs, spacing, italics, bold."""
    try:
        with zipfile.ZipFile(path, "r") as z:
            if "word/document.xml" not in z.namelist():
                return ""
            with z.open("word/document.xml") as f:
                tree = ET.parse(f)
        root = tree.getroot()
        html_parts = []

        for para in root.iter(f"{WORD_NS}p"):
            pPr    = para.find(f"{WORD_NS}pPr")
            style  = ""
            space_before = 0
            if pPr is not None:
                pStyle = pPr.find(f"{WORD_NS}pStyle")
                if pStyle is not None:
                    style = pStyle.get(f"{WORD_NS}val", "")
                spacing = pPr.find(f"{WORD_NS}spacing")
                if spacing is not None:
                    space_before = int(spacing.get(f"{WORD_NS}before", 0) or 0)

            inline = []
            for run in para.iter(f"{WORD_NS}r"):
                rPr       = run.find(f"{WORD_NS}rPr")
                is_bold   = False
                is_italic = False
                is_under  = False
                if rPr is not None:
                    b = rPr.find(f"{WORD_NS}b")
                    i = rPr.find(f"{WORD_NS}i")
                    u = rPr.find(f"{WORD_NS}u")
                    # A <w:b> or <w:i> element with w:val="0" explicitly turns OFF the property
                    is_bold   = b is not None and b.get(f"{WORD_NS}val", "1") not in ("0", "false")
                    is_italic = i is not None and i.get(f"{WORD_NS}val", "1") not in ("0", "false")
                    is_under  = u is not None and u.get(f"{WORD_NS}val", "none") not in ("0", "false", "none")

                text = "".join(
                    node.text for node in run.iter(f"{WORD_NS}t") if node.text
                ).replace("\xa0", " ")
                if not text:
                    continue

                text = text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                if is_bold and is_italic:
                    text = f"<strong><em>{text}</em></strong>"
                elif is_bold:
                    text = f"<strong>{text}</strong>"
                elif is_italic:
                    text = f"<em>{text}</em>"
                if is_under:
                    text = f"<u>{text}</u>"
                inline.append(text)

            text_content = "".join(inline).strip()

            if not text_content:
                # Preserve empty paragraphs as spacing
                html_parts.append('<p class="sp"></p>')
                continue

            style_lower = style.lower()
            if style_lower in ("heading1",):
                html_parts.append(f"<h1>{text_content}</h1>")
            elif style_lower in ("heading2",):
                html_parts.append(f"<h2>{text_content}</h2>")
            elif style_lower in ("heading3",):
                html_parts.append(f"<h3>{text_content}</h3>")
            elif space_before >= 200:
                html_parts.append(f'<p class="spaced">{text_content}</p>')
            else:
                html_parts.append(f"<p>{text_content}</p>")

        return "\n".join(html_parts)
    except Exception as e:
        return f"<p>[Error reading file: {e}]</p>"


def build_index():
    if not os.path.isdir(WORKUPS_FOLDER):
        print(f"\nERROR: Could not find folder:\n  {WORKUPS_FOLDER}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print("  Workup Document Indexer")
    print(f"{'='*60}")
    print(f"  Scanning: {WORKUPS_FOLDER}")
    print(f"  Database: {DATABASE_FILE}")
    print(f"{'='*60}\n")

    # Ensure the database directory exists (in case it's on a non-default path like AppData)
    os.makedirs(os.path.dirname(DATABASE_FILE), exist_ok=True)

    conn = sqlite3.connect(long_path(DATABASE_FILE))
    conn.row_factory = sqlite3.Row   # enables r["column_name"] access throughout
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            folder      TEXT NOT NULL,
            filename    TEXT NOT NULL,
            filepath    TEXT NOT NULL UNIQUE,
            content     TEXT,
            html        TEXT,
            indexed_at  TEXT NOT NULL,
            filesize    INTEGER,
            filehash    TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts
        USING fts5(folder, filename, content, content=documents, content_rowid=id)
    """)
    conn.commit()
    # Migrate existing databases — add html column if not present
    try:
        conn.execute("ALTER TABLE documents ADD COLUMN html TEXT")
        conn.commit()
        print("  (Migrated database to add HTML column)")
    except Exception:
        pass  # Column already exists

    # Migrate — add filesize and filehash columns if not present
    for col in ("filesize INTEGER", "filehash TEXT"):
        try:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {col}")
            conn.commit()
        except Exception:
            pass

    now = datetime.now().isoformat(timespec="seconds")
    added = updated = skipped = errors = 0

    folders = sorted([
        f for f in os.listdir(WORKUPS_FOLDER)
        if os.path.isdir(os.path.join(WORKUPS_FOLDER, f))
    ])

    for folder_name in folders:
        folder_path = os.path.join(WORKUPS_FOLDER, folder_name)

        try:
            all_files = os.listdir(long_path(folder_path))
        except OSError as e:
            print(f"  [{folder_name}] WARNING: Could not list folder - {e}")
            errors += 1
            continue

        files = [f for f in all_files if f.lower().endswith(".docx") and not f.startswith("~$")]
        if not files:
            continue

        print(f"  [{folder_name}] - {len(files)} file(s)")

        for filename in files:
            filepath    = os.path.join(folder_path, filename)
            filepath_lp = long_path(filepath)

            row = conn.execute(
                "SELECT id, indexed_at, html, filesize, filehash FROM documents WHERE filepath = ?", (filepath,)
            ).fetchone()

            try:
                src_size = os.path.getsize(filepath_lp)
            except (FileNotFoundError, OSError):
                print(f"    SKIPPED (not accessible - OneDrive not synced or path too long):")
                print(f"      {filename}")
                errors += 1
                continue

            # Skip only if html is present AND size+hash match (timestamps are unreliable
            # with SharePoint/OneDrive sync, which can alter mtime independently of edits)
            if row and row[2]:  # html present
                if row[3] == src_size:  # same size — check hash
                    try:
                        with open(filepath_lp, "rb") as f:
                            src_hash = hashlib.md5(f.read()).hexdigest()
                    except OSError:
                        src_hash = None
                    if src_hash and row[4] == src_hash:
                        skipped += 1
                        continue

            content = extract_text_from_docx(filepath_lp)
            if content.startswith("[Error"):
                print(f"    WARNING: {filename}: {content}")
                errors += 1
                continue

            try:
                with open(filepath_lp, "rb") as f:
                    src_hash = hashlib.md5(f.read()).hexdigest()
            except OSError:
                src_hash = None

            if row:
                html = extract_html_from_docx(filepath_lp)
                conn.execute("UPDATE documents SET content=?, html=?, indexed_at=?, filesize=?, filehash=? WHERE id=?",
                             (content, html, now, src_size, src_hash, row[0]))
                conn.execute("DELETE FROM docs_fts WHERE rowid=?", (row[0],))
                conn.execute("INSERT INTO docs_fts(rowid, folder, filename, content) VALUES (?,?,?,?)",
                             (row[0], folder_name, filename, content))
                updated += 1
            else:
                html = extract_html_from_docx(filepath_lp)
                cur = conn.execute(
                    "INSERT INTO documents (folder, filename, filepath, content, html, indexed_at, filesize, filehash) VALUES (?,?,?,?,?,?,?,?)",
                    (folder_name, filename, filepath, content, html, now, src_size, src_hash))
                conn.execute("INSERT INTO docs_fts(rowid, folder, filename, content) VALUES (?,?,?,?)",
                             (cur.lastrowid, folder_name, filename, content))
                added += 1

        conn.commit()

    # Remove database records for files that no longer exist on disk.
    # Uses is_locally_available() instead of os.path.exists() because OneDrive
    # Files On-Demand placeholders return True from os.path.exists() even after
    # the source file has been deleted — causing stale records to survive cleanup.
    deleted = 0
    all_rows = conn.execute("SELECT id, filepath, filename FROM documents").fetchall()
    for r in all_rows:
        if not is_locally_available(r["filepath"]):
            conn.execute("DELETE FROM docs_fts WHERE rowid=?", (r["id"],))
            conn.execute("DELETE FROM documents WHERE id=?", (r["id"],))
            print(f"  Removed (file deleted): {r['filename']}")
            deleted += 1
    if deleted:
        conn.commit()

    conn.execute("INSERT INTO docs_fts(docs_fts) VALUES('optimize')")
    conn.commit()
    conn.close()

    print(f"\n{'='*60}")
    print(f"  Done!")
    print(f"  Added:               {added}")
    print(f"  Updated:             {updated}")
    print(f"  Skipped (unchanged): {skipped}")
    print(f"  Removed:             {deleted}")
    print(f"  Errors/Skipped:      {errors}")
    print(f"\n  Database: {DATABASE_FILE}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    build_index()
    input("Press Enter to close...")
