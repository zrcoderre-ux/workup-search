"""
test_search_logic.py — search and narrow-results semantics.

Pins the contracts that were silently broken and made common searches return
zero results:
  1. Refine chips are substring filters ("results containing…") in BOTH
     search and browse mode. They must never be turned into whole-token FTS
     terms, where a partial word ("summ") matches nothing.
  2. A trailing * on a bare search word is a prefix search (neglig* finds
     negligence); FTS operator words are otherwise matched literally.
  3. .docx extraction must separate words split by tabs, manual line breaks,
     and carriage returns — captions/headings like MOTION<tab>FOR<tab>SUMMARY
     JUDGMENT used to index as one giant unsearchable token — and must
     include footnote/endnote text.
  4. LIKE wildcards typed into refine chips (%, _) are matched literally.

Run: python test_search_logic.py   (exits non-zero on any failure)
"""

import os
import sqlite3
import tempfile
import zipfile

import app
import index as indexer

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got : {got!r}")
        print(f"        want: {want!r}")
        fails += 1


def names(rows):
    return sorted(r["filename"] for r in rows)


# ── temp corpus wired through app.py's real search functions ────────────────
_tmpdir = tempfile.mkdtemp()
app.DATABASE_FILE = os.path.join(_tmpdir, "test.db")

DOCS = [
    ("Demurrer", "smith-demurrer.docx",
     "The demurrer to the negligence cause of action is sustained. Plaintiff's "
     "complaint fails. Summary of allegations follows. 100% of the claims fail."),
    ("MSJ", "doe-msj.docx",
     "Defendant moves for summary judgment on the negligent hiring claim. "
     "The anti-SLAPP statute does not apply."),
    ("MTS", "roe-mts.docx",
     "The motion to strike punitive damages is granted; malice is required."),
]

conn = sqlite3.connect(app.DATABASE_FILE)
conn.execute("""
    CREATE TABLE documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        folder TEXT NOT NULL, filename TEXT NOT NULL,
        filepath TEXT NOT NULL UNIQUE, content TEXT, html TEXT,
        indexed_at TEXT NOT NULL, filesize INTEGER, filehash TEXT)""")
conn.execute("""
    CREATE VIRTUAL TABLE docs_fts
    USING fts5(folder, filename, content, content=documents, content_rowid=id)""")
for folder, filename, content in DOCS:
    cur = conn.execute(
        "INSERT INTO documents (folder, filename, filepath, content, html, indexed_at)"
        " VALUES (?,?,?,?,?, '2026-01-01')",
        (folder, filename, f"X:\\Workups\\{folder}\\{filename}", content, "<p>x</p>"))
    conn.execute(
        "INSERT INTO docs_fts(rowid, folder, filename, content) VALUES (?,?,?,?)",
        (cur.lastrowid, folder, filename, content))
conn.commit()
conn.close()


print("\n--- query_to_fts contract ---")
check("bare words: implicit AND of phrases",
      app.query_to_fts("summary judgment"), '"summary" "judgment"')
check("quoted text stays one phrase",
      app.query_to_fts('"summary judgment"'), '"summary judgment"')
check("curly quotes work like straight quotes",
      app.query_to_fts("\u201csummary judgment\u201d"), '"summary judgment"')
check("FTS operator words matched literally",
      app.query_to_fts("smith AND jones"), '"smith" "AND" "jones"')
check("trailing * becomes a prefix query",
      app.query_to_fts("neglig*"), '"neglig" *')
check("bare * alone is dropped",
      app.query_to_fts("malice *"), '"malice"')

print("\n--- basic search ---")
check("single word", names(app.do_search("negligence")), ["smith-demurrer.docx"])
check("prefix search neglig* spans negligence+negligent",
      names(app.do_search("neglig*")), ["doe-msj.docx", "smith-demurrer.docx"])
check("multi-word implicit AND",
      names(app.do_search("summary judgment")), ["doe-msj.docx"])
check("quoted phrase", names(app.do_search('"punitive damages"')), ["roe-mts.docx"])
check("filename matches too", names(app.do_search("doe-msj")), ["doe-msj.docx"])

print("\n--- narrow (refine chips): substring semantics in search mode ---")
check("include chip: partial word narrows, not zeroes",
      names(app.do_search("neglig*", include_terms=["summ"])),
      ["doe-msj.docx", "smith-demurrer.docx"])
check("include chip: full word",
      names(app.do_search("neglig*", include_terms=["anti-SLAPP"])),
      ["doe-msj.docx"])
check("include chip: phrase",
      names(app.do_search("neglig*", include_terms=["summary judgment"])),
      ["doe-msj.docx"])
check("exclude chip removes matches",
      names(app.do_search("neglig*", exclude_terms=["anti-SLAPP"])),
      ["smith-demurrer.docx"])
check("chip LIKE wildcards are literal: '100%' only matches literal text",
      names(app.do_search("neglig*", include_terms=["100%"])),
      ["smith-demurrer.docx"])
check("chip '_' is literal, matches nothing here",
      names(app.do_search("neglig*", include_terms=["mal_ce"])), [])

print("\n--- search/browse chip parity ---")
for chip in ("summ", "anti-SLAPP", "100%"):
    s = {r["filepath"] for r in app.do_search("neglig*", include_terms=[chip])}
    b = {r["filepath"] for r in app.do_browse(include_terms=[chip])}
    # every doc kept by search+chip must also be kept by browse+chip
    check(f"chip {chip!r}: search results are a subset of browse results",
          s.issubset(b), True)

print("\n--- docx extraction: separators and footnotes ---")
DOC_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:r><w:t>MOTION</w:t><w:tab/><w:t>FOR</w:t><w:tab/><w:t>SUMMARY</w:t><w:tab/><w:t>JUDGMENT</w:t></w:r></w:p>
<w:p><w:r><w:t>SMITH,</w:t><w:br/><w:t>Plaintiff,</w:t></w:r></w:p>
<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs></w:pPr><w:r><w:t>No spurious tabstop text.</w:t></w:r></w:p>
<w:p><w:r><w:t>pre</w:t><w:noBreakHyphen/><w:t>existing</w:t></w:r></w:p>
</w:body>
</w:document>"""
FOOTNOTES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:footnote w:id="1"><w:p><w:r><w:t>Estoppel argument waived below.</w:t></w:r></w:p></w:footnote>
</w:footnotes>"""

docx_path = os.path.join(_tmpdir, "sample.docx")
with zipfile.ZipFile(docx_path, "w") as z:
    z.writestr("word/document.xml", DOC_XML)
    z.writestr("word/footnotes.xml", FOOTNOTES_XML)

text = indexer.extract_text_from_docx(docx_path)
check("tab-separated caption words stay separate words",
      "MOTION\tFOR\tSUMMARY\tJUDGMENT" in text, True)
check("manual line break separates words", "SMITH,\nPlaintiff," in text, True)
check("tab-stop definitions do not inject separators",
      "No spurious tabstop text." in text, True)
check("noBreakHyphen renders as hyphen", "pre-existing" in text, True)
check("footnote text is indexed", "Estoppel argument waived below." in text, True)

html = indexer.extract_html_from_docx(docx_path)
check("html preview also keeps tabbed words separate",
      "MOTIONFOR" not in html, True)

print("\n" + "=" * 60)
print(f"FAILURES: {fails}")
raise SystemExit(1 if fails else 0)
