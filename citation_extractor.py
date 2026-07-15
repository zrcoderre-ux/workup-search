"""
citation_extractor.py — California Legal Citation Extractor
============================================================
Extracts case, statute, and Rules of Court citations from HTML-formatted
legal documents (as produced by index.py's extract_html_from_docx).

Designed for California Style Manual citation format as used in
LA County Superior Court orders.

REPOSITORY KEY FORMATS  (UNCHANGED — repo / harvester / cross-opener compat)
----------------------------------------------------------------------------
  Cases:    "38 Cal.App.5th 745"          (volume + reporter + first page)
  Statutes: "Code Civ. Proc. § 437c"      (CSM display form + § + section)
  Rules:    "Cal. Rules of Court, rule 3.1350"

  New (previously-undetected) case shapes get keys that match the text the
  user actually sees, so the client's key-based linking still works:
    WL-only:    "2015 WL 13626022"
    Lexis-only: "2024 U.S. Dist. LEXIS 12345"
    Slip:       "Case No. 25STCV22646"
  New statute / rule shapes:
    Federal:    "9 U.S.C. § 1"
    RPC:        "Cal. Rules of Prof. Conduct, rule 1.9"

WHAT CHANGED IN THIS REVISION (ported from pdf_linker.py)
---------------------------------------------------------
  1. Expanded case-tail grammar: CSM, Bluebook, Flat (no-comma), WL-only,
     Lexis-only, slip-cite, "In re"/"Estate of"/etc., and "X Cases".
  2. Walk-back-from-"v." plaintiff-name algorithm (replaces <em>-cluster).
  3. Dash-class robustness in pin cites (figure/en/em/minus dashes).
  4. Disambiguated search terms + bare-reporter cite (exposed as attributes
     for the client to build Westlaw findType=Y / Lexis pdsearchterms URLs).
  5. Provider lock for single-database cites (wl_only / lexis_only).
  6. Chained additional statute sections ("§§ 1542, 1543, and 1544").
  7. Federal U.S.C. statutes and Rules of Professional Conduct.
  8. First-seen supra resolution + bare "X v. Y" short-form aliases,
     exposed via `short_name` / `short_names` for client-side re-linking.

  The auto-constructed fallback URLs (Google Scholar / leginfo /
  courts.ca.gov) are unchanged in behavior.
"""

import re
import html
from collections import namedtuple
from urllib.parse import quote_plus


# ── CALIFORNIA + FEDERAL REPORTERS ──────────────────────────────────────────────
# Both CSM (compact) and Bluebook (spaced) forms, plus ultra-compact CSM
# practitioner forms (C3d, CA4th, CR) which are normalized back to canonical.
# Sorted longest-first so the alternation prefers specific over generic.

_REPORTERS_RAW = [
    # California
    "Cal.5th", "Cal. 5th", "Cal.4th", "Cal. 4th", "Cal.3d", "Cal. 3d",
    "Cal.2d", "Cal. 2d", "Cal.",
    "Cal.App.5th Supp.", "Cal. App. 5th Supp.",
    "Cal.App.4th Supp.", "Cal. App. 4th Supp.",
    "Cal.App.3d Supp.", "Cal. App. 3d Supp.",
    "Cal.App.2d Supp.", "Cal. App. 2d Supp.",
    "Cal.App.5th", "Cal. App. 5th", "Cal.App.4th", "Cal. App. 4th",
    "Cal.App.3d", "Cal. App. 3d", "Cal.App.2d", "Cal. App. 2d",
    "Cal.App.", "Cal. App.",
    "Cal.Rptr.3d", "Cal. Rptr. 3d", "Cal.Rptr.2d", "Cal. Rptr. 2d",
    "Cal.Rptr.", "Cal. Rptr.",
    # California Style Manual ultra-compact forms (39 C3d 311, 116 CA4th 968,
    # 11 CR3d 45). Normalized to canonical by _normalize_reporter.
    "C5th", "C4th", "C3d", "C2d",
    "CA5th", "CA4th", "CA3d", "CA2d",
    "CR3d", "CR2d", "CR",
    # Federal — Supreme Court
    "U.S.", "S.Ct.", "S. Ct.", "L.Ed.2d", "L. Ed. 2d", "L.Ed.", "L. Ed.",
    # Federal — Circuit / District
    "F.4th", "F. 4th", "F.3d", "F. 3d", "F.2d", "F. 2d", "F.",
    "F.Supp.3d", "F. Supp. 3d", "F.Supp.2d", "F. Supp. 2d", "F.Supp.", "F. Supp.",
    "F. App'x", "F. App\u2019x", "F.App'x", "F.App\u2019x",
    # Federal — specialized
    "Fed.Cl.", "B.R.",
    # Out-of-state regional + New York
    "N.Y.S.2d", "N.Y.S.", "N.Y.2d", "N.Y. 2d", "N.Y.3d", "N.Y. 3d",
    "P.3d", "P. 3d", "P.2d", "P. 2d", "P.",
    "A.3d", "A. 3d", "A.2d", "A. 2d",
    "N.E.3d", "N.E. 3d", "N.E.2d", "N.E. 2d",
    "N.W.2d", "N.W. 2d",
    "S.E.2d", "S.E. 2d",
    "S.W.3d", "S.W. 3d", "S.W.2d", "S.W. 2d",
    "So.3d", "So. 3d", "So.2d", "So. 2d",
]
_REPORTERS_SORTED = sorted(_REPORTERS_RAW, key=len, reverse=True)
REPORTER_PATTERN = "|".join(re.escape(r) for r in _REPORTERS_SORTED)

# Compact CSM reporter → canonical compact form, keyed by whitespace-stripped
# matched text (so "CA4th" and a stray-spaced "CA 4th" both normalize).
_REPORTER_NORMALIZE = {
    "C5th": "Cal.5th", "C4th": "Cal.4th", "C3d": "Cal.3d", "C2d": "Cal.2d",
    "CA5th": "Cal.App.5th", "CA4th": "Cal.App.4th",
    "CA3d": "Cal.App.3d", "CA2d": "Cal.App.2d",
    "CR3d": "Cal.Rptr.3d", "CR2d": "Cal.Rptr.2d", "CR": "Cal.Rptr.",
}


def _normalize_reporter(reporter):
    """Strip internal whitespace and map CSM compact forms to canonical so
    keys and search URLs are consistent regardless of the brief's form."""
    compact = re.sub(r"\s+", "", _strip_tags(reporter)).replace("\\", "")
    return _REPORTER_NORMALIZE.get(compact, compact)


# ── CALIFORNIA CODES ───────────────────────────────────────────────────────────
# (regex_pattern, law_code). Long forms first, then CSM short forms, then
# practitioner variants. Sorted longest-first before alternation so a long
# form wins over a short form when both could match.
#
# law_code is the leginfo lawCode parameter AND the internal abbreviation used
# to key WL_SEARCH_PREFIX / LEXIS_SEARCH_PREFIX. The repo KEY, however, always
# uses the canonical CSM display (CANON_DISPLAY) so long/short forms unify.

