"""
app.py - Workup Search Server
Run this, then open workups.html in your browser.
Keep this window open while using the search interface.

Usage:
    python app.py
"""

import os
import sys
import json
import sqlite3
import subprocess
import threading
import logging
import traceback
from datetime import date
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
try:
    import winreg as _winreg
except ImportError:
    _winreg = None

# Debug log — written alongside this script
_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workup_debug.log")
logging.basicConfig(
    filename=_LOG_PATH,
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_log = logging.getLogger("workup")

# ── CONFIGURATION ──────────────────────────────────────────────────────────────────────────────
# First run after a fresh clone has no config.py (it is gitignored). Create it
# from the committed template so the app runs with zero manual setup.
import shutil
_HERE = os.path.dirname(os.path.abspath(__file__))
if not os.path.isfile(os.path.join(_HERE, "config.py")):
    _example = os.path.join(_HERE, "config.example.py")
    if os.path.isfile(_example):
        shutil.copyfile(_example, os.path.join(_HERE, "config.py"))
try:
    from config import DATABASE_FILE
except ImportError:
    sys.exit("Missing config.py and config.example.py — restore them from the repo.")
PORT = 54321
# ───────────────────────────────────────────────────────────────────────────────

# Import citation extractor (must live in the same directory as app.py)
try:
    from citation_extractor import extract_citations
    EXTRACTOR_AVAILABLE = True
except ImportError:
    EXTRACTOR_AVAILABLE = False
    print("  WARNING: citation_extractor.py not found — /citations endpoint disabled.")


def long_path(p):
    """Prepend Windows long-path prefix. No-op on non-Windows."""
    if os.name != "nt":
        return p
    prefix = "\\\\?\\"
    if p.startswith(prefix):
        return p
    return prefix + os.path.abspath(p)



# ── CITATION ENDPOINT HANDLERS ──────────────────────────────────────────────────────────
def get_citations_for_doc(doc_id):
    """Extract citations for one document.

    Returns the extractor output directly. The client builds live Lexis/
    Westlaw search URLs from the lexis_search_term / westlaw_search_cite /
    provider_lock fields; there is no stored link repository.
    """
    if not EXTRACTOR_AVAILABLE:
        return {"error": "citation_extractor.py not available", "citations": []}
    conn = get_db()
    row  = conn.execute("SELECT html FROM documents WHERE id=?", (doc_id,)).fetchone()
    conn.close()
    if not row or not row["html"]:
        return {"citations": []}
    result = []
    for c in extract_citations(row["html"]):
        d = c.to_dict()
        d.pop("match_start", None)
        d.pop("match_end",   None)
        d.pop("match_text",  None)
        result.append(d)
    return {"citations": result}


def get_db():
    conn = sqlite3.connect(long_path(DATABASE_FILE))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tags_schema(conn):
    """
    Create the tags table if it doesn't exist.
    Tags are keyed by filepath (not id) so they survive re-indexing.
    A separate tag_names table gives each tag a stable color index.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tag_names (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            color_index INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS doc_tags (
            filepath    TEXT NOT NULL,
            tag_name    TEXT NOT NULL,
            PRIMARY KEY (filepath, tag_name)
        )
    """)
    conn.commit()


def get_all_tags(conn):
    """Return list of {name, color_index, count} for every tag."""
    ensure_tags_schema(conn)
    rows = conn.execute("""
        SELECT tn.name, tn.color_index, COUNT(dt.filepath) as cnt
        FROM tag_names tn
        LEFT JOIN doc_tags dt ON dt.tag_name = tn.name
        GROUP BY tn.name
        ORDER BY tn.name
    """).fetchall()
    return [{"name": r["name"], "color_index": r["color_index"], "count": r["cnt"]} for r in rows]


def get_tags_for_docs(conn, filepaths):
    """Return dict of filepath -> [tag_name, ...] for the given filepaths."""
    if not filepaths:
        return {}
    ensure_tags_schema(conn)
    placeholders = ",".join("?" * len(filepaths))
    rows = conn.execute(
        f"SELECT filepath, tag_name FROM doc_tags WHERE filepath IN ({placeholders})",
        filepaths
    ).fetchall()
    result = {fp: [] for fp in filepaths}
    for r in rows:
        if r["filepath"] in result:
            result[r["filepath"]].append(r["tag_name"])
    return result


