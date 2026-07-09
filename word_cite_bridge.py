"""
word_cite_bridge.py — Word macro <-> citation_extractor bridge
==============================================================
Called by the CitationLinker Word macro. Reads a paragraph-tagged HTML file
(one <p>...</p> per Word paragraph, in document order) and writes a TSV file
of every detected citation occurrence, so the macro can hyperlink each span
in place.

USAGE
-----
    python word_cite_bridge.py <input_html> <output_tsv> [<repo_json>]

CONTRACT WITH THE MACRO
-----------------------
The macro emits exactly one <p> element per paragraph it iterates, in order.
This bridge enumerates the SAME blocks (via citation_extractor._split_blocks),
so block_index N in the output corresponds to the (N+1)-th paragraph the macro
emitted. Offsets are character indices into the block's normalized plain text;
the macro rebuilds that same normalization to map offsets back to Word ranges.

OUTPUT (UTF-8, one record per line, tab-separated)
--------------------------------------------------
    block_index <TAB> start <TAB> end <TAB> type <TAB> url <TAB> match_text

  block_index : 0-based block (paragraph) index
  start, end  : character offsets into the block's normalized plain text
                (end exclusive, Python slice semantics)
  type        : "case" | "statute" | "rule"
  url         : live provider search URL (search_urls.resolve_url): a Lexis+
                search by default, falling back to Westlaw for cites Lexis
                can't anchor (e.g. WL-only unpublished cases) and for any cite
                whose provider_lock forces Westlaw.
  match_text  : the literal matched text (tabs/newlines flattened to spaces);
                used for the macro's Find fallback and for the link ScreenTip

No deduplication is performed: every occurrence in every paragraph is reported
so the macro links each one. The macro is responsible for skipping spans that
overlap within a paragraph.
"""

import os
import re
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import citation_extractor as ce  # noqa: E402
from search_urls import resolve_url  # noqa: E402

# Live provider search URL for a citation. Lexis+ is primary; Westlaw is the
# fallback for cites Lexis can't anchor and for provider-locked cites. Shared
# with the Workup Search web app's client logic via search_urls (both ports of
# pdf-viewer/viewer resolveUrl); see search_urls.py.


# Chained continuations ("§§ 1542, 1543, and 1544" / "rules 3.1350, 3.1354")
# arrive with their leading separator included in the span. Strip it so the
# link covers only the section/rule, not the comma and "and".
_LEAD_SEP_RE = re.compile(r"^[\s,]*(?:and\s+)?")


def _flatten(s):
    return (s or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _trim_leading_separator(plain, start, end):
    """If a span starts with a connector (continuation cite), advance start to
    the first real character. Leaves normal cites (which start alphanumeric)
    untouched."""
    text = plain[start:end]
    if text and (text[0] == "," or text[0].isspace()):
        m = _LEAD_SEP_RE.match(text)
        if m:
            start += m.end()
    return start


def _overlaps(s, e, spans):
    for (fs, fe) in spans:
        if s < fe and fs < e:
            return True
    return False


def extract_rows(doc_html, repo=None):
    rows = []

    # Pass 1: full citations. Record their spans per block and build the
    # document-wide first-seen resolution maps (mirrors _augment_aliases).
    blocks = []                       # (block_index, plain)
    spans_by_block = {}               # block_index -> [(start, end), ...]
    index = ce.SupraIndex()           # shared first-seen resolution maps

    for block_index, (block_html, _offset) in enumerate(ce._split_blocks(doc_html)):
        plain = ce._normalize_ws(ce._strip_tags(block_html))
        if not plain:
            continue
        blocks.append((block_index, plain))

        cites = []
        cites.extend(ce._extract_cases(plain))
        cites.extend(ce._extract_statutes(plain))
        cites.extend(ce._extract_rules(plain))
        if repo:
            ce.apply_repo(cites, repo)

        spans = []
        for c in cites:
            if c.match_start is None or c.match_end is None:
                continue
            url = resolve_url(c)
            if not url:
                continue
            start = _trim_leading_separator(plain, c.match_start, c.match_end)
            end = c.match_end
            if start >= end:
                continue
            spans.append((start, end))
            rows.append("\t".join([
                str(block_index), str(start), str(end),
                c.type, url, _flatten(plain[start:end]),
            ]))

            # Registers short-name override, derived short name, reporter
            # volume, and party names — including the defensive post-comma
            # plaintiff for walk-backs that absorbed an intro word.
            index.add(c)
        spans_by_block[block_index] = spans

    # Pass 2: supra and bare "X v. Y" short forms that resolve to a full cite,
    # excluding any span that overlaps a full citation already emitted.
    for block_index, plain in blocks:
        spans = spans_by_block.get(block_index, [])

        for ref in ce.iter_supra(plain):
            s, e = ref.start, ref.end
            if _overlaps(s, e, spans):
                continue
            target = index.resolve_supra(ref.name, ref.volume, ref.reporter)
            if target is None:
                continue
            url = resolve_url(target)
            if not url:
                continue
            rows.append("\t".join([
                str(block_index), str(s), str(e),
                "case", url, _flatten(plain[s:e]),
            ]))

        for m in ce.SHORT_FORM_RE.finditer(plain):
            s, e = m.start(), m.end()
            if _overlaps(s, e, spans):
                continue
            plaintiff = ce._SHORTFORM_LEAD_RE.sub("", m.group(1).strip()).strip()
            defendant = m.group(2).strip()
            if not plaintiff:
                continue
            target = index.resolve_parties(plaintiff, defendant)
            if target is None:
                continue
            url = resolve_url(target)
            if not url:
                continue
            # Strip the leading signal word ("But", "See", ...) from the link
            # span so the link covers only the case name.
            lead = ce._SHORTFORM_LEAD_RE.match(plain[s:e])
            if lead:
                s += lead.end()
            if s >= e:
                continue
            rows.append("\t".join([
                str(block_index), str(s), str(e),
                "case", url, _flatten(plain[s:e]),
            ]))

    return rows


def main(argv):
    if len(argv) < 3:
        sys.stderr.write(
            "usage: word_cite_bridge.py <input_html> <output_tsv> [<repo_json>]\n"
        )
        return 2

    in_path, out_path = argv[1], argv[2]
    repo = None
    if len(argv) > 3 and argv[3] and os.path.exists(argv[3]):
        with open(argv[3], encoding="utf-8") as fh:
            repo = json.load(fh)

    with open(in_path, encoding="utf-8-sig") as fh:
        doc_html = fh.read()

    rows = extract_rows(doc_html, repo)

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(rows))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