LAW_CODES = [
    # Long forms (internal spaces are \s+ so line-wrapped names still match)
    (r"Code\s+of\s+Civil\s+Procedure", "CCP"),
    (r"Civil\s+Code", "CIV"),
    (r"Penal\s+Code", "PEN"),
    (r"Evidence\s+Code", "EVID"),
    (r"Business\s+(?:and|&)\s+Professions\s+Code", "BPC"),
    (r"Family\s+Code", "FAM"),
    (r"Government\s+Code", "GOV"),
    (r"Health\s+(?:and|&)\s+Safety\s+Code", "HSC"),
    (r"Labor\s+Code", "LAB"),
    (r"Probate\s+Code", "PROB"),
    (r"Vehicle\s+Code", "VEH"),
    (r"Welfare\s+(?:and|&)\s+Institutions\s+Code", "WIC"),
    (r"Corporations\s+Code", "CORP"),
    (r"Insurance\s+Code", "INS"),
    (r"Revenue\s+(?:and|&)\s+Taxation\s+Code", "RTC"),
    (r"Education\s+Code", "EDC"),
    (r"Elections\s+Code", "ELEC"),
    (r"Financial\s+Code", "FIN"),
    (r"Fish\s+(?:and|&)\s+Game\s+Code", "FGC"),
    (r"Food\s+(?:and|&)\s+Agricultural\s+Code", "FAC"),
    (r"Harbors\s+(?:and|&)\s+Navigation\s+Code", "HNC"),
    (r"Military\s+(?:and|&)\s+Veterans\s+Code", "MVC"),
    (r"Public\s+Contract\s+Code", "PCC"),
    (r"Public\s+Resources\s+Code", "PRC"),
    (r"Public\s+Utilities\s+Code", "PUC"),
    (r"Streets\s+(?:and|&)\s+Highways\s+Code", "SHC"),
    (r"Unemployment\s+Insurance\s+Code", "UIC"),
    (r"Water\s+Code", "WAT"),
    (r"Commercial\s+Code", "COM"),
    # CSM short forms
    (r"Code\s+Civ\.\s*Proc\.", "CCP"),
    (r"Civ\.\s*Code", "CIV"),
    (r"Pen\.\s*Code", "PEN"),
    (r"Evid\.\s*Code", "EVID"),
    (r"Bus\.\s*(?:&|and)\s*Prof\.\s*Code", "BPC"),
    (r"Fam\.\s*Code", "FAM"),
    (r"Gov\.\s*Code", "GOV"),
    (r"Health\s*(?:&|and)\s*Saf\.\s*Code", "HSC"),
    (r"Lab\.\s*Code", "LAB"),
    (r"Prob\.\s*Code", "PROB"),
    (r"Veh\.\s*Code", "VEH"),
    (r"Welf\.\s*(?:&|and)\s*Inst\.\s*Code", "WIC"),
    (r"Corp\.\s*Code", "CORP"),
    (r"Ins\.\s*Code", "INS"),
    (r"Rev\.\s*(?:&|and)\s*Tax\.\s*Code", "RTC"),
    (r"Educ\.\s*Code", "EDC"),
    (r"Elec\.\s*Code", "ELEC"),
    (r"Fin\.\s*Code", "FIN"),
    (r"Fish\s*(?:&|and)\s*Game\s+Code", "FGC"),
    (r"Food\s*(?:&|and)\s*Agric\.\s*Code", "FAC"),
    (r"Harb\.\s*(?:&|and)\s*Nav\.\s*Code", "HNC"),
    (r"Mil\.\s*(?:&|and)\s*Vet\.\s*Code", "MVC"),
    (r"Pub\.\s*Cont(?:ract)?\.?\s*Code", "PCC"),
    (r"Pub\.\s*Res(?:ources)?\.?\s*Code", "PRC"),
    (r"Pub\.\s*Util(?:ities)?\.?\s*Code", "PUC"),
    (r"Sts\.\s*(?:&|and)\s*Hwys?\.\s*Code", "SHC"),
    (r"Unemp\.\s*Ins\.\s*Code", "UIC"),
    (r"Wat\.\s*Code", "WAT"),
    (r"Com\.\s*Code", "COM"),
    # Extra variants validated by the cross-opener extension's content.js
    (r"Govt\.\s*Code", "GOV"),
    (r"Fish\s*(?:&|and)\s*G\.\s*Code", "FGC"),
    (r"Food\s*(?:&|and)\s*Agr\.\s*Code", "FAC"),
    # Practitioner reorderings (Code last): "Cal. Civ. Proc. Code § ..."
    (r"Civ\.\s*Proc\.\s*Code", "CCP"),
    (r"Civil\s+Procedure\s+Code", "CCP"),
]
LAW_CODES_SORTED = sorted(LAW_CODES, key=lambda x: len(x[0]), reverse=True)

# Canonical CSM display per law_code — used as the repo KEY's code portion.
# Values match the short forms the previous extractor emitted, so existing
# repo entries keyed "Code Civ. Proc. § X" still resolve. Long-form matches
# now canonicalize to the same key (a strict improvement, no fragmentation).
CANON_DISPLAY = {
    "CCP": "Code Civ. Proc.", "CIV": "Civ. Code", "PEN": "Pen. Code",
    "EVID": "Evid. Code", "BPC": "Bus. & Prof. Code", "FAM": "Fam. Code",
    "GOV": "Gov. Code", "HSC": "Health & Saf. Code", "LAB": "Lab. Code",
    "PROB": "Prob. Code", "VEH": "Veh. Code", "WIC": "Welf. & Inst. Code",
    "CORP": "Corp. Code", "INS": "Ins. Code", "RTC": "Rev. & Tax. Code",
    "EDC": "Educ. Code", "ELEC": "Elec. Code", "FIN": "Fin. Code",
    "FGC": "Fish & Game Code", "FAC": "Food & Agric. Code",
    "HNC": "Harb. & Nav. Code", "MVC": "Mil. & Vet. Code",
    "PCC": "Pub. Contract Code", "PRC": "Pub. Resources Code",
    "PUC": "Pub. Util. Code", "SHC": "Sts. & Hwys. Code",
    "UIC": "Unemp. Ins. Code", "WAT": "Wat. Code", "COM": "Com. Code",
}
FULL_NAME = {
    "CCP": "Code of Civil Procedure", "CIV": "Civil Code", "PEN": "Penal Code",
    "EVID": "Evidence Code", "BPC": "Business and Professions Code",
    "FAM": "Family Code", "GOV": "Government Code",
    "HSC": "Health and Safety Code", "LAB": "Labor Code",
    "PROB": "Probate Code", "VEH": "Vehicle Code",
    "WIC": "Welfare and Institutions Code", "CORP": "Corporations Code",
    "INS": "Insurance Code", "RTC": "Revenue and Taxation Code",
    "EDC": "Education Code", "ELEC": "Elections Code", "FIN": "Financial Code",
    "FGC": "Fish and Game Code", "FAC": "Food and Agricultural Code",
    "HNC": "Harbors and Navigation Code", "MVC": "Military and Veterans Code",
    "PCC": "Public Contract Code", "PRC": "Public Resources Code",
    "PUC": "Public Utilities Code", "SHC": "Streets and Highways Code",
    "UIC": "Unemployment Insurance Code", "WAT": "Water Code",
    "COM": "Commercial Code",
}

# Provider-native search prefixes (from cross-opener content.js — validated
# against live Westlaw / Lexis pages). Keyed by internal law_code.
WL_SEARCH_PREFIX = {
    "BPC": "CA BUS & PROF", "COM": "CA COML", "CIV": "CA CIVIL",
    "CCP": "CA CIV PRO", "CORP": "CA CORP", "EDC": "CA EDUC",
    "ELEC": "CA ELEC", "EVID": "CA EVID", "FAM": "CA FAM",
    "FIN": "CA FIN", "FGC": "CA FISH & G", "FAC": "CA FOOD & AG",
    "GOV": "CA GOVT", "HNC": "CA HARB & NAV", "HSC": "CA HLTH & S",
    "INS": "CA INS", "LAB": "CA LABOR", "MVC": "CA MIL & VET",
    "PEN": "CA PENAL", "PROB": "CA PROBATE", "PCC": "CA PUB CONT",
    "PRC": "CA PUB RES", "PUC": "CA PUB UTIL", "RTC": "CA REV & TAX",
    "SHC": "CA STR & HWY", "UIC": "CA UNEMP INS", "VEH": "CA VEHICLE",
    "WAT": "CA WATER", "WIC": "CA WELF & INST",
}
LEXIS_SEARCH_PREFIX = {
    "BPC": "Cal Bus & Prof Code", "COM": "Cal U Com Code", "CIV": "Cal Civ Code",
    "CCP": "Cal Code Civ Proc", "CORP": "Cal Corp Code", "EDC": "Cal Ed Code",
    "ELEC": "Cal Elec Code", "EVID": "Cal Evid Code", "FAM": "Cal Fam Code",
    "FIN": "Cal Fin Code", "FGC": "Cal Fish & G Code", "FAC": "Cal Food & Agr Code",
    "GOV": "Cal Gov Code", "HNC": "Cal Harb & Nav Code", "HSC": "Cal Health & Saf Code",
    "INS": "Cal Ins Code", "LAB": "Cal Lab Code", "MVC": "Cal Mil & Vet Code",
    "PEN": "Cal Pen Code", "PROB": "Cal Prob Code", "PCC": "Cal Pub Contract Code",
    "PRC": "Cal Pub Resources Code", "PUC": "Cal Pub Util Code", "RTC": "Cal Rev & Tax Code",
    "SHC": "Cal Sts & Hy Code", "UIC": "Cal Unemp Ins Code", "VEH": "Cal Veh Code",
    "WAT": "Cal Wat Code", "WIC": "Cal Welf & Inst Code",
}


