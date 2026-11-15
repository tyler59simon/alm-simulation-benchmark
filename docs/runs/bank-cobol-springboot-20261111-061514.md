# v1 C

_bank-cobol-springboot · 2026-11-11 12:15 UTC_

Run `bank-cobol-springboot-20261111-061514`

## Headline

| Probe score | Quiz with repo | Quiz memory only | Work cost | Sessions |
|---|---|---|---|---|
| - | - | 0.062 | $6.32 | 88 |


## Log entry

The first full run of the harness: scenario v1, 4 sprints, Living Memory on with each agent's own store. Living Memory main was at PR #28 (reviewed procedural learning, phase 1); none of the remediation work existed yet.

The memory plumbing worked: no Living Memory CLI errors, and hooks fired in every session. What memory held was the problem. In the memory-only quiz, most should-know misses were capture gaps: the fact never reached the agent's store. The 2026-11-11 review traced this to four causes:

- The protocol rule "skip what docs record" sent stakeholder decisions into tickets and ADRs, so even the agent who received a decision saved no note about it.
- Codebase maps carried most of the stored facts, and they went stale: the architect's map still said money was long cents after the architect wrote ADR-004 (BigDecimal).
- Notes kept interim beliefs: an open bug note kept a hypothesis, and one note recorded a wrong conclusion with no verified flag.
- Sonnet-low leads made 3 memory calls in 15 work sessions, against 65 in 47 for Haiku agents.

This run predates the repo-access quiz and the work probes, so its only quiz is memory-only. Those findings became the Living Memory remediation phases measured later by run v2 C seed 1.


## Cost

| Who spent it | Dollars |
|---|---|
| Work sessions (team, merge resolves) | $6.32 |
| Simulated colleagues (chat) | $0.00 |
| Harness (quizzes, grading, probe judging) | $0.69 |
| Run total | $7.01 |
| Sessions without a recorded cost | 0 |


## Efficiency per session

| Kind | Sessions | $/session | Turns | Tool calls | Seconds | Cache-read tokens | Output tokens |
|---|---|---|---|---|---|---|---|
| work | 48 | $0.122 | 19.8 | 20.9 | 206.4 | 901,367 | 17,516 |
| quiz memory | 13 | $0.018 | 2.1 | 1.1 | 11.4 | 37,818 | 1,338 |


## Quizzes

Should-know scores per fact (1 = every agent who should know it answered correctly). Memory only: answered from memory with the repo denied. With repo: the agent's clone and tools available.

| Fact | What it is | Memory only | With repo | Stores holding it | Should-know coverage | Stale-only stores |
|---|---|---|---|---|---|---|
| T1 | Day count by product | 0.125 | - | 0 | 0 | - |
| T2 | Rounding of interest | 0.3 | - | 4 | 0.6 | - |
| T3 | Legacy date format | 0 | - | 3 | 0.5 | - |
| T4 | Account number masking | 0.038 | - | 2 | 0.154 | - |
| D1 | Money representation | 0.025 | - | 0 | 0 | arch, dev-acct |
| D2 | Overdraft fee | 0.167 | - | 1 | 0.333 | - |
| H1 | Interest module ownership | 0 | - | 3 | 0.25 | - |
| I1 | Retried transfer incident | 0 | - | 9 | 1 | - |
| O1 | Maintenance fee | 0 | - | 1 | 0.333 | - |
| O2 | Overdraft counting | 0 | - | 0 | 0 | - |

- Memory only: all 0.035, should-know 0.062, failure kinds capture_gap 53, stale 1, retrieval_miss 10, ok 8, stale answers 1, missing 0


## Work metrics

| Measure | Value | What it counts |
|---|---|---|
| Re-reads per work session | 4.58 | files and searches the agent had read in an earlier session |
| Re-read share | 0.237 | re-reads over all reads |
| Tool calls before the first change | 9.9 | exploration before the first edit or commit |
| Own repeated failures | 4 | an error the agent already hit in an earlier session |
| Team repeated failures | 9 | an error a teammate hit earlier |
| Repeated failed Living Memory calls | 4 | memory-tool friction, kept apart from work mistakes |
| Stale code lines | 0 | added code matching an outdated decision (heuristic) |
| Joiner cost ratio | 3.08 | joiners' first sessions vs the team median (1 = same) |
| App-check regressions | 0 | a check on main that passed and later failed |


## Planted mistakes

| Trap | What it is | Hits | Repeats |
|---|---|---|---|
| M1 | Running the Windows wrapper through cmd /c from Git Bash: prints the cmd banner, builds nothing and exits 0 (a silent false green) | 47 | 13 |


## Memory stores

| Measure | Value |
|---|---|
| Active notes | 32 |
| Maps | 13 |
| Noise-like notes | 8 |
| Status snapshot notes | - |
| Living Memory calls | 72 |
| Calls per work session | 0.94 |
| CLI errors | 0 |
| Note updates | 6 |
| Superseded notes | 0 |
| Decision docs with a pointer note | 2 of 8 |
| Hook pre-tool-use p50 / p95 ms | 21.3 / 43.1 (n=1,085) |
| Hook session-end p50 / p95 ms | 38.4 / 77.6 (n=75) |
| Hook session-start p50 / p95 ms | 171.7 / 340.1 (n=75) |
| Hook stop p50 / p95 ms | 24.6 / 42.9 (n=89) |
| Hook user-prompt p50 / p95 ms | 180 / 270.8 (n=89) |


## CI, merges and final code

| Measure | Value |
|---|---|
| CI runs green | 13 of 13 |
| Last CI | green |
| Merge attempts | 62 |
| Conflicts on first try | 14 |
| Unresolved merges | 0 |
| Files swept up uncommitted | 0 |

| Fact | Final code check | Result |
|---|---|---|
| T1 | 30/360 day count for SV1 | ok |
| T2 | Half-even rounding at posting | ok |
| T2 | Truncation in daily accrual | ok |
| T3 | Century window at 70 | missing |
| T4 | Account number masking | ok |
| D1 | BigDecimal money | ok |
| D1 | No long-cents money left | missing |
| D2 | Overdraft fee 25.00 | ok |
| I1 | Duplicate reference guard | ok |


## Run facts

- **Scenario:** `bank-cobol-springboot` (v1)
- **Arm:** C: Living Memory
- **Label:** -
- **Semantic search:** no
- **Started:** 2026-11-11 12:15 UTC
- **Finished:** 2026-11-11 14:14 UTC
- **Duration:** 1 h 59 min
- **Claude Code:** 2.1.322
- **Living Memory tree:** `6f7e6c5dc58571ab`
- **Harness:** `7fe0720c5b3cc4cd`
- **Scenario files:** `5c4f10f5c8f87fd4`


## Living Memory before this run

- Main at #28 feat: reviewed procedural learning (phase 1) (28 merges before this first run)


## Compare

- [Scenario v1 analysis](../analysis/v1.md)


_2.1.322 (Claude Code) · Living Memory tree 6f7e6c5dc58571ab · harness 7fe0720c5b3cc4cd_
