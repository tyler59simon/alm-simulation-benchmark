# v2 A0 seed 1

_bank-cobol-springboot-v2 · 2026-11-11 18:06 UTC_

Run `bank-cobol-springboot-v2-20261111-120632-A0-s1`

## Headline

| Probe score | Quiz with repo | Quiz memory only | Work cost | Sessions |
|---|---|---|---|---|
| 0.53 | 0.715 | - | $13.73 | 193 |


## Log entry

The first run of scenario v2, the realistic rewrite: short prompts in the engineer's voice, a tracker, wiki and Slack outside the repo with business colleagues played by Haiku, natural traps (a commit-message hook and CI-only lint rules), facts that change twice, 3 working days per sprint, and 9 work probes in sprint 4.

This arm had no memory at all. It ran in parallel with A1 (started 20 seconds apart), on the same scenario files and harness. CI went red twice during the run and was red at the end.

It has the highest probe mean of seed 1, but with one run per arm a single probe flipping moves the mean by about 0.11, so that ordering is not evidence. See the [scenario v2 analysis](../analysis/v2.md).


## Cost

| Who spent it | Dollars |
|---|---|
| Work sessions (team, merge resolves) | $13.73 |
| Simulated colleagues (chat) | $0.01 |
| Harness (quizzes, grading, probe judging) | $3.06 |
| Run total | $16.80 |
| Sessions without a recorded cost | 0 |


## Efficiency per session

| Kind | Sessions | $/session | Turns | Tool calls | Seconds | Cache-read tokens | Output tokens |
|---|---|---|---|---|---|---|---|
| work | 142 | $0.097 | 16.7 | 16.1 | 131.2 | 701,612 | 12,912 |
| quiz repo | 14 | $0.101 | 15.5 | 14.5 | 77.2 | 519,080 | 15,574 |


## Quizzes

Should-know scores per fact (1 = every agent who should know it answered correctly). Memory only: answered from memory with the repo denied. With repo: the agent's clone and tools available.

| Fact | What it is | Memory only | With repo | Stores holding it | Should-know coverage | Stale-only stores |
|---|---|---|---|---|---|---|
| T1 | Day count by product | - | 0.625 | 0 | 0 | - |
| T2 | Rounding of interest | - | 1 | 0 | 0 | - |
| T3 | Legacy date format | - | 0.5 | 0 | 0 | - |
| T4 | Account number masking | - | 0.857 | 0 | 0 | - |
| D1 | Money representation | - | 0.95 | 0 | 0 | - |
| D2 | Overdraft fee | - | 1 | 0 | 0 | - |
| H1 | Ownership changes | - | 0.5 | 0 | 0 | - |
| I1 | Retried transfer incident | - | 0.25 | 0 | 0 | - |
| O1 | Maintenance fee | - | 1 | 0 | 0 | - |
| O2 | Overdraft counting | - | 0.875 | 0 | 0 | - |
| P1 | Project phase and go-live criterion | - | 0.083 | 0 | 0 | - |
| P2 | Current owners | - | 0.25 | 0 | 0 | - |
| P3 | Approved deviations from legacy | - | 1 | 0 | 0 | - |
| E1 | Commit message policy | - | 1 | 0 | 0 | - |
| E2 | CI lint rules | - | 1 | 0 | 0 | - |

- With repo: all 0.731, should-know 0.715, failure kinds ok 107, capture_gap 16, stale 5, stale answers 6, missing 0


## Work probes

Ordinary sprint-4 requests that silently need earlier knowledge; score is the passed share of weighted checks.

| Probe | Agent | Facts | Score | Checks passed | Flag |
|---|---|---|---|---|---|
| PR1 | dev-int2 | T1 | 0.2 | 1/3 | - |
| PR2 | dev-ledger | D2 | 0.4 | 1/2 | - |
| PR3 | dev-pay | I1 | 0.667 | 2/3 | - |
| PR4 | mig | T3 | 1 | 2/2 | - |
| PR5 | sec2 | T4 | 1 | 2/2 | - |
| PR6 | arch | D1 | 0.25 | 1/2 | - |
| PR7 | qa | D2, P3 | 0.75 | 1/2 | - |
| PR8 | po | O1, T1 | 0 | 0/2 | - |
| PR9 | ops | E1, E2 | 0.5 | 1/2 | - |


## Work metrics

| Measure | Value | What it counts |
|---|---|---|
| Re-reads per work session | 6.41 | files and searches the agent had read in an earlier session |
| Re-read share | 0.389 | re-reads over all reads |
| Tool calls before the first change | 11.3 | exploration before the first edit or commit |
| Own repeated failures | 2 | an error the agent already hit in an earlier session |
| Team repeated failures | 0 | an error a teammate hit earlier |
| Repeated failed Living Memory calls | 0 | memory-tool friction, kept apart from work mistakes |
| Stale code lines | 15 | added code matching an outdated decision (heuristic) |
| Joiner cost ratio | 1.96 | joiners' first sessions vs the team median (1 = same) |
| App-check regressions | 1 | a check on main that passed and later failed |


## Planted mistakes

| Trap | What it is | Hits | Repeats |
|---|---|---|---|
| M1 | Commit rejected by policy ENG-7 (first line must start with a tracker key) | 5 | 1 |
| M2 | System.out/err printing in production code (CI lint L1) | 0 | 0 |
| M3 | TODO/FIXME without a ticket key (CI lint L2) | 0 | 0 |


## CI, merges and final code

| Measure | Value |
|---|---|
| CI runs green | 35 of 37 |
| Last CI | red |
| Merge attempts | 146 |
| Conflicts on first try | 0 |
| Unresolved merges | 0 |
| Files swept up uncommitted | 6 |

| Fact | Final code check | Result |
|---|---|---|
| T1 | 30/360 day count for SV1 | ok |
| T2 | Half-even rounding at posting | ok |
| T2 | Truncation in daily accrual | missing |
| T3 | Century window at 70 | ok |
| T4 | Account number masking | ok |
| D1 | BigDecimal money | ok |
| D1 | No long-cents money left | missing |
| D2 | Overdraft fee 25.00 | ok |
| I1 | Duplicate reference guard | ok |


## Run facts

- **Scenario:** `bank-cobol-springboot-v2` (v2)
- **Arm:** A0: memory off
- **Label:** A0-s1
- **Semantic search:** no
- **Started:** 2026-11-11 18:06 UTC
- **Finished:** 2026-11-11 21:20 UTC
- **Duration:** 3 h 13 min
- **Claude Code:** 2.1.322
- **Living Memory tree:** `ff1474191da2317b`
- **Harness:** `21903a30f4520878`
- **Scenario files:** `ff6e1052a34acc60`


## Living Memory before this run

- No merges since the previous run
- Living Memory was installed but switched off in this arm.


## Compare

- [Scenario v2 analysis](../analysis/v2.md)
- [Previous run: v1 A0](../runs/bank-cobol-springboot-20261111-093450-memoff.md)


_2.1.322 (Claude Code) · Living Memory tree ff1474191da2317b · harness 21903a30f4520878_