def _build_statute_re():
    parts = [f"(?P<c{i}>{pat})" for i, (pat, _) in enumerate(LAW_CODES_SORTED)]
    code_alt = "|".join(parts)
    full = (
        r"\b(?:Cal\.\s*|California\s+)?"
        rf"(?:{code_alt})"
        r",?\s*"
        # Section marker is REQUIRED (§ / "section" / "sec.") to keep false
        # positives down. Allows the word forms the old §-only regex missed.
        r"(?:§§?|sections?|secs?\.?)\s*"
        r"(?P<sec>\d+(?:\.\d+)?[a-z]?(?:\([a-z0-9]+\))*)"
    )
    return re.compile(full, re.DOTALL | re.IGNORECASE)


STATUTE_RE = _build_statute_re()


def _statute_law_code(match):
    for i, (_, law_code) in enumerate(LAW_CODES_SORTED):
        if match.group(f"c{i}"):
            return law_code
    return None


# Federal statutes: "9 U.S.C. § 1", "42 U.S.C. § 1983". Tolerant of spaced
# "U. S. C." that PDF/text extraction sometimes produces.
USC_RE = re.compile(
    r"\b(?P<title>\d{1,3})\s+U\.\s*S\.\s*C\."
    r"(?:\s*App\.)?"
    r"\s*"
    r"(?:§§?|sections?|secs?\.?)\s*"
    r"(?P<sec>\d+(?:\.\d+)?[a-z]?(?:\([a-z0-9]+\))*)",
    re.IGNORECASE,
)

# Chained additional sections after a primary statute match:
#   "Code of Civil Procedure sections 598 and 1048(b)"
#   "Civ. Code §§ 1542, 1543, and 1544"
# Anchored at the end of the previous match via re.match(text, pos).
ADDL_SEC_RE = re.compile(
    r"\s*(?:,\s*and|,|\s+and)\s+"
    r"(?P<sec>\d+(?:\.\d+)?[a-z]?(?:\([a-z0-9]+\))*)",
    re.IGNORECASE,
)


# ── RULES OF COURT + PROFESSIONAL CONDUCT ───────────────────────────────────────
_RULE_TITLES = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
}

RULE_RE = re.compile(
    r"\b(?:Cal\.\s*Rules?\s*of\s*Court|California\s*Rules?\s*of\s*Court),?\s*"
    r"rules?\s+(?P<rule>\d+(?:\.\d+)*(?:\([a-z0-9]+\))*)",
    re.IGNORECASE,
)
# Additional rules chained after a primary Rules-of-Court match:
#   "Cal. Rules of Court, rules 3.1350, 3.1354"
RULE_ADDL_RE = re.compile(
    r"\s*(?:,\s*and|,|\s+and)\s+(?P<rule>\d+(?:\.\d+)*(?:\([a-z0-9]+\))*)",
    re.IGNORECASE,
)
RPC_RE = re.compile(
    r"\b(?:Cal(?:ifornia)?\.?\s+)?Rules?\s+of\s+(?:Prof(?:essional)?\.?\s+)?Conduct,?\s+"
    r"rules?\s+(?P<rule>\d+(?:\.\d+)*(?:\([a-z0-9]+\))*)",
    re.IGNORECASE,
)


# ── HTML STRIPPING ─────────────────────────────────────────────────────────────
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(s):
    """Remove HTML tags and decode entities."""
    return html.unescape(_TAG_RE.sub("", s))


def _normalize_ws(s):
    """Collapse whitespace (handles tag-boundary gaps)."""
    return re.sub(r"\s+", " ", s).strip()


# ── URL BUILDERS (auto-constructed fallbacks; unchanged behavior) ────────────────

def build_google_scholar_url(volume, reporter, page):
    raw_reporter = _strip_tags(reporter).replace("\\", "")
    query = f"{volume} {raw_reporter} {page}"
    return f"https://scholar.google.com/scholar?q={quote_plus(query)}"


def build_google_scholar_name_url(case_name):
    return f"https://scholar.google.com/scholar?q={quote_plus(case_name)}"


def build_leginfo_url(law_code, section):
    sec = _bare_section(section).rstrip(".")
    return (
        f"https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml"
        f"?sectionNum={sec}.&lawCode={law_code}"
    )


def build_cornell_usc_url(title, section):
    sec = _bare_section(section)
    return f"https://www.law.cornell.edu/uscode/text/{title}/{sec}"


def build_courts_url(rule_number):
    try:
        prefix = int(rule_number.split(".")[0])
    except ValueError:
        return "https://www.courts.ca.gov/rules.htm"
    title = _RULE_TITLES.get(prefix, str(prefix))
    linkid = f"rule{rule_number.replace('.', '_')}"
    return (
        f"https://www.courts.ca.gov/cms/rules/index.cfm"
        f"?title={title}&linkid={linkid}"
    )


def build_rpc_fallback_url(rule_number):
    return (
        "https://scholar.google.com/scholar?q="
        + quote_plus(f"California Rules of Professional Conduct rule {rule_number}")
    )


# ── SEARCH-TERM HELPERS (data for client-side Westlaw / Lexis URL building) ──────

def _bare_section(sec):
    """Strip parenthetical subdivisions and anything after them. Search
    engines index '430.10', not '430.10(e)'. Letter suffixes are kept
    ('437c'), the decimal IS the section ('1714.10')."""
    return re.sub(r"\([^)]*\).*$", "", sec)


def wl_statute_term(law_code, section):
    """Westlaw native search term, e.g. ('CCP', '760.020') -> 'CA CIV PRO § 760.020'.
    Federal USC keys pass through; returns None if law_code unknown."""
    if law_code == "USC":
        return None  # caller uses the key directly
    p = WL_SEARCH_PREFIX.get(law_code)
    return f"{p} § {_bare_section(section)}" if p else None


def lexis_statute_term(law_code, section):
    """Lexis native search term, e.g. ('CCP', '760.020') -> 'Cal Code Civ Proc § 760.020'."""
    if law_code == "USC":
        return None
    p = LEXIS_SEARCH_PREFIX.get(law_code)
    return f"{p} § {_bare_section(section)}" if p else None


# ── CITATION RESULT CLASS ──────────────────────────────────────────────────────

class Citation:
    """A single detected citation and its resolution data.

    Original attributes (unchanged contract with app.py / workups.html):
      type, key, display, url, fallback_url, source,
      match_start, match_end, match_text,
      case_name, year, volume, reporter, first_page,   # case
      code_name, law_code, section,                    # statute
      rule_number                                      # rule

    New attributes (additive — existing consumers ignore unknown keys):
      wl_only, lexis_only, slip_only : bool  — single-database / slip cite
      provider_lock   : "westlaw" | "lexis" | None — forces a provider
      lexis_search_term  : str | None — disambiguated Lexis pdsearchterms value
      westlaw_search_cite: str | None — bare reporter cite for findType=Y
                                        (or WL/LEXIS number, or case-name search)
      short_name      : str  — distinguishing token for supra resolution
                               (the author's override, when one was given)
      short_name_override : str — the author's own short name, taken from a
                               trailing "(Grand Terrace)" parenthetical; ""
                               when the document didn't supply one
      short_names     : list — alias strings (case-name cores / supra / short
                               forms) the client may also link to this URL
    """
    __slots__ = [
        "type", "key", "display", "url", "fallback_url", "source",
        "match_start", "match_end", "match_text",
        "case_name", "year", "volume", "reporter", "first_page",
        "code_name", "law_code", "section",
        "rule_number",
        # ── new ──
        "wl_only", "lexis_only", "slip_only", "provider_lock",
        "lexis_search_term", "westlaw_search_cite",
        "short_name", "short_name_override", "short_names",
    ]

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))
        if self.short_names is None:
            self.short_names = []
        if self.short_name_override is None:
            self.short_name_override = ""

    def to_dict(self):
        return {s: getattr(self, s) for s in self.__slots__}


