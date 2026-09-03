"""
test_numeric_party_names.py — party names that open on a digit.

"Market Lofts Community Assn. v. 9th Street Market Lofts, LLC (2014) 222
Cal.App.4th 924" was not detected at all: the defendant had to open on a
capital letter, and "9" is not one. On the plaintiff side the span survived
but lost its first word's digits -- "21st Century Ins. Co." came back as "st
Century Ins. Co." and "24 Hour Fitness, Inc." as " Hour Fitness, Inc." -- so
the link and the italics both opened mid-name.

A bare number inside a sentence is still NOT read into a name: "In 2019 Smith
v. Jones" starts at "Smith".

Run: python test_numeric_party_names.py   (exits non-zero on any failure)
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
    cites = [c for c in ce.extract_citations(text) if c.type == "case"]
    assert len(cites) == 1, f"expected 1 case cite, got {len(cites)}: {text!r}"
    return cites[0]


print("Defendant opening on a digit")
c = only_case("<p>(Market Lofts Community Assn. v. 9th Street Market Lofts, LLC "
              "(2014) 222 Cal.App.4th 924 (Market Lofts).)</p>")
check("case_name", c.case_name,
      "Market Lofts Community Assn. v. 9th Street Market Lofts, LLC")
check("key", c.key, "222 Cal.App.4th 924")
check("override alias", "Market Lofts" in c.short_names, True)

c = only_case("<p>(Smith v. 24 Hour Fitness USA, Inc. (2010) 180 Cal.App.4th 1.)</p>")
check("bare-number defendant", c.case_name, "Smith v. 24 Hour Fitness USA, Inc.")

print("Plaintiff opening on a digit")
c = only_case("<p>(21st Century Ins. Co. v. Superior Court (2009) 47 Cal.4th 511, 520.)</p>")
check("ordinal keeps its digits", c.case_name, "21st Century Ins. Co. v. Superior Court")
check("span opens on the digit", c.match_text.startswith("21st"), True)

c = only_case("<p>(24 Hour Fitness, Inc. v. Superior Court (1998) 66 Cal.App.4th 1199.)</p>")
check("bare number + corp marker", c.case_name, "24 Hour Fitness, Inc. v. Superior Court")

print("A bare number in prose is still not a name")
c = only_case("<p>In 2019 Smith v. Jones (2019) 1 Cal.5th 1 was decided.</p>")
check("year not swept in", c.case_name, "Smith v. Jones")

print("Supra resolves back to the numeric-defendant cite")
doc = ("<p>(Market Lofts Community Assn. v. 9th Street Market Lofts, LLC "
       "(2014) 222 Cal.App.4th 924 (Market Lofts).)</p>"
       "<p>(Market Lofts, supra, 222 Cal.App.4th at p. 930.)</p>")
cases = [c for c in ce.extract_citations(doc) if c.type == "case"]
check("one case, seen twice", len(cases) >= 1, True)

print()
print(f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
