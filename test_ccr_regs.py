"""
test_ccr_regs.py — California Code of Regulations citations.

The CCR is cited two ways ("Cal. Code Regs., tit. 27, § 25805" and
"27 CCR § 25805") and both must produce the same key and the same provider
search terms. Westlaw abbreviates the code "CA ADC" and indexes it as a
regulation, so its search URL must NOT carry the contentType=STATUTE filter
that ordinary code sections get.

Run: python3 test_ccr_regs.py   (exits non-zero on any failure)
"""

import citation_extractor as ce
from search_urls import resolve_url

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got : {got!r}")
        print(f"        want: {want!r}")
        fails += 1


def only(text):
    """The single CCR citation extracted from `text`."""
    cites = ce._extract_ccr(text)
    assert len(cites) == 1, f"expected 1 cite, got {len(cites)}: {text!r}"
    return cites[0]


print("\n--- every cite form reaches the same section ---")
for label, text in [
    ("CSM title-first",      "See Cal. Code Regs., tit. 27, § 25805."),
    ("no space after Cal.",  "See Cal.Code Regs., tit. 27, § 25805."),
    ("spelled out",          "See California Code of Regulations, title 27, section 25805."),
    ("no comma before tit.", "See Cal. Code Regs. tit. 27, § 25805."),
    ("volume-first",         "See 27 Cal. Code Regs. § 25805."),
    ("CCR abbreviation",     "See 27 CCR § 25805."),
    ("C.C.R., no section marker", "See 27 C.C.R. 25805."),
]:
    c = only(text)
    check(f"{label}: key", c.key, "Cal. Code Regs., tit. 27, § 25805")
    check(f"{label}: westlaw term", c.westlaw_search_cite, "27 CA ADC § 25805")
    check(f"{label}: lexis term", c.lexis_search_term, "27 CCR § 25805")

print("\n--- the pre-1988 name is the same code ---")
c = only("Former Cal. Admin. Code, tit. 22, § 51000 governed.")
check("Cal. Admin. Code keys as CCR", c.key, "Cal. Code Regs., tit. 22, § 51000")

print("\n--- structured fields ---")
c = only("Cal. Code Regs., tit. 27, § 25805.")
check("type is statute", c.type, "statute")
check("law_code", c.law_code, "CCR")
check("code_name", c.code_name, "California Code of Regulations")
check("section", c.section, "25805")

print("\n--- subdivisions are linked but never searched ---")
c = only("Cal. Code Regs., tit. 8, § 3203(a)(1) requires a written program.")
check("key drops the subdivision", c.key, "Cal. Code Regs., tit. 8, § 3203")
check("westlaw term drops it too", c.westlaw_search_cite, "8 CA ADC § 3203")
check("the link still covers it",
      "Cal. Code Regs., tit. 8, § 3203(a)(1) requires a written program."[c.match_start:c.match_end],
      "Cal. Code Regs., tit. 8, § 3203(a)(1)")

print("\n--- dotted and lettered section numbers survive ---")
c = only("Cal. Code Regs., tit. 22, § 66261.24.")
check("decimal section", c.section, "66261.24")
c = only("Cal. Code Regs., tit. 24, § 1605A.1.")
check("lettered section", c.section, "1605A.1")

print("\n--- chained sections share the title ---")
cites = ce._extract_ccr("Cal. Code Regs., tit. 8, §§ 3203, 3204 and 3205 apply.")
check("three sections found", len(cites), 3)
check("keys", [c.key for c in cites], [
    "Cal. Code Regs., tit. 8, § 3203",
    "Cal. Code Regs., tit. 8, § 3204",
    "Cal. Code Regs., tit. 8, § 3205",
])

print("\n--- reached through _extract_statutes (what the bridge calls) ---")
keys = [c.key for c in ce._extract_statutes("Cal. Code Regs., tit. 27, § 25805.")]
check("bridge sees the reg", keys, ["Cal. Code Regs., tit. 27, § 25805"])

print("\n--- provider URLs ---")
c = only("Cal. Code Regs., tit. 27, § 25805.")
check("westlaw drops contentType=STATUTE",
      resolve_url(c, "westlaw"),
      "https://1.next.westlaw.com/Search/Results.html"
      "?query=27%20CA%20ADC%20%C2%A7%2025805&jurisdiction=CA")
check("lexis searches the CCR cite",
      resolve_url(c, "lexis"),
      "https://plus.lexis.com/search/"
      "?pdmfid=1530671&pdsearchterms=27%20CCR%20%C2%A7%2025805")
check("fallback is the free public CCR",
      c.fallback_url,
      "https://govt.westlaw.com/calregs/Search/Results?query=27+CA+ADC+s+25805")

print("\n--- what must NOT read as a regulation ---")
for text in [
    "The court reviewed 25 Cal.4th 826, 843.",
    "Code Civ. Proc., § 437c, subd. (c).",
    "Gov. Code, § 12940, subd. (a).",
    "See 9 U.S.C. § 1 et seq.",
    "Cal. Rules of Court, rule 3.1350.",
    "Clifford v. Quest Software Inc. (2019) 38 Cal.App.5th 745, 748.",
    "The CCR requires compliance.",
]:
    check(f"clean: {text}", [c.key for c in ce._extract_ccr(text)], [])

print("\n" + "=" * 60)
print(f"FAILURES: {fails}")
raise SystemExit(1 if fails else 0)