# ── BLOCK SPLITTER ─────────────────────────────────────────────────────────────
# Splits stored HTML into paragraph-level blocks to prevent cross-paragraph
# matches (respects the paragraph-boundary rule from WrapCitations).
_BLOCK_RE = re.compile(
    r"(<(?:p|h[1-3])[^>]*>)(.*?)(</(?:p|h[1-3])>)",
    re.DOTALL | re.IGNORECASE,
)


def _split_blocks(doc_html):
    """Yield (block_html, block_start_offset) for each paragraph/heading.
    Falls back to the whole document if no block tags are present."""
    found = False
    for m in _BLOCK_RE.finditer(doc_html):
        found = True
        yield m.group(0), m.start()
    if not found and doc_html.strip():
        yield doc_html, 0


# ── CASE WALK-BACK (port of pdf_linker._walk_back_for_name) ──────────────────────

ANCHOR_RE = re.compile(r"(?<=\s)v\.(?=\s)")

# vol REPORTER page (+ optional pin / pin-range). Dash class accepts ASCII
# hyphen-minus, figure (U+2012), en (U+2013), em (U+2014), and minus (U+2212)
# dashes — missing any silently breaks otherwise-valid pin ranges.
REPORTER_PART = (
    rf"(\d{{1,4}})\s+({REPORTER_PATTERN})\s+(\d{{1,5}})"
    rf"(?:,\s*\d{{1,5}}(?:[-\u2012\u2013\u2014\u2212]\d{{1,5}})?)?"
)

CSM_TAIL = re.compile(rf"\s*\((?:[^)]*?\b)?(\d{{4}})\)\s+{REPORTER_PART}")
BB_TAIL = re.compile(rf",\s+{REPORTER_PART}\s*,?\s*\((?:[^)]*?\b)?(\d{{4}})\)")
FLAT_TAIL = re.compile(rf"\s+{REPORTER_PART}\s*,?\s*\((?:[^)]*?\b)?(\d{{4}})\)")
WL_TAIL = re.compile(
    r",\s+(\d{4})\s+WL\s+(\d{4,8})"
    r"(?:,\s*at\s+\*?\d+(?:\s+n\.\d+)?)?"
    r"\s*\((?:[^)]*?\b)?(\d{4})\)"
)
LEXIS_TAIL = re.compile(
    r",\s+(\d{4})\s+U\.S\.\s*Dist\.\s*LEXIS\s+(\d{4,8})"
    r"(?:,\s*at\s+\*?\d+(?:\s+n\.\d+)?)?"
    r"\s*\((?:[^)]*?\b)?(\d{4})\)"
)
SLIP_TAIL = re.compile(
    r",?\s+Case\s+No\.\s+([A-Z0-9][A-Z0-9:\-]{3,30})"
    r"\s*\(([^)]{3,80})\)",
    re.IGNORECASE,
)

_NONV_PREFIX = (
    r"In re|Estate of|Guardianship of|Conservatorship of|Adoption of|Marriage of"
)
_NONV_PREFIX_RE = re.compile(rf"^\s*({_NONV_PREFIX})\b")

INRE_RE = re.compile(
    rf"\b(?:{_NONV_PREFIX})\s+([A-Z][A-Za-z0-9.\-'&, ]+?)\s*"
    rf"(?:"
    rf"\((\d{{4}})\)\s+(\d{{1,4}})\s+({REPORTER_PATTERN})\s+(\d{{1,5}})"
    rf"|"
    rf",?\s+(\d{{1,4}})\s+({REPORTER_PATTERN})\s+(\d{{1,5}})\s*\((?:[^)]*?\b)?(\d{{4}})\)"
    rf"|"
    rf"[,\s][^\n]{{0,80}}?,\s+(\d{{4}})\s+WL\s+(\d{{4,8}})"
    rf"(?:,\s*at\s+\*?\d+(?:\s+n\.\d+)?)?"
    rf"\s*\((?:[^)]*?\b)?(\d{{4}})\)"
    rf")"
)

# A supra reference's name may be a single party surname ("Aguilar"), an
# authorial short name of several title-case words ("Grand Terrace"), a
# non-v. caption ("In re Marriage of Bonds"), or a full "X v. Y" core.
# It may be followed by the volume/reporter of the earlier full cite
# ("Aguilar, supra, 25 Cal.4th at p. 850"), which is the second-priority
# resolution key when the name itself doesn't match anything.
_SUPRA_TOKEN = r"[A-Z][A-Za-z0-9.\-'&]*"
# Lowercase connectors bind two title-case tokens ("City of Grand Terrace",
# "In re Marriage of Bonds"). Without them the run stops at the connector and
# the "Marriage of" alternative in _NONV_PREFIX swallows the caption's head.
_SUPRA_CONNECTOR = r"(?:of|the|and|&|de|la|du|von|van)"
_SUPRA_RUN = rf"{_SUPRA_TOKEN}(?:\s+(?:{_SUPRA_CONNECTOR}\s+)?{_SUPRA_TOKEN}){{0,3}}"
_SUPRA_NAME = (
    rf"(?:(?:{_NONV_PREFIX})\s+)?{_SUPRA_RUN}"
    rf"(?:\s+v\.\s+{_SUPRA_RUN})?"
)
SUPRA_RE = re.compile(
    rf"\b({_SUPRA_NAME})(,\s*supra)\b"
    rf"(?:\s*,\s*(?:at\s+)?(\d{{1,4}})\s+({REPORTER_PATTERN}))?"
)

# Title-case words that can precede a supra name and get swept into the
# multi-token run ("See Grand Terrace, supra"). "In" is stripped too, unless
# it opens an "In re" caption.
_SUPRA_LEAD_WORDS = {
    "see", "cf", "but", "and", "the", "compare", "accord", "also", "in",
    "per", "citing", "quoting", "following", "like", "under", "of", "to",
    "by", "from", "as", "here", "thus", "e.g", "id",
}
_SUPRA_LEAD_TOKEN_RE = re.compile(r"^([A-Za-z.'&\-]+)\s+(?=\S)")
_SUPRA_INRE_RE = re.compile(rf"^(?:{_NONV_PREFIX})\b")

SupraRef = namedtuple("SupraRef", "name start end volume reporter")


def iter_supra(plain):
    """Yield SupraRef for each 'X, supra' reference in `plain`.

    `start`/`end` bound the name only (not the ", supra" tail), matching what
    the Word bridge needs to hyperlink. `volume`/`reporter` are the trailing
    cite fragment when present, else None.
    """
    for m in SUPRA_RE.finditer(plain):
        name = m.group(1)
        start = m.start(1)
        while True:
            if _SUPRA_INRE_RE.match(name):
                break
            wm = _SUPRA_LEAD_TOKEN_RE.match(name)
            if not wm:
                break
            word = wm.group(1).lower().rstrip(".")
            if word not in _SUPRA_LEAD_WORDS:
                break
            start += wm.end()
            name = name[wm.end():]
        if not name:
            continue
        yield SupraRef(name, start, start + len(name), m.group(3), m.group(4))

_TITLE_WORD = r"[A-Z][a-z][A-Za-z]*"
_CASES_FIRST = r"(?!The\b|In\b|See\b|Cf\b|But\b)" + _TITLE_WORD
CASES_RE = re.compile(
    rf"\b({_CASES_FIRST}(?:\s+{_TITLE_WORD}){{1,5}}\s+Cases)\s*"
    rf"(?:"
    rf"\((\d{{4}})\)\s+(\d{{1,4}})\s+({REPORTER_PATTERN})\s+(\d{{1,5}})"
    rf"|"
    rf",?\s+(\d{{1,4}})\s+({REPORTER_PATTERN})\s+(\d{{1,5}})\s*\((?:[^)]*?\b)?(\d{{4}})\)"
    rf")"
)

# Bare "X v. Y" short-form references (no reporter/year) — second pass.
_PARTY_TOKEN = r"[A-Z][A-Za-z0-9.\-'&]*"
SHORT_FORM_RE = re.compile(
    rf"\b({_PARTY_TOKEN}(?:\s+{_PARTY_TOKEN}){{0,3}})\s+v\.\s+"
    rf"({_PARTY_TOKEN}(?:\s+{_PARTY_TOKEN}){{0,4}}(?:,\s*(?:Inc|LLC|LLP|Ltd|Corp|Co)\.?)?)"
)
_SHORTFORM_LEAD_RE = re.compile(
    r"^(?:In|See|Cf|Cf\.|Compare|Accord|But|Following|Per|Under|Like|Citing|Quoting)\s+",
    re.IGNORECASE,
)

