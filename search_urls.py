"""
search_urls.py — live Lexis+ / Westlaw search-URL resolution
============================================================
Single source of truth (within the Workup Search repo) for turning a detected
Citation into a live provider search URL. Used by both the Word macro bridge
(word_cite_bridge.py) and any server-side consumer, so the two stay in lockstep.

This is a Python port of the "current pdf.viewer search logic": the URL builders
in pdf-viewer/viewer/code-tables.js and the resolve_url dispatch in
pdf-viewer/viewer/citation-linker.js (resolveUrl, the Lexis/Westlaw branch).
That JS repo is the CANONICAL source — keep this file in sync with it.

Resolution model (mirrors resolveUrl):
  * Provider defaults to Lexis+; a single-database cite forces its provider via
    the citation's `provider_lock` ("westlaw" for WL-only, "lexis" for
    Lexis-only) — the same role wlOnly/lexisOnly play in resolveUrl.
  * When the resolved provider is Lexis but the citation has no Lexis search
    term (e.g. a WL-only unpublished decision), resolution FALLS BACK to Westlaw
    rather than emitting nothing.

The citation's search TERMS are precomputed by citation_extractor
(`lexis_search_term` / `westlaw_search_cite`), so this module only holds the
thin URL-string builders and the provider dispatch.
"""

from urllib.parse import quote

# `safe` mirrors JavaScript's encodeURIComponent, which leaves !*'() (and the
# always-unreserved -_.~) unescaped, so URLs match the JS builders byte-for-byte.
_ENCODE_SAFE = "!*'()"

_LEXIS_PDMFID = "1530671"


def _q(term):
    return quote(term or "", safe=_ENCODE_SAFE)


# ── URL builders (ported from pdf-viewer/viewer/code-tables.js) ─────────────────

def lexis_search_url(term):
    """Live Lexis+ search URL (port of lexisSearchUrl)."""
    return (
        "https://plus.lexis.com/search/"
        "?pdmfid=" + _LEXIS_PDMFID +
        "&pdsearchterms=" + _q(term)
    )


def westlaw_case_url(cite):
    """Westlaw case URL (port of westlawCaseUrl). WL database numbers aren't
    served by findType=Y, so those route through search instead; a real
    reporter cite uses the direct findType=Y link."""
    if " WL " in cite:
        return (
            "https://1.next.westlaw.com/Search/Results.html"
            "?query=" + _q(cite) +
            "&jurisdiction=CA&contentType=CASE"
        )
    return (
        "https://1.next.westlaw.com/Link/Document/FullText"
        "?findType=Y&cite=" + _q(cite)
    )


def westlaw_statute_url(query):
    """Westlaw statute search URL (port of westlawStatuteUrl)."""
    return (
        "https://1.next.westlaw.com/Search/Results.html"
        "?query=" + _q(query) +
        "&jurisdiction=CA&contentType=STATUTE"
    )


def westlaw_rule_url(query):
    """Westlaw rule search URL (port of westlawRuleUrl) — no contentType filter,
    since court rules aren't indexed as statutes."""
    return (
        "https://1.next.westlaw.com/Search/Results.html"
        "?query=" + _q(query) +
        "&jurisdiction=CA"
    )


def westlaw_ucc_url(query):
    """Model Uniform Commercial Code search URL (port of westlawUccUrl) — no CA
    jurisdiction filter, since the model UCC is indexed nationally. Included for
    parity with the canonical logic; citation_extractor does not currently emit
    a model-UCC key, so resolve_url never reaches it here."""
    return (
        "https://1.next.westlaw.com/Search/Results.html"
        "?query=" + _q(query) +
        "&contentType=STATUTE"
    )


# ── Provider dispatch (port of citation-linker.js resolveUrl) ───────────────────

def resolve_url(c, provider="lexis"):
    """Live search URL for a citation `c` (a citation_extractor.Citation).

    `provider` is the default provider ("lexis" | "westlaw"); a citation's
    `provider_lock` overrides it for single-database cites. Lexis is primary and
    Westlaw is the fallback: if the resolved provider is Lexis but the citation
    carries no Lexis search term, we build the Westlaw URL instead. Returns ""
    only when neither provider can produce a term (so the caller's
    `if not url: continue` guard still applies)."""
    # Single-database cites force their provider (mirrors resolveUrl's
    # wlOnly -> westlaw / lexisOnly -> lexis override).
    effective = getattr(c, "provider_lock", None) or provider

    if effective != "westlaw":
        term = c.lexis_search_term
        if term:
            return lexis_search_url(term)
        # No Lexis anchor (e.g. a WL-only decision) — fall back to Westlaw.
        effective = "westlaw"

    # Westlaw branch. Terms are precomputed by the extractor
    # (westlaw_search_cite); fall back to the bare key if absent.
    cite = c.westlaw_search_cite or c.key
    if not cite:
        return ""

    # Model UCC (not emitted by the current extractor, but kept for parity with
    # resolveUrl's statute branch).
    if c.type == "statute" and str(c.key).startswith("UCC § "):
        section = c.key[len("UCC § "):]
        return westlaw_ucc_url("Unif.Commercial Code § " + section)

    if c.type == "case":
        return westlaw_case_url(cite)
    if c.type == "rule":
        return westlaw_rule_url(cite)
    return westlaw_statute_url(cite)  # statute (incl. federal U.S.C.)
