# v2 C seed 1

_bank-cobol-springboot-v2 · 2026-11-11 22:11 UTC_

Run `bank-cobol-springboot-v2-20261111-161109-C-s1`

## Headline

| Probe score | Quiz with repo | Quiz memory only | Work cost | Sessions |
|---|---|---|---|---|
| 0.363 | 0.699 | 0.227 | $13.14 | 230 |


## Log entry

Living Memory with remediation phases 1 to 3 (PR #30, phases 1 and 2; PR #31, phase 3) and semantic search on. It started after A0 and A1 had finished: after an out-of-memory crash, the user chose one run at a time.

**Grading history.** The first grading gave this run a repo-quiz should-know score of 0.348 and a probe mean of 0.457. Living Memory's Stop reminder made agents save notes after answering, and the harness had read that housekeeping message instead of the answer. After the reply-reader fix (harness commit `fe6a593`), the run was regraded from its transcripts (repo quiz 0.699, probes 0.430). A0 and A1 evidence was identical under the new reader. On 2026-11-13 the probes were re-graded again with the evidence fixes; PR4 fell from 1.0 to 0.4 when the judge failed the century-window check because the reply never says the dates are Julian YYDDD. The first judge had noted the same gap and passed it, so this is judge variance on a borderline answer. That gives the probe mean of 0.363 shown here.

**What went wrong.** The team recorded the fee-cap decision PC-2025-21 as unconfirmed and never built it, which cost the fee-cap questions and most of probe PR7. A colleague NPC also revealed that decision in sprint 2, earlier than the scenario intended; scenario v3 gates colleague knowledge by sprint to stop that.

**Memory friction.** Most repeated failed Living Memory calls were Bash commands that started with the PowerShell call operator (`& "python.exe" ".../living_memory.py" ...`), which Bash rejects: 13 sessions from 8 agents. This is recorded as a Living Memory bug.

On work cost and re-reads per session this arm was the lowest of seed 1; on probes and quizzes it was not better. See the [scenario v2 analysis](../analysis/v2.md).


## Cost

| Who spent it | Dollars |
|---|---|
| Work sessions (team, merge resolves) | $13.14 |
| Simulated colleagues (chat) | $0.03 |
| Harness (quizzes, grading, probe judging) | $4.73 |
| Run total | $17.90 |
| Sessions without a recorded cost | 0 |


## Efficiency per session

| Kind | Sessions | $/session | Turns | Tool calls | Seconds | Cache-read tokens | Output tokens |
|---|---|---|---|---|---|---|---|
| work | 142 | $0.092 | 16 | 15.9 | 121.8 | 682,333 | 12,511 |
| quiz memory | 14 | $0.030 | 3.1 | 2.1 | 21.2 | 41,288 | 3,682 |
| quiz repo | 14 | $0.113 | 14.8 | 13.8 | 75.5 | 632,283 | 13,507 |


## Quizzes

Should-know scores per fact (1 = every agent who should know it answered correctly). Memory only: answered from memory with the repo denied. With repo: the agent's clone and tools available.

| Fact | What it is | Memory only | With repo | Stores holding it | Should-know coverage | Stale-only stores |
|---|---|---|---|---|---|---|
| T1 | Day count by product | 0.167 | 0.542 | 4 | 0.667 | - |
| T2 | Rounding of interest | 0 | 1 | 2 | 0.2 | - |
| T3 | Legacy date format | 0.125 | 0.75 | 4 | 0.75 | - |
| T4 | Account number masking | 0.214 | 0.679 | 6 | 0.429 | - |
| D1 | Money representation | 0.55 | 1 | 12 | 0.8 | dev-acct, dev-pay |
| D2 | Overdraft fee | 0 | 0 | 6 | 0.667 | dev-ledger, la2, qa |
| H1 | Ownership changes | 0.143 | 0.714 | 11 | 0.857 | - |
| I1 | Retried transfer incident | 0 | 0.25 | 8 | 1 | - |
| O1 | Maintenance fee | 0 | 1 | 0 | 0 | - |
| O2 | Overdraft counting | 0 | 0.625 | 2 | 0.5 | - |
| P1 | Project phase and go-live criterion | 0.375 | 0.458 | 14 | 1 | - |
| P2 | Current owners | 0.208 | 0.458 | 13 | 0.917 | - |
| P3 | Approved deviations from legacy | 0 | 0 | 10 | 0.6 | - |
| E1 | Commit message policy | 0.214 | 1 | 11 | 0.786 | - |
| E2 | CI lint rules | 0.167 | 1 | 7 | 0.333 | - |

- Memory only: all 0.153, should-know 0.227, failure kinds capture_gap 36, ok 50, retrieval_miss 35, stale 7, stale answers 10, missing 0
- With repo: all 0.653, should-know 0.699, failure kinds ok 113, stale 8, retrieval_miss 6, capture_gap 1, stale answers 22, missing 0


## Work probes

Ordinary sprint-4 requests that silently need earlier knowledge; score is the passed share of weighted checks.

| Probe | Agent | Facts | Score | Checks passed | Flag |
|---|---|---|---|---|---|
| PR1 | dev-int2 | T1 | 0.2 | 1/3 | - |
| PR2 | dev-ledger | D2 | 0 | 0/2 | - |
| PR3 | dev-pay | I1 | 0.667 | 2/3 | - |
| PR4 | mig | T3 | 0.4 | 1/2 | - |
| PR5 | sec2 | T4 | 1 | 2/2 | - |
| PR6 | arch | D1 | 0.25 | 1/2 | - |
| PR7 | qa | D2, P3 | 0.25 | 1/2 | - |
| PR8 | po | O1, T1 | 0.5 | 1/2 | - |
| PR9 | ops | E1, E2 | 0 | 0/2 | - |


## Work metrics

| Measure | Value | What it counts |
|---|---|---|
| Re-reads per work session | 5.53 | files and searches the agent had read in an earlier session |
| Re-read share | 0.387 | re-reads over all reads |
| Tool calls before the first change | 11.5 | exploration before the first edit or commit |
| Own repeated failures | 0 | an error the agent already hit in an earlier session |
| Team repeated failures | 4 | an error a teammate hit earlier |
| Repeated failed Living Memory calls | 18 | memory-tool friction, kept apart from work mistakes |
| Stale code lines | 9 | added code matching an outdated decision (heuristic) |
| Joiner cost ratio | 0.82 | joiners' first sessions vs the team median (1 = same) |
| App-check regressions | 0 | a check on main that passed and later failed |


## Planted mistakes

| Trap | What it is | Hits | Repeats |
|---|---|---|---|
| M1 | Commit rejected by policy ENG-7 (first line must start with a tracker key) | 0 | 0 |
| M2 | System.out/err printing in production code (CI lint L1) | 0 | 0 |
| M3 | TODO/FIXME without a ticket key (CI lint L2) | 0 | 0 |


## Memory stores

| Measure | Value |
|---|---|
| Active notes | 95 |
| Maps | 14 |
| Noise-like notes | 27 |
| Living Memory calls | 329 |
| Calls per work session | 1.97 |
| CLI errors | 0 |
| Note updates | 117 |
| Superseded notes | 5 |
| Decision docs with a pointer note | 12 of 19 |
| Hook pre-tool-use p50 / p95 ms | 30.8 / 59.4 (n=2,395) |
| Hook session-end p50 / p95 ms | 31 / 81.7 (n=172) |
| Hook session-start p50 / p95 ms | 578.1 / 769.9 (n=172) |
| Hook stop p50 / p95 ms | 48.8 / 182.9 (n=231) |
| Hook user-prompt p50 / p95 ms | 218.3 / 322.8 (n=224) |


## CI, merges and final code

| Measure | Value |
|---|---|
| CI runs green | 37 of 37 |
| Last CI | green |
| Merge attempts | 144 |
| Conflicts on first try | 2 |
| Unresolved merges | 0 |
| Files swept up uncommitted | 7 |

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
- **Arm:** C: Living Memory
- **Label:** C-s1
- **Semantic search:** yes
- **Started:** 2026-11-11 22:11 UTC
- **Finished:** 2026-11-12 01:14 UTC
- **Duration:** 3 h 2 min
- **Claude Code:** 2.1.322
- **Living Memory tree:** `bee03f6518524309`
- **Harness:** `21903a30f4520878`
- **Scenario files:** `ff6e1052a34acc60`


## Living Memory before this run

- #30 Remediation phase 2: long-prompt retrieval, gotcha snippets, repo briefings, command hints
- #31 Remediation phase 3: repo-keyed maps and briefs, change-aware staleness, hypothesis lifecycle


## Compare

- [Scenario v2 analysis](../analysis/v2.md)
- [Previous run: v2 A1 seed 1](../runs/bank-cobol-springboot-v2-20261111-120652-A1-s1.md)


_2.1.322 (Claude Code) · Living Memory tree bee03f6518524309 · harness 21903a30f4520878_