SIGNAL_PREFIXES = {
    "see", "cf", "cf.", "per", "in", "but", "compare", "accord", "e.g.",
    "also", "n", "of", "the", "and", "to", "by", "for", "with", "from",
    "as", "if", "when", "while", "since", "because", "though", "although",
    "court", "supreme", "federal", "state", "california",
}
_TOA_HEADERS = {
    "cases", "statutes", "rules", "authorities", "treatises",
    "regulations", "constitutional", "miscellaneous",
}
_STOPPER_ABBREVS = {
    "e.g", "i.e", "cf", "etc", "viz", "supra",
    "eg", "ie", "see", "accord", "compare",
}
_CORP_SUFFIX_LOWER = {"inc", "co", "corp", "ltd", "grp", "ass'n", "assn", "lp"}
_CORP_SUFFIX_UPPER = {"LLC", "LLP", "LP", "LLLP", "PLLC", "PC", "PLC"}
_NAME_CONNECTORS = {"of", "the", "and", "&", "de", "la", "du", "von", "van", "re",
                    "ex", "rel"}


def _short_name(plaintiff):
    p = plaintiff.strip()
    p = re.sub(rf"^(?:(?:{_NONV_PREFIX})\s+|Ex parte\s+|People v\.\s+)",
               "", p, flags=re.IGNORECASE)
    parts = p.split()
    return parts[0].rstrip(",.;:") if parts else p


def _walk_back_for_name(text, v_pos):
    """Return start index of the plaintiff name before `v.`, or None."""
    pos = v_pos - 1
    while pos > 0 and text[pos] == " ":
        pos -= 1

    et_al_match = re.search(r",\s*et\s+al\.?\s*$", text[: pos + 1])
    if et_al_match:
        pos = et_al_match.start() - 1
        while pos > 0 and text[pos] == " ":
            pos -= 1

    tokens = []  # (start, end, text), closest-to-v.-first
    while pos >= 0:
        while pos >= 0 and text[pos] in " \t":
            pos -= 1
        if pos < 0:
            break
        if text[pos] == "\n":
            break
        tok_end = pos + 1
        while pos >= 0 and text[pos] not in " \n\t":
            pos -= 1
        tok_start = pos + 1
        tok = text[tok_start:tok_end]
        if not tok:
            break

        if tok[-1] in ":;!?":
            break

        _tok_clean_low = tok.lstrip("(.,;:\"'").rstrip(",.;:").lower()
        if _tok_clean_low in _STOPPER_ABBREVS:
            if tokens:
                break
            return None

        if tok.endswith(".") and len(tok) > 1 and tok[-2].islower():
            inner = tok.rstrip(".")
            is_short_cap_abbrev = inner and inner[0].isupper() and 1 <= len(inner) <= 6
            if not is_short_cap_abbrev and tok.lower() not in {
                "co.", "inc.", "corp.", "ltd.", "ass'n.",
            }:
                break

        clean = tok.lstrip("(.,;:\"'\u2010\u2011\u2012\u2013\u2014\u2212-").rstrip(",.;:")
        if not clean:
            break

        # Citation-join boundary: "...745 and Del Monte v. ..." — an "and"/"&"
        # whose left neighbour is a page number or reporter separates two
        # citations, not two words of one name.
        if clean.lower() in {"and", "&"} and tokens:
            _left = re.search(r"(\S+)\s*$", text[:tok_start])
            if _left:
                _lt = _left.group(1).rstrip(",.;:")
                if _lt.isdigit() or re.search(REPORTER_PATTERN, _lt):
                    break

        if clean[0].isdigit():
            if tok.rstrip().endswith(","):
                if tokens:
                    break
                return None
            _has_corp_marker = any(
                t[2].rstrip(",.;:").lower() in _CORP_SUFFIX_LOWER
                or t[2].upper() in _CORP_SUFFIX_UPPER
                for t in tokens
            )
            _local_intro = False
            _peek_left = text[:tok_start].rstrip()
            _last_tok_match = re.search(r"(\S+)$", _peek_left)
            if _last_tok_match:
                _prev = _last_tok_match.group(1).rstrip(",.;:").lower()
                if _prev in {"local", "loc", "no", "chapter", "ch"}:
                    _local_intro = True
            if not (_has_corp_marker or _local_intro):
                if tokens:
                    break
                return None
            tokens.append((tok_start, tok_end, tok))
            continue

        if clean[0].islower() and clean.lower() not in _NAME_CONNECTORS:
            if tokens:
                break
            return None
        if not clean[0].isupper() and clean.lower() not in _NAME_CONNECTORS:
            if tokens:
                break
            return None

        alpha_chars = [c for c in clean if c.isalpha()]
        if (len(alpha_chars) >= 5
                and all(c.isupper() for c in alpha_chars)
                and clean.lower() not in _NAME_CONNECTORS):
            if tokens:
                break
            return None
        if clean.upper() in {"LLP", "LLC", "LLLP", "PLLC", "PC", "PLC"}:
            if tokens:
                break

        if clean.lower() in _TOA_HEADERS:
            if tokens:
                break
            return None

        tokens.append((tok_start, tok_end, tok))

    if not tokens:
        return None

    tokens.reverse()

    while tokens:
        first = tokens[0][2].lower().rstrip(",.;:").lstrip("(.,;:\"'")
        if first in SIGNAL_PREFIXES:
            if first == "in" and len(tokens) > 1:
                second = tokens[1][2].lower().rstrip(",.;:")
                if second == "re":
                    break
            tokens.pop(0)
        else:
            break

    if not tokens:
        return None

    start = tokens[0][0]
    end = tokens[0][1]
    while start < end and not text[start].isalpha():
        start += 1
    return start


# ── SHORT-NAME OVERRIDE PARENTHETICAL (port of ShortCite's snO block) ──────────
# A full cite may be followed by the author's own short name:
#
#   City of Grand Terrace v. Superior Court (1987) 192 Cal.App.3d 1251, 1261
#   (Grand Terrace).
#
# That parenthetical, not the derived plaintiff surname, is what later supra
# references use. The hard part is not finding "(...)" — it is refusing the
# explanatory parentheticals that look identical to a naive matcher:
#
#   ... 25 Cal.4th 826, 843 (disapproved on other grounds in Reid v. Google).
#
# Guards (from ShortCite): the inner text must start with a letter, run no more
# than _OVERRIDE_MAX_LEN characters, contain no paragraph break, and not be an
# explanatory parenthetical. Ported additions: the first letter must be
# uppercase, and structural giveaways (a year, a nested cite, a "v.", a
# semicolon) disqualify it.

_OVERRIDE_MAX_LEN = 60
_OVERRIDE_MAX_WORDS = 6

# First word of the parenthetical. Checked case-insensitively.
_EXPLANATORY_FIRST_WORDS = {
    "disapproved", "disapproving", "overruled", "overruling",
    "abrogated", "abrogating", "superseded", "superseding",
    "questioned", "criticized", "modified", "modifying", "affirmed",
    "affirming", "reversed", "reversing", "vacated", "depublished",
    "review", "cert", "rehearing", "reh'g", "rev'd", "aff'd",
    "holding", "held", "finding", "noting", "concluding", "explaining",
    "observing", "rejecting", "applying", "construing", "distinguishing",
    "citing", "quoting", "internal", "emphasis", "italics", "cleaned",
    "footnote", "footnotes", "fn", "fns", "accord", "see", "cf",
    "compare", "but", "e.g", "i.e", "as", "per", "en", "dictum", "dicta",
    "conc", "dis", "opn", "plurality", "collecting", "summarizing",
}

_EXPLANATORY_PHRASES = (
    "other grounds", "another ground", "by statute", "on remand",
    "emphasis added", "italics added", "emphasis in", "italics in",
    "internal quotation", "cleaned up", "citations omitted",
    "quotations omitted", "omitted", "review granted", "review den",
    "cert. denied", "cert denied", "en banc", "per curiam", "as modified",
    "disapproved", "overruled", "abrogated", "superseded", "depublished",
)

