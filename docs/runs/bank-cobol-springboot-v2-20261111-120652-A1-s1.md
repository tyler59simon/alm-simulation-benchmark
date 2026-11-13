# v2 A1 seed 1

_bank-cobol-springboot-v2 · 2026-11-11 18:06 UTC_

Run `bank-cobol-springboot-v2-20261111-120652-A1-s1`

## Headline

| Probe score | Quiz with repo | Quiz memory only | Work cost | Sessions |
|---|---|---|---|---|
| 0.485 | 0.715 | - | $14.46 | 193 |


## Log entry

Claude Code as shipped: built-in auto-memory on, no Living Memory. It ran in parallel with A0 on the same scenario files and harness.

Built-in memory saved one note in the whole run, so this arm behaved almost like A0. Its work cost was the highest of seed 1. Of the planted traps, only the commit-message hook fired (4 hits by 4 agents, no repeats), and the lint traps never fired in any v2 run.


## Cost

| Who spent it | Dollars |
|---|---|
| Work sessions (team, merge resolves) | $14.46 |
| Simulated colleagues (chat) | $0.02 |
| Harness (quizzes, grading, probe judging) | $3.38 |
| Run total | $17.87 |
| Sessions without a recorded cost | 0 |


## Efficiency per session

| Kind | Sessions | $/session | Turns | Tool calls | Seconds | Cache-read tokens | Output tokens |
|---|---|---|---|---|---|---|---|
| work | 142 | $0.102 | 16.8 | 16.9 | 127.8 | 757,953 | 13,550 |
| quiz repo | 14 | $0.119 | 13.1 | 12.1 | 73.7 | 465,479 | 14,608 |


## Quizzes

Should-know scores per fact (1 = every agent who should know it answered correctly). Memory only: answered from memory with the repo denied. With repo: the agent's clone and tools available.

| Fact | What it is | Memory only | With repo | Stores holding it | Should-know coverage | Stale-only stores |
|---|---|---|---|---|---|---|
| T1 | Day count by product | - | 0.375 | 0 | 0 | - |
| T2 | Rounding of interest | - | 1 | 0 | 0 | - |
| T3 | Legacy date format | - | 0.75 | 0 | 0 | - |
| T4 | Account number masking | - | 0.964 | 0 | 0 | - |
| D1 | Money representation | - | 1 | 0 | 0 | - |
| D2 | Overdraft fee | - | 0.833 | 0 | 0 | - |
| H1 | Ownership changes | - | 0.214 | 0 | 0 | - |
| I1 | Retried transfer incident | - | 0.375 | 0 | 0 | - |
| O1 | Maintenance fee | - | 1 | 0 | 0 | - |
| O2 | Overdraft counting | - | 1 | 0 | 0 | - |
| P1 | Project phase and go-live criterion | - | 0.375 | 0 | 0 | - |
| P2 | Current owners | - | 0.083 | 0 | 0 | - |
| P3 | Approved deviations from legacy | - | 1 | 0 | 0 | - |
| E1 | Commit message policy | - | 1 | 0 | 0 | - |
| E2 | CI lint rules | - | 0.944 | 0 | 0 | - |

- With repo: all 0.7, should-know 0.715, failure kinds ok 104, capture_gap 23, stale 1, stale answers 1, missing 0


## Work probes

Ordinary sprint-4 requests that silently need earlier knowledge; score is the passed share of weighted checks.

| Probe | Agent | Facts | Score | Checks passed | Flag |
|---|---|---|---|---|---|
| PR1 | dev-int2 | T1 | 0.2 | 1/3 | - |
| PR2 | dev-ledger | D2 | 0 | 0/2 | - |
| PR3 | dev-pay | I1 | 0.667 | 2/3 | - |
| PR4 | mig | T3 | 1 | 2/2 | - |
| PR5 | sec2 | T4 | 0 | 0/2 | - |
| PR6 | arch | D1 | 1 | 2/2 | - |
| PR7 | qa | D2, P3 | 1 | 2/2 | - |
| PR8 | po | O1, T1 | 0.5 | 1/2 | - |
| PR9 | ops | E1, E2 | 0 | 0/2 | - |


## Work metrics

| Measure | Value | What it counts |
|---|---|---|
| Re-reads per work session | 7.11 | files and searches the agent had read in an earlier session |
| Re-read share | 0.415 | re-reads over all reads |
| Tool calls before the first change | 12.1 | exploration before the first edit or commit |
| Own repeated failures | 3 | an error the agent already hit in an earlier session |
| Team repeated failures | 5 | an error a teammate hit earlier |
| Repeated failed Living Memory calls | 0 | memory-tool friction, kept apart from work mistakes |
| Stale code lines | 5 | added code matching an outdated decision (heuristic) |
| Joiner cost ratio | 0.85 | joiners' first sessions vs the team median (1 = same) |
| App-check regressions | 0 | a check on main that passed and later failed |


## Planted mistakes

| Trap | What it is | Hits | Repeats |
|---|---|---|---|
| M1 | Commit rejected by policy ENG-7 (first line must start with a tracker key) | 4 | 0 |
| M2 | System.out/err printing in production code (CI lint L1) | 0 | 0 |
| M3 | TODO/FIXME without a ticket key (CI lint L2) | 0 | 0 |


## CI, merges and final code

| Measure | Value |
|---|---|
| CI runs green | 37 of 37 |
| Last CI | green |
| Merge attempts | 142 |
| Conflicts on first try | 0 |
| Unresolved merges | 0 |
| Files swept up uncommitted | 8 |

| Fact | Final code check | Result |
|---|---|---|
| T1 | 30/360 day count for SV1 | ok |
| T2 | Half-even rounding at posting | ok |
| T2 | Truncation in daily accrual | ok |
| T3 | Century window at 70 | ok |
| T4 | Account number masking | ok |
| D1 | BigDecimal money | ok |
| D1 | No long-cents money left | missing |
| D2 | Overdraft fee 25.00 | ok |
| I1 | Duplicate reference guard | ok |


## Run facts

- **Scenario:** `bank-cobol-springboot-v2` (v2)
- **Arm:** A1: Claude Code auto-memory
- **Label:** A1-s1
- **Semantic search:** no
- **Started:** 2026-11-11 18:06 UTC
- **Finished:** 2026-11-11 22:11 UTC
- **Duration:** 4 h 4 min
- **Claude Code:** 2.1.322
- **Living Memory tree:** `ff1474191da2317b`
- **Harness:** `21903a30f4520878`
- **Scenario files:** `ff6e1052a34acc60`


## Living Memory before this run

- No merges since the previous run
- Living Memory was installed but switched off in this arm.


## Compare

- [Scenario v2 analysis](../analysis/v2.md)
- [Previous run: v2 A0 seed 1](../runs/bank-cobol-springboot-v2-20261111-120632-A0-s1.md)


_2.1.322 (Claude Code) · Living Memory tree ff1474191da2317b · harness 21903a30f4520878_
