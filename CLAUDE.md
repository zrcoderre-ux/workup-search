# Project guidelines

## Workflow

- After completing a given task, squash merge the changes into `main` (and push
  `main`). Develop on the designated feature branch as usual, then collapse that
  branch's commits into a single commit on `main` via squash merge.
- A task is "complete" once work on the user's prompt is finished and the user
  has not sent a follow-up asking for something else. If the user sends more
  requests, wait until all of them are resolved before merging — don't merge
  between follow-ups. If work finishes and the user has not messaged, go ahead
  and merge.

## Tests

Standalone scripts at the repo root, each run directly and exiting non-zero on
any failure — there is no pytest harness:

```
python3 test_nonv_case_names.py
python3 test_shortcite_port.py
python3 test_rule_subdivision.py
python3 test_search_logic.py
python3 test_ccr_regs.py
python3 citation_extractor.py    # module self-test corpus
```