def set_doc_tag(filepath, tag_name, action):
    """
    Add or remove a tag on a document.
    action: 'add' or 'remove'
    New tag names are auto-assigned the next available color_index.
    Returns updated tag list for the doc.
    """
    conn = get_db()
    ensure_tags_schema(conn)

    if action == "add":
        # Insert tag name if new, assigning next color slot
        existing = conn.execute(
            "SELECT id FROM tag_names WHERE name=?", (tag_name,)
        ).fetchone()
        if not existing:
            max_row = conn.execute("SELECT MAX(color_index) as m FROM tag_names").fetchone()
            next_color = (max_row["m"] + 1) if max_row["m"] is not None else 0
            conn.execute(
                "INSERT INTO tag_names (name, color_index) VALUES (?,?)",
                (tag_name, next_color)
            )
        # Insert doc-tag link (ignore if already exists)
        conn.execute(
            "INSERT OR IGNORE INTO doc_tags (filepath, tag_name) VALUES (?,?)",
            (filepath, tag_name)
        )

    elif action == "remove":
        conn.execute(
            "DELETE FROM doc_tags WHERE filepath=? AND tag_name=?",
            (filepath, tag_name)
        )
        # If no docs use this tag any more, remove it from tag_names too
        remaining = conn.execute(
            "SELECT COUNT(*) as c FROM doc_tags WHERE tag_name=?", (tag_name,)
        ).fetchone()
        if remaining["c"] == 0:
            conn.execute("DELETE FROM tag_names WHERE name=?", (tag_name,))

    conn.commit()

    # Return fresh tag list for this doc
    rows = conn.execute(
        "SELECT tag_name FROM doc_tags WHERE filepath=? ORDER BY tag_name",
        (filepath,)
    ).fetchall()
    conn.close()
    return [r["tag_name"] for r in rows]


def attach_tags_to_results(conn, results):
    """Mutate result dicts to add a 'tags' list to each."""
    filepaths = [r["filepath"] for r in results]
    tag_map = get_tags_for_docs(conn, filepaths)
    for r in results:
        r["tags"] = tag_map.get(r["filepath"], [])
    return results