_OVERRIDE_YEAR_RE = re.compile(r"\b(?:1[6-9]|20)\d{2}\b")
_OVERRIDE_CITE_RE = re.compile(rf"\d{{1,4}}\s+{REPORTER_PATTERN}")


def _is_explanatory_parenthetical(inner):
    """True when `inner` is a subsequent-history / explanatory parenthetical
    rather than the author's short name for the case."""
    text = inner.strip()
    if not text:
        return True

    low = text.lower()
    first = re.split(r"[\s,;:]+", low, maxsplit=1)[0].rstrip(".")
    if first in _EXPLANATORY_FIRST_WORDS:
        return True
    if any(p in low for p in _EXPLANATORY_PHRASES):
        return True

    # Structural giveaways: a year, an embedded reporter cite, a case name,
    # or a list separator all mean this is not a short name.
    if _OVERRIDE_YEAR_RE.search(text):
        return True
    if _OVERRIDE_CITE_RE.search(text):
        return True
    if re.search(r"\bv\.\s", text):
        return True
    if ";" in text:
        return True
    return False


def _is_valid_short_name_override(inner):
    text = inner.strip()
    if not text or len(text) > _OVERRIDE_MAX_LEN:
        return False
    if "\n" in text or "\r" in text:
        return False
    if not (text[0].isalpha() and text[0].isupper()):
        return False
    if text.endswith(","):
        return False
    if len(text.split()) > _OVERRIDE_MAX_WORDS:
        return False
    return not _is_explanatory_parenthetical(text)


# Material the override may sit behind: a bracketed parallel cite
# ("[251 Cal.Rptr.3d 269]") and/or a footnote pin (", fn. 3"), plus spacing.
# Nothing else — a period or a closing paren means the sentence moved on.
_PRE_OVERRIDE_RE = re.compile(
    r"\s*(?:\[[^\]\n]{0,120}\]\s*)?"
    r"(?:,\s*fns?\.\s*\d+\s*)?"
    r"(?:\[[^\]\n]{0,120}\]\s*)?"
)
_OVERRIDE_RE = re.compile(rf"\(([^()\n]{{1,{_OVERRIDE_MAX_LEN}}})\)")


def _short_name_override(plain, cite_end):
    """Return the author's short name for the cite ending at `cite_end`, or ""."""
    pre = _PRE_OVERRIDE_RE.match(plain, cite_end)
    pos = pre.end() if pre else cite_end
    om = _OVERRIDE_RE.match(plain, pos)
    if not om:
        return ""
    inner = om.group(1).strip()
    return inner if _is_valid_short_name_override(inner) else ""


# ── CASE CITATION EXTRACTION ────────────────────────────────────────────────────

def _make_case(key, case_name, year, volume, reporter, first_page,
               span, match_text, *, wl_only=False, lexis_only=False,
               slip_only=False, short_name="", short_name_override=""):
    """Construct a case Citation with resolution data populated."""
    if wl_only or lexis_only or slip_only:
        fallback = build_google_scholar_name_url(case_name or key)
    else:
        fallback = build_google_scholar_url(volume, reporter, first_page)

    provider_lock = ("westlaw" if wl_only else "lexis" if lexis_only else None)

    if slip_only:
        lexis_term = case_name or key
        wl_cite = case_name or key
    elif wl_only:
        lexis_term = None
        wl_cite = key  # "2015 WL 13626022"
    elif lexis_only:
        lexis_term = key  # "2024 U.S. Dist. LEXIS 12345"
        wl_cite = None
    else:
        # Full case name (BOTH parties) + reporter cite, matching pdf-viewer's
        # disambiguatedLexisTerm. Including both party names — not just the
        # first plaintiff word — keeps a same-volume neighbour from winning the
        # Lexis search (e.g. "Miranda v. Arizona 384 U.S. 436" vs a different
        # case reported at 384 U.S. 333).
        lexis_term = f"{case_name} {key}".strip() if case_name else key
        wl_cite = key  # bare reporter cite — required by findType=Y

    short_names = []
    if case_name:
        short_names.append(case_name)
    # The author's own short name is, by definition, a string they intend as a
    # reference to this case — so it is also an alias the client may link.
    if short_name_override and short_name_override not in short_names:
        short_names.append(short_name_override)

    return Citation(
        type="case", key=key, display=case_name and f"{case_name} {key}" or key,
        url=fallback, fallback_url=fallback, source="google_scholar",
        match_start=span[0], match_end=span[1], match_text=match_text,
        case_name=case_name, year=year, volume=volume, reporter=reporter,
        first_page=first_page,
        wl_only=wl_only, lexis_only=lexis_only, slip_only=slip_only,
        provider_lock=provider_lock,
        lexis_search_term=lexis_term, westlaw_search_cite=wl_cite,
        # Override beats the derived plaintiff surname.
        short_name=(short_name_override or short_name
                    or _short_name(case_name or "")),
        short_name_override=short_name_override,
        short_names=short_names,
    )


def _extract_cases(plain):
    """Extract all case citations from a single block's plain text."""
    results = []

    # v.-anchored cases (CSM / Bluebook / Flat / WL / Lexis / slip)
    for m in ANCHOR_RE.finditer(plain):
        v_start, v_end = m.start(), m.end()
        plaintiff_start = _walk_back_for_name(plain, v_start)
        if plaintiff_start is None:
            continue
        plaintiff = plain[plaintiff_start:v_start].strip()
        rest = plain[v_end:]

        candidates = []
        for kind, rx in (("csm", CSM_TAIL), ("bb", BB_TAIL),
                         ("wl", WL_TAIL), ("lexis", LEXIS_TAIL),
                         ("flat", FLAT_TAIL)):
            s = rx.search(rest)
            if s and s.start() <= 80:
                candidates.append((kind, s))
        if not candidates:
            s = SLIP_TAIL.search(rest)
            if s and s.start() <= 80:
                candidates.append(("slip", s))
        if not candidates:
            continue

        kind, mm = min(candidates, key=lambda c: c[1].start())
        defendant_text = rest[: mm.start()].rstrip(", ").strip()
        if not defendant_text or not defendant_text[0].isupper():
            continue
        if len(defendant_text) > 200:
            continue

        plaintiff_clean = re.sub(r"\s+", " ", plaintiff).strip()
        defendant_clean = re.sub(r"\s+", " ", defendant_text).strip()
        case_name = f"{plaintiff_clean} v. {defendant_clean}"
        full_span = (plaintiff_start, v_end + mm.end())
        match_text = plain[full_span[0]:full_span[1]]
        sname = _short_name(plaintiff_clean)
        snO = _short_name_override(plain, full_span[1])

        if kind in ("csm",):
            year, vol, rep, page = mm.group(1), mm.group(2), mm.group(3), mm.group(4)
            key = f"{vol} {_normalize_reporter(rep)} {page}"
            results.append(_make_case(key, case_name, year, vol,
                                      _normalize_reporter(rep), page,
                                      full_span, match_text, short_name=sname,
                                      short_name_override=snO))
        elif kind in ("bb", "flat"):
            vol, rep, page, year = mm.group(1), mm.group(2), mm.group(3), mm.group(4)
            key = f"{vol} {_normalize_reporter(rep)} {page}"
            results.append(_make_case(key, case_name, year, vol,
                                      _normalize_reporter(rep), page,
                                      full_span, match_text, short_name=sname,
                                      short_name_override=snO))
        elif kind == "wl":
            wl_year, wl_num = mm.group(1), mm.group(2)
            key = f"{wl_year} WL {wl_num}"
            results.append(_make_case(key, case_name, mm.group(3), None, None, None,
                                      full_span, match_text, wl_only=True,
                                      short_name=sname, short_name_override=snO))
        elif kind == "lexis":
            lx_year, lx_num = mm.group(1), mm.group(2)
            key = f"{lx_year} U.S. Dist. LEXIS {lx_num}"
            results.append(_make_case(key, case_name, mm.group(3), None, None, None,
                                      full_span, match_text, lexis_only=True,
                                      short_name=sname, short_name_override=snO))
        else:  # slip
            docket = mm.group(1)
            key = f"Case No. {docket}"
            results.append(_make_case(key, case_name, "", None, None, None,
                                      full_span, match_text, slip_only=True,
                                      short_name=sname, short_name_override=snO))

    # In re / Estate of / Guardianship of / Conservatorship of / Adoption of /
    # Marriage of (no "v." anchor)
    for m in INRE_RE.finditer(plain):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        prefix_m = _NONV_PREFIX_RE.match(m.group(0))
        prefix = prefix_m.group(1) if prefix_m else "In re"
        full_name = f"{prefix} {name}"
        if m.group(2):
            year, vol, rep, page = m.group(2), m.group(3), m.group(4), m.group(5)
        elif m.group(6):
            vol, rep, page, year = m.group(6), m.group(7), m.group(8), m.group(9)
        else:
            wl_year, wl_num, year = m.group(10), m.group(11), m.group(12)
            key = f"{wl_year} WL {wl_num}"
            results.append(_make_case(key, full_name, year, None, None, None,
                                      m.span(), m.group(0), wl_only=True,
                                      short_name=_short_name(full_name),
                                      short_name_override=_short_name_override(
                                          plain, m.end())))
            continue
        key = f"{vol} {_normalize_reporter(rep)} {page}"
        results.append(_make_case(
            key, full_name, year, vol, _normalize_reporter(rep), page,
            m.span(), m.group(0),
            short_name=_short_name(full_name),
            short_name_override=_short_name_override(plain, m.end()),
        ))

    # "[Subject] Cases" — consolidated-litigation names with no v./In re.
    for m in CASES_RE.finditer(plain):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        if m.group(2):
            year, vol, rep, page = m.group(2), m.group(3), m.group(4), m.group(5)
        else:
            vol, rep, page, year = m.group(6), m.group(7), m.group(8), m.group(9)
        key = f"{vol} {_normalize_reporter(rep)} {page}"
        results.append(_make_case(
            key, name, year, vol, _normalize_reporter(rep), page,
            m.span(), m.group(0),
            short_name=name.split()[0] if name.split() else name,
            short_name_override=_short_name_override(plain, m.end()),
        ))

    return results


