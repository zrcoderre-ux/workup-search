"""
test_rule_subdivision.py — a rule-of-court search term must never carry a
subdivision. "rule 7.955(a)(1)" searches for "rule 7.955"; Lexis and Westlaw
index the rule, not its lettered subdivisions, so the parenthetical only breaks
the search. The visible cite (key/display/rule_number) keeps the full text.

Run: python test_rule_subdivision.py   (exits non-zero on any failure)
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


def only(text):
    """Return the single citation extracted from `text`."""
    cites = ce._extract_rules(text)
    assert len(cites) == 1, f"expected 1 cite, got {len(cites)}: {text!r}"
    return cites[0]


print("\n--- search term strips subdivision ---")
c = only("See Cal. Rules of Court, rule 7.955(a)(1).")
check("lexis term drops (a)(1)", c.lexis_search_term, "Cal. Rules of Court, rule 7.955")
check("westlaw cite drops (a)(1)", c.westlaw_search_cite, "Cal. Rules of Court, rule 7.955")
check("display keeps subdivision", c.key, "Cal. Rules of Court, rule 7.955(a)(1)")
check("rule_number keeps subdivision", c.rule_number, "7.955(a)(1)")

print("\n--- single-letter subdivision ---")
c = only("Cal. Rules of Court, rule 3.1354(b).")
check("lexis term drops (b)", c.lexis_search_term, "Cal. Rules of Court, rule 3.1354")

print("\n--- Rules of Professional Conduct ---")
c = only("Cal. Rules of Prof. Conduct, rule 1.9(a).")
check("RPC lexis term drops (a)", c.lexis_search_term, "Cal. Rules of Prof. Conduct, rule 1.9")
check("RPC westlaw cite drops (a)", c.westlaw_search_cite, "Cal. Rules of Prof. Conduct, rule 1.9")

print("\n--- no subdivision: unchanged (regression) ---")
c = only("under Cal. Rules of Court, rule 3.1350,")
check("plain rule unchanged (lexis)", c.lexis_search_term, "Cal. Rules of Court, rule 3.1350")
check("plain rule unchanged (display)", c.key, "Cal. Rules of Court, rule 3.1350")

print("\n" + "=" * 60)
print(f"FAILURES: {fails}")
raise SystemExit(1 if fails else 0)
