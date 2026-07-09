import sys
sys.path.insert(0, ".")
import citation_extractor as ce

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got  {got!r}\n        want {want!r}")
        fails.append(label)


print("\n--- _is_valid_short_name_override ---")
for inner, want in [
    ("Grand Terrace", True),
    ("Clifford", True),
    ("Ford Motor Warranty Cases", True),
    ("Song-Beverly Act", True),
    ("O'Neil", True),
    # explanatory parentheticals — must be rejected
    ("disapproved on other grounds in Reid v. Google, Inc.", False),
    ("overruled on other grounds", False),
    ("abrogated by statute", False),
    ("superseded by statute as stated in Smith", False),
    ("emphasis added", False),
    ("italics added", False),
    ("internal quotation marks omitted", False),
    ("cleaned up", False),
    ("citations omitted", False),
    ("as modified Aug. 3, 2019", False),
    ("Disapproved on other grounds in Reid", False),   # capitalized variant
    ("Overruled by Aguilar", False),
    ("2001", False),
    ("C.D. Cal. Nov. 2, 2015", False),
    ("Fourth Dist., Div. Two, 1987", False),
    ("citing Aguilar", False),
    ("holding the statute inapplicable", False),
    ("per curiam", False),
    ("en banc", False),
    ("25 Cal.4th 826", False),
    ("Smith v. Jones", False),
    ("Smith; Jones", False),
    ("lowercase", False),
    ("", False),
    ("A" * 61, False),
    ("One Two Three Four Five Six Seven", False),
]:
    check(f"({inner[:44]})", ce._is_valid_short_name_override(inner), want)


print("\n--- _short_name_override placement ---")
cases = [
    ("City of Grand Terrace v. Superior Court (1987) 192 Cal.App.3d 1251, 1261 (Grand Terrace).",
     "Grand Terrace"),
    ("Clifford v. Quest Software Inc. (2019) 38 Cal.App.5th 745, 748 [251 Cal.Rptr.3d 269] (Clifford).",
     "Clifford"),
    ("Aguilar v. Atlantic Richfield Co. (2001) 25 Cal.4th 826, 843, fn. 22 (Aguilar).",
     "Aguilar"),
    # explanatory parenthetical in the override slot -> no override
    ("Smith v. Jones (2001) 25 Cal.4th 826, 843 (disapproved on other grounds in Reid v. Google).",
     ""),
    # sentence ended; the next paren is a new citation, not an override
    ("Smith v. Jones (2001) 25 Cal.4th 826, 843.) (See also Doe v. Roe (2002) 26 Cal.4th 1.)",
     ""),
]
for text, want in cases:
    cs = ce._extract_cases(text)
    got = cs[0].short_name_override if cs else "<no cite>"
    check(text[:52] + "...", got, want)


print("\n--- resolution priority ---")

HTML = """
<p>(<em>City of Grand Terrace v. Superior Court</em> (1987) 192 Cal.App.3d 1251,
1261 (<em>Grand Terrace</em>).)</p>
<p>The court in <em>Grand Terrace, supra</em>, 192 Cal.App.3d at p. 1261, held otherwise.</p>
<p>(<em>Aguilar v. Atlantic Richfield Co.</em> (2001) 25 Cal.4th 826, 843
(disapproved on other grounds in <em>Reid v. Google, Inc.</em> (2010) 50 Cal.4th 512).)</p>
<p>See <em>Aguilar, supra</em>, 25 Cal.4th at p. 850.</p>
<p>As stated in <em>Wrongway, supra</em>, 25 Cal.4th at p. 851, the burden shifts.</p>
<p>(<em>In re Marriage of Bonds</em> (2000) 24 Cal.4th 1, 25.)</p>
<p>In <em>In re Marriage of Bonds, supra</em>, 24 Cal.4th 1, the court explained.</p>
"""
by_key = {c.key: c for c in ce.extract_citations(HTML) if c.type == "case"}

gt = by_key["192 Cal.App.3d 1251"]
ag = by_key["25 Cal.4th 826"]

check("override beats derived surname", gt.short_name, "Grand Terrace")
check("override is an alias", "Grand Terrace" in gt.short_names, True)
check("multi-word supra resolves", "Grand Terrace, supra" in gt.short_names, True)

check("explanatory paren rejected", ag.short_name_override, "")
check("derived surname retained", ag.short_name, "Aguilar")
check("Reid parsed as its own cite", "50 Cal.4th 512" in by_key, True)
check("name-hit supra", "Aguilar, supra" in ag.short_names, True)
# "Wrongway" matches no case name -> must resolve on "25 Cal.4th"
check("reporter-volume fallback", "Wrongway, supra" in ag.short_names, True)

bonds = by_key["24 Cal.4th 1"]
check("In re supra", "In re Marriage of Bonds, supra" in bonds.short_names, True)


print("\n--- iter_supra lead-word stripping ---")
for text, want in [
    ("See Grand Terrace, supra, 192 Cal.App.3d at p. 1261", "Grand Terrace"),
    ("In Aguilar, supra, the court", "Aguilar"),
    ("The court in Aguilar, supra", "Aguilar"),
    ("In re Marriage of Bonds, supra", "In re Marriage of Bonds"),
    ("But see Clifford v. Quest, supra", "Clifford v. Quest"),
]:
    refs = list(ce.iter_supra(text))
    check(text[:44], refs[0].name if refs else None, want)

refs = list(ce.iter_supra("Aguilar, supra, 25 Cal.4th at p. 850"))
check("volume captured", (refs[0].volume, refs[0].reporter), ("25", "Cal.4th"))
check("span isolates name", "Aguilar, supra, 25 Cal.4th at p. 850"[refs[0].start:refs[0].end], "Aguilar")


print("\n--- regression: existing self-test corpus still parses ---")
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    import runpy
    runpy.run_path("citation_extractor.py", run_name="__main__")
out = buf.getvalue()
for expect in ["38 Cal.App.5th 745", "25 Cal.4th 826", "217 Cal.App.4th 138",
               "477 U.S. 242", "2015 WL 13626022", "56 Cal.App.5th 324",
               "24 Cal.4th 1", "17 Cal.5th 1122", "Gov. Code", "9 U.S.C."]:
    check(f"still detects {expect}", expect in out, True)

print("\n" + "=" * 60)
print("FAILURES:", len(fails))
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