def do_search(query, folder=None, include_terms=None, exclude_terms=None,
              tag_filters=None, limit=500):
    """Search documents. include_terms/exclude_terms are lists of additional FTS terms.
       tag_filters is a list of tag names; results must have ALL of them (AND logic)."""
    conn = get_db()
    ensure_tags_schema(conn)

    def make_fts(q):
        # Strip surrounding quotes the user may have typed; we wrap in FTS phrase quotes ourselves
        q = q.strip().strip('"\'\u201c\u201d\u2018\u2019')
        return f'"{q.replace(chr(34), chr(34)+chr(34))}"'
    def strip_quotes(t):
        return t.strip().strip('"\'\u201c\u201d\u2018\u2019')

    fts_parts = [make_fts(query)]
    for t in (include_terms or []):
        if t.strip():
            fts_parts.append(make_fts(t.strip()))
    fts_query = " ".join(fts_parts)

    try:
        if folder and folder != "all":
            rows = conn.execute("""
                SELECT d.id, d.folder, d.filename, d.filepath, d.content, LENGTH(d.content) AS char_count, rank
                FROM docs_fts f
                JOIN documents d ON d.id = f.rowid
                WHERE docs_fts MATCH ? AND d.folder = ? AND d.folder != ?
                ORDER BY rank LIMIT ?
            """, (fts_query, folder, SUMMARIES_FOLDER, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT d.id, d.folder, d.filename, d.filepath, d.content, LENGTH(d.content) AS char_count, rank
                FROM docs_fts f
                JOIN documents d ON d.id = f.rowid
                WHERE docs_fts MATCH ? AND d.folder != ?
                ORDER BY rank LIMIT ?
            """, (fts_query, SUMMARIES_FOLDER, limit)).fetchall()
    except sqlite3.OperationalError:
        like = f"%{query}%"
        if folder and folder != "all":
            rows = conn.execute("""
                SELECT id, folder, filename, filepath, content, LENGTH(content) AS char_count, 0 as rank
                FROM documents
                WHERE (content LIKE ? OR filename LIKE ?) AND folder = ? AND folder != ?
                LIMIT ?
            """, (like, like, folder, SUMMARIES_FOLDER, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, folder, filename, filepath, content, LENGTH(content) AS char_count, 0 as rank
                FROM documents
                WHERE (content LIKE ? OR filename LIKE ?) AND folder != ?
                LIMIT ?
            """, (like, like, SUMMARIES_FOLDER, limit)).fetchall()

    results = []
    terms = query.lower().split()
    for r in rows:
        try:
            doc_content  = (r["content"] or "").lower()
            doc_filename = r["filename"].lower()
            haystack     = doc_content + " " + doc_filename

            if any(strip_quotes(t).lower() in haystack for t in (exclude_terms or []) if t.strip()):
                continue

            snippet = make_snippet(r["content"] or "", terms)
            results.append({
                "id":         r["id"],
                "folder":     r["folder"],
                "filename":   r["filename"],
                "filepath":   r["filepath"],
                "snippet":    snippet,
                "char_count": r["char_count"] or 0,
            })
        except Exception:
            _log.error("Error processing row id=%s filepath=%s for query=%r",
                       r["id"] if "id" in r.keys() else "?",
                       r["filepath"] if "filepath" in r.keys() else "?",
                       query, exc_info=True)
            continue

    attach_tags_to_results(conn, results)

    # Also include docs whose tags match the search query (tag-as-search)
    # Find docs tagged with any tag that contains the query term
    try:
        tag_rows = conn.execute("""
            SELECT d.id, d.folder, d.filename, d.filepath, d.content, LENGTH(d.content) AS char_count
            FROM doc_tags dt
            JOIN documents d ON d.filepath = dt.filepath
            WHERE LOWER(dt.tag_name) LIKE ? AND d.folder != ?
        """, (f"%{query.lower()}%", SUMMARIES_FOLDER)).fetchall()

        existing_fps = {r["filepath"] for r in results}
        for r in tag_rows:
            if r["filepath"] not in existing_fps:
                if folder and folder != "all" and r["folder"] != folder:
                    continue
                if any(strip_quotes(t).lower() in (r["content"] or "").lower() + " " + r["filename"].lower()
                       for t in (exclude_terms or []) if t.strip()):
                    continue
                results.append({
                    "id":         r["id"],
                    "folder":     r["folder"],
                    "filename":   r["filename"],
                    "filepath":   r["filepath"],
                    "snippet":    "",
                    "char_count": r["char_count"] or 0,
                })
                existing_fps.add(r["filepath"])
    except Exception:
        pass

    # Re-attach tags for any newly added docs
    attach_tags_to_results(conn, results)

    # Apply tag filter (AND): keep only docs that have every required tag
    if tag_filters:
        tag_set = set(tag_filters)
        results = [r for r in results if tag_set.issubset(set(r["tags"]))]

    conn.close()
    return results


def do_browse(folder=None, tag_filters=None, include_terms=None, exclude_terms=None):
    """Return all documents, optionally filtered by folder, tags, and inc/exc terms."""
    conn = get_db()
    ensure_tags_schema(conn)

    if folder and folder != "all":
        rows = conn.execute(
            "SELECT id, folder, filename, filepath, content, LENGTH(content) AS char_count FROM documents WHERE folder=? AND folder!=? ORDER BY filename",
            (folder, SUMMARIES_FOLDER)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, folder, filename, filepath, content, LENGTH(content) AS char_count FROM documents WHERE folder!=? ORDER BY folder, filename",
            (SUMMARIES_FOLDER,)
        ).fetchall()

    results = []
    for r in rows:
        doc_content  = (r["content"] or "").lower()
        doc_filename = r["filename"].lower()
        haystack     = doc_content + " " + doc_filename
        if include_terms:
            if not all(strip_quotes(t).lower() in haystack for t in include_terms if t.strip()):
                continue
        if exclude_terms:
            if any(strip_quotes(t).lower() in haystack for t in exclude_terms if t.strip()):
                continue
        results.append({"id": r["id"], "folder": r["folder"], "filename": r["filename"],
                        "filepath": r["filepath"], "snippet": "",
                        "char_count": r["char_count"] or 0})

    attach_tags_to_results(conn, results)

    # Apply tag filter (AND)
    if tag_filters:
        tag_set = set(tag_filters)
        results = [r for r in results if tag_set.issubset(set(r["tags"]))]

    conn.close()
    return results


def make_snippet(text, terms, chars=500):
    if not text:
        return ""
    lower = text.lower()
    best  = 0
    for t in terms:
        pos = lower.find(t)
        if pos != -1:
            best = max(0, pos - 100)
            break
    excerpt = text[best:best + chars]
    if best > 0:
        excerpt = "…" + excerpt
    if best + chars < len(text):
        excerpt += "…"
    return excerpt.replace("\n", " ").strip()


SUMMARIES_FOLDER = "Summaries"

def get_folders():
    conn = get_db()
    rows = conn.execute(
        "SELECT folder, COUNT(*) as cnt FROM documents GROUP BY folder ORDER BY folder"
    ).fetchall()
    conn.close()
    return [{"folder": r["folder"], "count": r["cnt"]} for r in rows
            if r["folder"] != SUMMARIES_FOLDER]


def get_summary_for_doc(src_filepath):
    """
    Given a source document filepath, look up its Copilot summary in the DB.
    The summary file lives in the Summaries subfolder with ' (Summary)' appended
    to the base filename, e.g.:
      source:  ...\Motions\Smith v Jones - MSJ.docx
      summary: ...\Summaries\Smith v Jones - MSJ (Summary).docx
    Returns {"text": <plain text>} or {"text": None} if not found.
    """
    try:
        base   = os.path.splitext(os.path.basename(src_filepath))[0]
        root   = os.path.dirname(os.path.dirname(src_filepath))  # Workups root: up from motion folder
        sum_fp = os.path.join(root, SUMMARIES_FOLDER, base + " (Summary).docx")
        conn   = get_db()
        row    = conn.execute(
            "SELECT content FROM documents WHERE filepath = ?", (sum_fp,)
        ).fetchone()
        conn.close()
        if row and row["content"]:
            return {"text": row["content"]}
        return {"text": None}
    except Exception as e:
        _log.debug("get_summary_for_doc error: %s", e)
        return {"text": None}


def get_full_content(doc_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT content, html FROM documents WHERE id=?", (doc_id,)).fetchone()
        conn.close()
        if not row:
            return {"text": "", "html": ""}
        return {"text": row["content"] or "", "html": row["html"] or ""}
    except Exception:
        try:
            row = conn.execute("SELECT content FROM documents WHERE id=?", (doc_id,)).fetchone()
        except Exception:
            row = None
        conn.close()
        return {"text": (row["content"] if row else "") or "", "html": ""}


def open_file(filepath):
    clean = filepath
    for prefix in ("\\\\?\\", "\\\\?\\UNC\\"):
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
            break

    errors = []

    try:
        os.startfile(clean)
        return {"ok": True}
    except Exception as e:
        errors.append(f"startfile: {e}")

    try:
        subprocess.Popen(f'start "" "{clean}"', shell=True)
        return {"ok": True}
    except Exception as e:
        errors.append(f"start cmd: {e}")

    try:
        subprocess.Popen(["cmd", "/c", "start", "", clean])
        return {"ok": True}
    except Exception as e:
        errors.append(f"cmd start: {e}")

    return {"ok": False, "error": " | ".join(errors)}


# ── REGISTRY PREFERENCE HELPERS ─────────────────────────────────────────────

REG_KEY     = r"Software\WorkupSearch"
REG_VALUE   = "citeServicePref"
REG_DEFAULT = "lexis"

def get_cite_pref():
    if _winreg is None:
        return REG_DEFAULT
    try:
        key = _winreg.OpenKey(_winreg.HKEY_CURRENT_USER, REG_KEY)
        val, _ = _winreg.QueryValueEx(key, REG_VALUE)
        _winreg.CloseKey(key)
        return val if val in ("lexis", "westlaw") else REG_DEFAULT
    except Exception:
        return REG_DEFAULT

def set_cite_pref(value):
    if _winreg is None:
        return False
    if value not in ("lexis", "westlaw"):
        return False
    try:
        key = _winreg.CreateKey(_winreg.HKEY_CURRENT_USER, REG_KEY)
        _winreg.SetValueEx(key, REG_VALUE, 0, _winreg.REG_SZ, value)
        _winreg.CloseKey(key)
        return True
    except Exception:
        return False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress request logging

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        try:
            self._do_GET_inner()
        except Exception as e:
            tb = traceback.format_exc()
            _log.error("Unhandled exception in do_GET for %s\n%s", self.path, tb)
            try:
                self.send_json({"error": str(e), "traceback": tb, "path": self.path}, 500)
            except Exception:
                # If we can't even send the error (e.g. headers already sent), give up cleanly
                _log.error("Failed to send 500 response", exc_info=True)

    def _do_GET_inner(self):
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)

        if parsed.path == "/folders":
            self.send_json(get_folders())

        elif parsed.path == "/tags":
            # Returns [{name, color_index, count}] for all known tags
            conn = get_db()
            ensure_tags_schema(conn)
            result = get_all_tags(conn)
            conn.close()
            self.send_json(result)

        elif parsed.path == "/tag/set":
            # ?filepath=...&tag=...&action=add|remove
            # filepath passed raw (no encoding) — read directly from query string
            raw_qs   = parsed.query
            # Parse filepath and tag carefully from raw query string
            # Use standard parse_qs for tag and action; filepath may contain special chars
            tag      = unquote(qs.get("tag",    [""])[0]).strip()
            action   = unquote(qs.get("action", [""])[0]).strip()
            # Extract filepath: everything after "filepath=" up to "&tag=" or end
            fp_match = ""
            parts    = raw_qs.split("&")
            for part in parts:
                if part.startswith("filepath="):
                    fp_match = part[9:]  # strip "filepath=" prefix
                    break
            filepath = unquote(fp_match)
            if not filepath or not tag or action not in ("add", "remove"):
                self.send_json({"ok": False, "error": "Missing filepath, tag, or action"}, 400)
                return
            new_tags = set_doc_tag(filepath, tag, action)
            self.send_json({"ok": True, "tags": new_tags})

        elif parsed.path == "/search":
            query  = unquote(qs.get("q",      [""])[0]).strip()
            folder = unquote(qs.get("folder", ["all"])[0]).strip()
            inc    = [unquote(t) for t in qs.get("inc", [])]
            exc    = [unquote(t) for t in qs.get("exc", [])]
            tags   = [unquote(t) for t in qs.get("tag", [])]
            if not query:
                self.send_json([])
            else:
                self.send_json(do_search(query, folder, inc, exc, tags or None))

        elif parsed.path == "/open":
            filepath = unquote(qs.get("path", [""])[0])
            self.send_json(open_file(filepath))

        elif parsed.path == "/content":
            doc_id = int(qs.get("id", [0])[0])
            self.send_json(get_full_content(doc_id))

        elif parsed.path == "/browse":
            folder = unquote(qs.get("folder", ["all"])[0]).strip()
            tags   = [unquote(t) for t in qs.get("tag", [])]
            inc    = [unquote(t) for t in qs.get("inc", [])]
            exc    = [unquote(t) for t in qs.get("exc", [])]
            self.send_json(do_browse(folder, tags or None, inc or None, exc or None))

        elif parsed.path == "/ping":
            self.send_json({"ok": True})

        elif parsed.path == "/getpref":
            self.send_json({"citeServicePref": get_cite_pref()})

        elif parsed.path == "/setpref":
            val = qs.get("value", [""])[0].strip().lower()
            ok  = set_cite_pref(val)
            self.send_json({"ok": ok, "citeServicePref": get_cite_pref()})


        # ── Citation endpoints ───────────────────────────────────────────────────────────────────

        elif parsed.path == "/citations":
            # GET /citations?id=N  — extract + resolve citations for one document
            doc_id = int(qs.get("id", [0])[0])
            if not doc_id:
                self.send_json({"error": "id parameter required", "citations": []}, 400)
            else:
                self.send_json(get_citations_for_doc(doc_id))

        elif parsed.path == "/summary":
            # GET /summary?filepath=<source_filepath>
            # Constructs the summary path and returns its plain-text content from the DB.
            src_path = unquote(qs.get("filepath", [""])[0])
            if not src_path:
                self.send_json({"text": None})
            else:
                self.send_json(get_summary_for_doc(src_path))

        else:
            self.send_response(404)
            self.end_headers()


    def do_POST(self):
        try:
            self._do_POST_inner()
        except Exception as e:
            tb = traceback.format_exc()
            _log.error("Unhandled exception in do_POST for %s\n%s", self.path, tb)
            try:
                self.send_json({"error": str(e), "traceback": tb, "path": self.path}, 500)
            except Exception:
                _log.error("Failed to send 500 response", exc_info=True)

    def _do_POST_inner(self):
        parsed = urlparse(self.path)

        self.send_response(404)
        self.end_headers()


def main():
    if not os.path.isfile(long_path(DATABASE_FILE)):
        print("\nERROR: Database not found. Please run index.py first.\n")
        input("Press Enter to close...")
        sys.exit(1)

    # Ensure tags schema exists on startup
    conn = get_db()
    ensure_tags_schema(conn)
    conn.close()

    print(f"\n{'='*55}")
    print("  Workup Search Server")
    print(f"{'='*55}")
    print(f"  Running at http://localhost:{PORT}")
    print(f"  Open workups.html in your browser to search.")
    print(f"  Keep this window open while searching.")
    print(f"  Press Ctrl+C to stop.")
    print(f"{'='*55}")
    print(f"  Citations: {'enabled' if EXTRACTOR_AVAILABLE else 'DISABLED (citation_extractor.py missing)'}")
    print(f"{'='*55}\n")

    server = HTTPServer(("localhost", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.\n")


if __name__ == "__main__":
    main()
