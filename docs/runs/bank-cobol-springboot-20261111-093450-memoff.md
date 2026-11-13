# v1 A0

_bank-cobol-springboot · 2026-11-11 15:34 UTC_

Run `bank-cobol-springboot-20261111-093450-memoff`

## Headline

| Probe score | Quiz with repo | Quiz memory only | Work cost | Sessions |
|---|---|---|---|---|
| - | 0.858 | - | $5.48 | 99 |


## Log entry

The control for the first run: the same v1 project with Living Memory's hooks disabled. It ran on the Phase 0 harness, which added this memory-off arm, the repo-access quiz, the planted-mistake metrics and pointer coverage. At that harness version the off arm did not also switch off Claude Code's own auto-memory; that came with arm A0 in scenario v2. So this run is "no Living Memory" rather than "no memory at all".

The pipeline stopped at the sprint-3 handover: the leaver's store had no notes, and the export failed with "No notes match". The harness was changed to skip handovers in the memory-off arm and when the leaver saved nothing, and the run resumed from its saved state.

With the repo available, agents answered most should-know questions correctly. Because the v1 runs took different quizzes (this one with the repo, the first one from memory only), the two cannot be compared on quiz score. The team briefing also changed between them, so the planted-mistake counts are not comparable either.


## Cost

| Who spent it | Dollars |
|---|---|
| Work sessions (team, merge resolves) | $5.48 |
| Simulated colleagues (chat) | $0.00 |
| Harness (quizzes, grading, probe judging) | $2.02 |
| Run total | $7.50 |
| Sessions without a recorded cost | 0 |


## Efficiency per session

| Kind | Sessions | $/session | Turns | Tool calls | Seconds | Cache-read tokens | Output tokens |
|---|---|---|---|---|---|---|---|
| work | 48 | $0.109 | 20.2 | 19.2 | 166.5 | 992,144 | 19,829 |
| quiz repo | 13 | $0.085 | 11.1 | 10.1 | 44.9 | 356,853 | 8,069 |


## Quizzes

Should-know scores per fact (1 = every agent who should know it answered correctly). Memory only: answered from memory with the repo denied. With repo: the agent's clone and tools available.

| Fact | What it is | Memory only | With repo | Stores holding it | Should-know coverage | Stale-only stores |
|---|---|---|---|---|---|---|
| T1 | Day count by product | - | 0.958 | 0 | 0 | - |
| T2 | Rounding of interest | - | 1 | 0 | 0 | - |
| T3 | Legacy date format | - | 1 | 0 | 0 | - |
| T4 | Account number masking | - | 0.962 | 0 | 0 | - |
| D1 | Money representation | - | 1 | 0 | 0 | - |
| D2 | Overdraft fee | - | 1 | 0 | 0 | - |
| H1 | Interest module ownership | - | 0.875 | 0 | 0 | - |
| I1 | Retried transfer incident | - | 0.375 | 0 | 0 | - |
| O1 | Maintenance fee | - | 0.667 | 0 | 0 | - |
| P1 | Project phase and go-live criterion | - | 0.577 | 0 | 0 | - |
| P2 | Module ownership | - | 0.708 | 0 | 0 | - |
| P3 | Approved deviations from legacy | - | 1 | 0 | 0 | - |
| O2 | Overdraft counting | - | 0.875 | 0 | 0 | - |

- With repo: all 0.862, should-know 0.858, failure kinds ok 100, capture_gap 2, stale answers 0, missing 0


## Work metrics

| Measure | Value | What it counts |
|---|---|---|
| Re-reads per work session | 4.5 | files and searches the agent had read in an earlier session |
| Re-read share | 0.22 | re-reads over all reads |
| Tool calls before the first change | 9 | exploration before the first edit or commit |
| Own repeated failures | 1 | an error the agent already hit in an earlier session |
| Team repeated failures | 4 | an error a teammate hit earlier |
| Repeated failed Living Memory calls | 0 | memory-tool friction, kept apart from work mistakes |
| Stale code lines | 0 | added code matching an outdated decision (heuristic) |
| Joiner cost ratio | 0.95 | joiners' first sessions vs the team median (1 = same) |
| App-check regressions | 0 | a check on main that passed and later failed |


## Planted mistakes

| Trap | What it is | Hits | Repeats |
|---|---|---|---|
| M1 | Running the Windows wrapper through cmd /c from Git Bash: prints the cmd banner, builds nothing and exits 0 (a silent false green) | 0 | 0 |


## CI, merges and final code

| Measure | Value |
|---|---|
| CI runs green | 13 of 13 |
| Last CI | green |
| Merge attempts | 60 |
| Conflicts on first try | 12 |
| Unresolved merges | 0 |
| Files swept up uncommitted | 0 |

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

- **Scenario:** `bank-cobol-springboot` (v1)
- **Arm:** A0: memory off
- **Label:** memoff
- **Semantic search:** no
- **Started:** 2026-11-11 15:34 UTC
- **Finished:** 2026-11-11 17:02 UTC
- **Duration:** 1 h 27 min
- **Claude Code:** 2.1.322
- **Living Memory tree:** `6b94fa536ab5ccb5`
- **Harness:** `89be16a86789de33`
- **Scenario files:** `e2b5df721bbe71c1`


## Living Memory before this run

- No merges since the previous run
- Living Memory was installed but switched off in this arm.


## Compare

- [Scenario v1 analysis](../analysis/v1.md)
- [Previous run: v1 C](../runs/bank-cobol-springboot-20261111-061514.md)


_2.1.322 (Claude Code) · Living Memory tree 6b94fa536ab5ccb5 · harness 89be16a86789de33_