# ── STATUTE CITATION EXTRACTION ────────────────────────────────────────────────

def _make_statute(law_code, section, span, match_text, *, is_usc=False, title=None):
    """Construct a statute Citation with resolution data populated."""
    bare = _bare_section(section)
    if is_usc:
        key = f"{title} U.S.C. \u00a7 {bare}"
        display = key
        fallback = build_cornell_usc_url(title, bare)
        full_name = "United States Code"
        lc = "USC"
        wl_term = key
        lexis_term = key
    else:
        canon = CANON_DISPLAY.get(law_code, law_code)
        key = f"{canon} \u00a7 {bare}"
        display = f"{canon}, \u00a7 {bare}"
        fallback = build_leginfo_url(law_code, bare)
        full_name = FULL_NAME.get(law_code, law_code)
        lc = law_code
        wl_term = wl_statute_term(law_code, bare)
        lexis_term = lexis_statute_term(law_code, bare)

    return Citation(
        type="statute", key=key, display=display,
        url=fallback, fallback_url=fallback, source="auto",
        match_start=span[0], match_end=span[1], match_text=match_text,
        code_name=full_name, law_code=lc, section=bare,
        lexis_search_term=lexis_term, westlaw_search_cite=wl_term,
        short_names=[],
    )


def _extract_statutes(plain):
    """Extract statute citations (CA codes + chained sections + federal USC)."""
    results = []

    for m in STATUTE_RE.finditer(plain):
        law_code = _statute_law_code(m)
        if not law_code:
            continue
        section = m.group("sec")
        results.append(_make_statute(law_code, section, m.span(), m.group(0)))

        # Chained additional sections: "§§ 1542, 1543, and 1544".
        scan_pos = m.end()
        while True:
            cont = ADDL_SEC_RE.match(plain, scan_pos)
            if not cont:
                break
            results.append(_make_statute(
                law_code, cont.group("sec"), cont.span(),
                plain[cont.start():cont.end()].lstrip(),
            ))
            scan_pos = cont.end()

    for m in USC_RE.finditer(plain):
        results.append(_make_statute(
            None, m.group("sec"), m.span(), m.group(0),
            is_usc=True, title=m.group("title"),
        ))

    return results


# ── RULE CITATION EXTRACTION ────────────────────────────────────────────────────

def _make_rule(rule_num, span, match_text, *, rpc=False):
    # The search term never carries a subdivision: "rule 7.955(a)(1)" must
    # search for "rule 7.955". Lexis and Westlaw index the rule itself, not its
    # lettered subdivisions, so the trailing parenthetical only breaks the
    # search. key/display/rule_number keep the full cite for fidelity; only the
    # search term drops the "(a)(1)" tail (everything from the first paren).
    base_num = rule_num.split("(")[0]
    if rpc:
        key = f"Cal. Rules of Prof. Conduct, rule {rule_num}"
        display = key
        url = build_rpc_fallback_url(rule_num)
        search_term = f"Cal. Rules of Prof. Conduct, rule {base_num}"
    else:
        key = f"Cal. Rules of Court, rule {rule_num}"
        display = key
        url = build_courts_url(rule_num)
        search_term = f"Cal. Rules of Court, rule {base_num}"
    return Citation(
        type="rule", key=key, display=display,
        url=url, fallback_url=url, source="auto",
        match_start=span[0], match_end=span[1], match_text=match_text,
        rule_number=rule_num, lexis_search_term=search_term,
        westlaw_search_cite=search_term, short_names=[],
    )


def _extract_rules(plain):
    """Extract Rules of Court (+ chained) and Rules of Professional Conduct."""
    results = []

    for m in RULE_RE.finditer(plain):
        results.append(_make_rule(m.group("rule"), m.span(), m.group(0)))
        scan_pos = m.end()
        while True:
            cont = RULE_ADDL_RE.match(plain, scan_pos)
            if not cont:
                break
            results.append(_make_rule(
                cont.group("rule"), cont.span(),
                plain[cont.start():cont.end()].lstrip(),
            ))
            scan_pos = cont.end()

    for m in RPC_RE.finditer(plain):
        results.append(_make_rule(m.group("rule"), m.span(), m.group(0), rpc=True))

    return results


# ── DEDUPLICATION ──────────────────────────────────────────────────────────────

def _deduplicate(citations):
    """One Citation per unique key (first occurrence wins for metadata).
    short_names are merged so later aliases of the same case are preserved.
    A short-name override found on any occurrence is adopted by the survivor —
    the author may give it on a later cite than the first."""
    seen = {}
    for c in citations:
        if c.key not in seen:
            seen[c.key] = c
        else:
            existing = seen[c.key]
            if c.short_name_override and not existing.short_name_override:
                existing.short_name_override = c.short_name_override
                existing.short_name = c.short_name_override
            for alias in (c.short_names or []):
                if alias and alias not in existing.short_names:
                    existing.short_names.append(alias)
    return list(seen.values())


# ── SUPRA + SHORT-FORM AUGMENTATION (item 8) ─────────────────────────────────────

def _normalize_party(s):
    s = re.sub(r"[.,;:'\"]", "", s.lower())
    return re.sub(r"\s+", " ", s).strip()


_PD_RE = re.compile(r"^(.+?)\s+v\.\s+(.+?)$")


