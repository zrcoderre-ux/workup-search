"""
test_summary_placeholder.py — a summary document that still holds only the
Copilot prompt is NOT a summary. The prompt text must never be served as
preview text; /summary reports it as a placeholder so the UI can offer the
"Add Summary" button instead.

Run: python test_summary_placeholder.py   (exits non-zero on any failure)
"""

import os

import app

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got : {got!r}")
        print(f"        want: {want!r}")
        fails += 1


# The prompt exactly as it is pasted into an empty summary document, smart
# quotes, non-breaking hyphens and all.
PROMPT = (
    "Write a one-paragraph past-tense summary of this order. Do not include any "
    "references or footnote citations in the Word document. Capitalize \u201cCourt\u201d. "
    "Do not tell me what you produced (i.e., \u201cHere is a one\u2011paragraph past\u2011tense "
    "summary of the order, based solely on the document you provided:\u201d). Do not "
    "mention what other tasks you can complete (i.e., \u201cIf you\u2019d like, I can also "
    "prepare a shorter version, a more formal version, or a version tailored for a "
    "particular filing\u201d.) Your only output should be the one paragraph summary, "
    "footnote-free."
)

SUMMARY = (
    "The Court granted defendant's motion for summary judgment. The Court found "
    "that plaintiff failed to raise a triable issue of material fact as to the "
    "element of causation, and entered judgment accordingly."
)

print("\nPlaceholder detection")
check("the pasted prompt", app.is_summary_placeholder(PROMPT), True)
check("prompt with straight quotes/hyphens",
      app.is_summary_placeholder(PROMPT.replace("\u201c", '"').replace("\u201d", '"')
                                       .replace("\u2011", "-").replace("\u2019", "'")),
      True)
check("prompt broken across lines",
      app.is_summary_placeholder(PROMPT.replace(". ", ".\n")), True)
check("prompt in a different case",
      app.is_summary_placeholder(PROMPT.upper()), True)
check("a real summary", app.is_summary_placeholder(SUMMARY), False)
check("a real summary that mentions a footnote",
      app.is_summary_placeholder(SUMMARY + " The Court's footnote 3 was cited."), False)
check("empty text", app.is_summary_placeholder(""), False)
check("no text at all", app.is_summary_placeholder(None), False)

print("\nSummary path derivation")
src = os.path.join("C:\\Workups", "Motions", "Smith v Jones - MSJ.docx")
check("summary sits in the Summaries folder with ' (Summary)' appended",
      app.summary_path_for_doc(src),
      os.path.join("C:\\Workups", "Summaries", "Smith v Jones - MSJ (Summary).docx"))

print("\nEndpoint payload shape")


class _FakeConn:
    def __init__(self, content):
        self._content = content

    def execute(self, *a):
        content = self._content
        class _Cur:
            def fetchone(self):
                return None if content is None else {"content": content}
        return _Cur()

    def close(self):
        pass


def payload_for(content):
    real = app.get_db
    app.get_db = lambda: _FakeConn(content)
    try:
        return app.get_summary_for_doc(src)
    finally:
        app.get_db = real


sum_fp = app.summary_path_for_doc(src)
check("prompt-only summary is reported as a placeholder with no text",
      payload_for(PROMPT),
      {"text": None, "placeholder": True, "summary_path": sum_fp})
check("a written summary comes back as text",
      payload_for(SUMMARY),
      {"text": SUMMARY, "placeholder": False, "summary_path": sum_fp})
check("a missing summary is neither text nor placeholder",
      payload_for(None),
      {"text": None, "placeholder": False, "summary_path": sum_fp})

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILURE(S)'}\n")
raise SystemExit(1 if fails else 0)
