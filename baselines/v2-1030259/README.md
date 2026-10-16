# Frozen baseline: v2 at `1030259`

Reference point for every later change. Do not edit the files in this folder. A new baseline gets a new folder.

| Item | Value |
|---|---|
| Commit | `1030259` (git tag `v2-baseline`, branch `ai_revenue_leakage_hunter_v2`) |
| Dataset fingerprint | `cca8a43cec67` (generator seed 42, 1,580 ground-truth invoice lines) |
| Tests | 64 passed (`pytest.txt`, `pytest_junit.xml`), captured 2026-10-16 on a clean tree |
| Lint | `ruff check` and `ruff format --check` clean (`lint.txt`) |
| Environment | Python 3.12.4, pandas 3.0.6, pydantic 2.14.1, pytest 8.4.2, ruff 0.17.0, Windows 11 |

## Evaluation at the baseline (synthetic data)

| Terms source | Field accuracy | Leakage lines found | Precision | $ found vs seeded | False overbilling | Lines to review | Gate |
|---|---|---|---|---|---|---|---|
| Answer key (engine-only) | 100% | 311/311 | 100% | $757,338 / $757,338 | $0 | 5 | PASS |
| Rules baseline (regex) | 94.1% | 222/311 (71.4%) | 100% | $499,409 / $757,338 (34.1% error) | $139,908 | 335 | FAIL |
| Gemini | not run (no API key, B-002) | | | | | | |

Vetting: 35 / 43 pass, 1 fail (EVAL-04 blind holdout, B-005), the rest blocked on Gemini access or human walkthroughs.

## Contents
- `reports/`, `vetting/`: copied byte-for-byte from commit `1030259` (`git show 1030259:<path>`), not from the working tree.
- `pytest.txt`, `pytest_junit.xml`, `lint.txt`: run output at `1030259`.
- `SHA256SUMS`: checksums of every file here.

## Regeneration noise (not committed)
A re-run on 2026-10-15 changed only the timestamp in `reports/evaluation_rule.md` and the timings in vetting `OPS-04`. Those two edits are kept in `git stash` as "v2 regen noise (timestamps/timings) after 1030259 re-run 2026-10-15". They are not part of any commit.
