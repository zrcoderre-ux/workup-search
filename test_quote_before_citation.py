"""
test_quote_before_citation.py — a citation that follows a quotation must not
drag the quoted sentence into the case name.

The name walk-back stops at a sentence boundary by testing whether a token ends
in "." with a lowercase letter before it. A closing quote HIDES that mark: a
quotation ending a sentence reads `English.”`, whose last character is the
quote, so the test was False and the walk-back sailed on through the sentence
before the citation. The span came back as

    English.” (Penilla v. Westmont Corp. (2016) 3 Cal.App.5th 205, 209

and the Word macro hyperlinked the judge's own quoted prose along with the case.

Run: python test_quote_before_citation.py   (exits non-zero on any failure)
"""

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


def span(text):
    """The literal text of the single case citation extracted from `text`."""
    cites = ce._extract_cases(text)
    assert len(cites) == 1, f"expected 1 cite, got {len(cites)}: {text!r}"
    c = cites[0]
    return text[c.match_start:c.match_end]


PENILLA = "Penilla v. Westmont Corp. (2016) 3 Cal.App.5th 205, 209"

print("\n--- a quotation before the citation is not part of the name ---")
check(
    "curly quote",
    span(
        "An arbitration provision is procedurally unconscionable where it "
        "“was neither provided in a Spanish-language copy nor explained "
        "to respondents who did not understand written English.” "
        "(" + PENILLA + ".)"
    ),
    PENILLA,
)
check(
    "straight quote",
    span('It was "one-sided." (' + PENILLA + ".)"),
    PENILLA,
)
check(
    "question mark inside the quotation",
    span("Who signed it?” (" + PENILLA + ".)"),
    PENILLA,
)
check(
    "quotation ending in a corporate abbreviation",
    span("a claim against the Co.” (" + PENILLA + ".)"),
    PENILLA,
)

print("\n--- a short-form cite in parentheses is not part of the next name ---")
# "(Ibid.)" ends in ")", not ".", so the sentence-boundary test missed it the
# same way a closing quote did, and the walk-back from Nguyen's "v." pulled the
# whole short cite in -- the Word macro hyperlinked "Ibid.)" along with the
# case. Reported separately from the quotation shape; same root cause, which is
# why ")" and "]" are in _CLOSING_PUNCT alongside the quotes.
NGUYEN = "Nguyen v. Applied Medical Resources Corp. (2016) 4 Cal.App.5th 232"
check(
    "(Ibid.) before the case name",
    span(
        "a prearbitration exhaustion requirement was reasonable in an agreement "
        "carrying a mutual obligation to arbitrate. (Ibid.) " + NGUYEN +
        " distinguished the free peek cases on the same grounds."
    ),
    NGUYEN,
)
check(
    "(Id. at p. 250.) before the case name",
    span("the term again went undefined. (Id. at p. 250.) " + NGUYEN + " so held."),
    NGUYEN,
)

print("\n--- plain sentence boundaries still stop it (regression) ---")
check(
    "unquoted period",
    span("The court so held. (" + PENILLA + ".)"),
    PENILLA,
)
check(
    "no preceding sentence at all",
    span(PENILLA + "."),
    PENILLA,
)

print("\n--- names that must survive the closing-punctuation strip ---")
check(
    "possessive plaintiff",
    span("See Farmers' Insurance Exchange v. Superior Court (1992) 2 Cal.4th 377, 383."),
    "Farmers' Insurance Exchange v. Superior Court (1992) 2 Cal.4th 377, 383",
)
check(
    "abbreviated party name mid-sentence",
    span("as stated in Ford Motor Co. v. Superior Court (1973) 35 Cal.App.3d 676, 679."),
    "Ford Motor Co. v. Superior Court (1973) 35 Cal.App.3d 676, 679",
)
check(
    "et al. plaintiff",
    span("Juan Carlos Meneses, et al. v. FCA US LLC (2022) 75 Cal.App.5th 1, 5."),
    "Juan Carlos Meneses, et al. v. FCA US LLC (2022) 75 Cal.App.5th 1, 5",
)
check(
    "multi-word corporate name",
    span("Aguilar v. Atlantic Richfield Co. (2001) 25 Cal.4th 826, 850."),
    "Aguilar v. Atlantic Richfield Co. (2001) 25 Cal.4th 826, 850",
)

print("\n" + "=" * 60)
print(f"FAILURES: {fails}")
raise SystemExit(1 if fails else 0)
