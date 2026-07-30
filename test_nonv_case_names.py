"""
test_nonv_case_names.py — probate/conservatorship/family-law case names.

"Conservatorship of Whitley (2010) 50 Cal.4th 1206" has no "v." anchor, so it
is only reachable through the _NONV_PREFIX alternation. This guards the whole
family (In re / Estate of / Guardianship of / Conservatorship of / Adoption of
/ Marriage of): detection, the derived short name, and supra resolution.

The nested-prefix case matters most. "In re Marriage of Bonds" is "In re" +
"Marriage of" + "Bonds"; a single prefix strip leaves "Marriage of Bonds",
whose first word makes every Marriage-of case share the short name "Marriage"
— and SupraIndex.add uses setdefault, so the second one in a document would
silently resolve every later supra to the first.

Run: python test_nonv_case_names.py   (exits non-zero on any failure)
"""

import sys

import citation_extractor as ce

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got : {got!r}")
        print(f"        want: {want!r}")
        fails += 1


def only_case(text):
    """Return the single case citation extracted from `text`."""
    cites = [c for c in ce.extract_citations(text) if c.type == "case"]
    assert len(cites) == 1, f"expected 1 case cite, got {len(cites)}: {text!r}"
    return cites[0]


print("\n--- detection: every non-v. prefix ---")
CASES = [
    ("Conservatorship of Whitley (2010) 50 Cal.4th 1206.",
     "Conservatorship of Whitley", "50 Cal.4th 1206", "Whitley"),
    ("Estate of Bowles (2008) 169 Cal.App.4th 684.",
     "Estate of Bowles", "169 Cal.App.4th 684", "Bowles"),
    ("Guardianship of Ann S. (2009) 45 Cal.4th 1110.",
     "Guardianship of Ann S.", "45 Cal.4th 1110", "Ann"),
    ("Adoption of Kelsey S. (1992) 1 Cal.4th 816.",
     "Adoption of Kelsey S.", "1 Cal.4th 816", "Kelsey"),
    ("In re Marriage of Bonds (2000) 24 Cal.4th 1.",
     "In re Marriage of Bonds", "24 Cal.4th 1", "Bonds"),
    ("In re Doe (2009) 555 F.3d 100.",
     "In re Doe", "555 F.3d 100", "Doe"),
]
for text, want_name, want_key, want_short in CASES:
    c = only_case(text)
    check(f"{want_name} — name", c.case_name, want_name)
    check(f"{want_name} — key", c.key, want_key)
    check(f"{want_name} — short name", c.short_name, want_short)

print("\n--- the cite is a whole span, pinpoint page excluded ---")
c = only_case("The court in Conservatorship of Whitley (2010) 50 Cal.4th 1206, "
              "1214 held otherwise.")
check("match text", c.match_text, "Conservatorship of Whitley (2010) 50 Cal.4th 1206")
check("year", c.year, "2010")
check("westlaw search cite", c.westlaw_search_cite, "50 Cal.4th 1206")

print("\n--- Bluebook form ---")
c = only_case("Conservatorship of Whitley, 50 Cal.4th 1206 (2010).")
check("bluebook key", c.key, "50 Cal.4th 1206")
check("bluebook name", c.case_name, "Conservatorship of Whitley")

print("\n--- iter_supra keeps the prefix on the name ---")
for text, want in [
    ("See Conservatorship of Whitley, supra, 50 Cal.4th at p. 1214.",
     "Conservatorship of Whitley"),
    ("Estate of Bowles, supra, 169 Cal.App.4th 684.", "Estate of Bowles"),
    ("In re Marriage of Bonds, supra", "In re Marriage of Bonds"),
]:
    refs = list(ce.iter_supra(text))
    check(text[:48], refs[0].name if refs else None, want)

print("\n--- supra resolves back to the full cite ---")
doc = ("Conservatorship of Whitley (2010) 50 Cal.4th 1206, 1214. "
       "Later: Conservatorship of Whitley, supra, 50 Cal.4th at p. 1214.")
idx = ce.SupraIndex()
for c in ce.extract_citations(doc):
    idx.add(c)
ref = next(iter(ce.iter_supra(doc)))
target = idx.resolve_supra(ref.name, ref.volume, ref.reporter)
check("Whitley supra -> full cite", target.key if target else None, "50 Cal.4th 1206")

print("\n--- nested prefixes don't collide on 'Marriage' ---")
doc = ("In re Marriage of Bonds (2000) 24 Cal.4th 1, 25. "
       "In re Marriage of Davis (2015) 61 Cal.4th 846, 850. "
       "See In re Marriage of Davis, supra, 61 Cal.4th at p. 850.")
idx = ce.SupraIndex()
for c in ce.extract_citations(doc):
    idx.add(c)
ref = list(ce.iter_supra(doc))[0]
target = idx.resolve_supra(ref.name, ref.volume, ref.reporter)
check("Davis supra -> Davis, not Bonds",
      target.key if target else None, "61 Cal.4th 846")

print("\n" + "=" * 60)
print(f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