class SupraIndex:
    """First-seen resolution maps for supra and bare short-form references.

    Resolution priority (ported from ShortCite's PreScanDocument):

        1. short name  — the author's "(Grand Terrace)" override, then the
                         derived plaintiff surname
        2. reporter volume — "Aguilar, supra, 25 Cal.4th at p. 850" resolves
                         on "25 Cal.4th" even when the name doesn't match
        3. party name  — fall back to matching the plaintiff of a full cite

    Both the extractor and the Word bridge feed this the same way: `add()`
    every full cite in document order, then `resolve_supra()` / `resolve_parties()`.
    """

    def __init__(self):
        self._by_override = {}     # norm(override) -> Citation
        self._by_short = {}        # norm(short name) -> Citation
        self._by_reporter = {}     # (volume, reporter) -> Citation
        self._by_parties = {}      # (p_norm, d_norm) -> Citation
        self._by_party = {}        # p_norm -> Citation

    def add(self, c):
        if getattr(c, "type", None) != "case":
            return

        if c.short_name_override:
            self._by_override.setdefault(_normalize_party(c.short_name_override), c)
        if c.short_name:
            self._by_short.setdefault(_normalize_party(c.short_name), c)
        derived = _short_name(c.case_name or "")
        if derived:
            self._by_short.setdefault(_normalize_party(derived), c)

        if c.volume and c.reporter:
            self._by_reporter.setdefault(
                (str(c.volume), _normalize_reporter(c.reporter)), c)

        if not c.case_name:
            return
        pm = _PD_RE.match(c.case_name)
        if not pm:
            # "In re Marriage of Bonds" and the like: no party split.
            self._by_party.setdefault(_normalize_party(c.case_name), c)
            return

        p_raw, d_raw = pm.group(1), pm.group(2)
        d_norm = _normalize_party(d_raw)
        self._by_parties.setdefault((_normalize_party(p_raw), d_norm), c)
        self._by_party.setdefault(_normalize_party(p_raw), c)

        # Defensive: the name walk-back can absorb a leading intro word
        # ("Separately, Donlen v. Ford ..."). Register the post-comma
        # plaintiff too so later short forms still resolve.
        p_stripped = re.sub(r"^[^,]*,\s*", "", p_raw)
        if p_stripped and p_stripped != p_raw:
            self._by_parties.setdefault((_normalize_party(p_stripped), d_norm), c)
            self._by_party.setdefault(_normalize_party(p_stripped), c)
            alt_short = _short_name(p_stripped)
            if alt_short:
                self._by_short.setdefault(_normalize_party(alt_short), c)

    def resolve_supra(self, name, volume=None, reporter=None):
        """Return the Citation a 'name, supra' reference points at, or None."""
        key = _normalize_party(name)

        # 1. short name — override first, then derived.
        for table in (self._by_override, self._by_short):
            hit = table.get(key)
            if hit is not None:
                return hit

        # A full "X v. Y, supra" core.
        pm = _PD_RE.match(name)
        if pm:
            hit = self._by_parties.get(
                (_normalize_party(pm.group(1)), _normalize_party(pm.group(2))))
            if hit is not None:
                return hit

        # Single-token fallback ("City of Grand Terrace, supra" -> "City").
        first = _normalize_party(_short_name(name))
        if first and first != key:
            for table in (self._by_override, self._by_short):
                hit = table.get(first)
                if hit is not None:
                    return hit

        # 2. reporter volume.
        if volume and reporter:
            hit = self._by_reporter.get((str(volume), _normalize_reporter(reporter)))
            if hit is not None:
                return hit

        # 3. party name.
        return self._by_party.get(key)

    def resolve_parties(self, plaintiff, defendant):
        """Return the Citation a bare 'X v. Y' short form points at, or None."""
        p_norm = _normalize_party(plaintiff)
        d_norm = _normalize_party(defendant)
        hit = self._by_parties.get((p_norm, d_norm))
        if hit is not None:
            return hit
        for (rp, rd), c in self._by_parties.items():
            if rp == p_norm and (rd.startswith(d_norm) or d_norm.startswith(rd)):
                return c
        return None


def _augment_aliases(deduped, plain_blocks):
    """Attach supra / bare-'X v. Y' short-form aliases to the matching case
    citation's short_names, so the client can re-link in-text references that
    don't repeat the reporter cite. First-seen short name / party pair wins.

    This does not add new unique citations — it only enriches `short_names`
    on cases already detected, mirroring pdf_linker's first-seen resolution.
    """
    cases = [c for c in deduped if c.type == "case"]
    if not cases:
        return

    index = SupraIndex()
    for c in cases:
        index.add(c)

    for plain in plain_blocks:
        # supra: "Smith, supra" / "Grand Terrace, supra, 192 Cal.App.3d at p. 1261"
        for ref in iter_supra(plain):
            target = index.resolve_supra(ref.name, ref.volume, ref.reporter)
            if target is None:
                continue
            alias = f"{ref.name}, supra"
            if alias not in target.short_names:
                target.short_names.append(alias)

        # bare "X v. Y" short forms
        for m in SHORT_FORM_RE.finditer(plain):
            plaintiff = _SHORTFORM_LEAD_RE.sub("", m.group(1).strip()).strip()
            defendant = m.group(2).strip()
            if not plaintiff:
                continue
            target = index.resolve_parties(plaintiff, defendant)
            if target is None:
                continue
            alias = f"{plaintiff} v. {defendant}"
            if alias != target.case_name and alias not in target.short_names:
                target.short_names.append(alias)


# ── PUBLIC API ─────────────────────────────────────────────────────────────────

def extract_citations(doc_html):
    """Extract all legal citations from a document's HTML string.

    Returns a deduplicated list of Citation objects (one per unique key),
    sorted cases → statutes → rules, then by key. Detection runs on each
    paragraph/heading block's plain text; supra/short-form aliases are
    resolved document-wide against first-seen full cites.

    URLs are auto-constructed (Google Scholar / leginfo / courts.ca.gov) as
    fallbacks; the client builds live Lexis/Westlaw search URLs from the
    lexis_search_term / westlaw_search_cite / provider_lock fields.
    """
    all_citations = []
    plain_blocks = []

    for block_html, _offset in _split_blocks(doc_html):
        plain = _normalize_ws(_strip_tags(block_html))
        if not plain:
            continue
        plain_blocks.append(plain)
        all_citations.extend(_extract_cases(plain))
        all_citations.extend(_extract_statutes(plain))
        all_citations.extend(_extract_rules(plain))

    deduped = _deduplicate(all_citations)
    _augment_aliases(deduped, plain_blocks)

    order = {"case": 0, "statute": 1, "rule": 2}
    deduped.sort(key=lambda c: (order.get(c.type, 9), c.key))
    return deduped


# ── SELF-TEST ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    SAMPLE_HTML = """
    <p>This matter comes before the court on defendant's motion for summary judgment.</p>
    <p>(<em>Clifford v. Quest Software Inc.</em> (2019) 38 Cal.App.5th 745, 748 [251 Cal.Rptr.3d 269].)</p>
    <p>The standard for summary judgment is well established. (<em>Aguilar v. Atlantic Richfield Co.</em>
    (2001) 25 Cal.4th 826, 843.)</p>
    <p>Flat form: Donlen v. Ford Motor Co. 217 Cal.App.4th 138 (2013) controls.</p>
    <p>Bluebook: Anderson v. Liberty Lobby, Inc., 477 U.S. 242 (1986).</p>
    <p>Unpublished: Roe v. Doe, 2015 WL 13626022 (C.D. Cal. Nov. 2, 2015).</p>
    <p>Pin range with figure dash: Santana v. FCA US, LLC, 56 Cal.App.5th 324, 345&#8210;46 (2020).</p>
    <p>In re Marriage of Bonds (2000) 24 Cal.4th 1, 25 is instructive.</p>
    <p>Ford Motor Warranty Cases (2025) 17 Cal.5th 1122, 1130.</p>
    <p>Plaintiff's claims arise under the FEHA. (Gov. Code, &#167; 12940, subd. (a).)</p>
    <p>The court considers Code Civ. Proc., &#167; 437c, subd. (c) and Evid. Code, &#167; 352.</p>
    <p>Chained: Civ. Code &#167;&#167; 1542, 1543, and 1544 apply.</p>
    <p>Federal arbitration under 9 U.S.C. &#167; 1 et seq.</p>
    <p>Pursuant to Cal. Rules of Court, rule 3.1350, and Cal. Rules of Court, rule 3.1354.</p>
    <p>Counsel violated Cal. Rules of Prof. Conduct, rule 1.9.</p>
    <p>As discussed, Aguilar, supra, is dispositive; see also Clifford v. Quest Software Inc.</p>
    """
    print("=" * 65)
    print("  Citation Extractor — Self Test")
    print("=" * 65)
    for c in extract_citations(SAMPLE_HTML):
        print(f"\n  [{c.type.upper()}] key={c.key!r}")
        if c.type == "case":
            print(f"    name={c.case_name!r}  lock={c.provider_lock}")
            print(f"    lexis_term={c.lexis_search_term!r}  wl_cite={c.westlaw_search_cite!r}")
            if c.short_names:
                print(f"    aliases={c.short_names}")
        elif c.type == "statute":
            print(f"    code={c.code_name} [{c.law_code}] sec={c.section}")
            print(f"    wl_term={c.westlaw_search_cite!r}  lexis_term={c.lexis_search_term!r}")
        elif c.type == "rule":
            print(f"    rule={c.rule_number}")
    print(f"\n{'=' * 65}")
