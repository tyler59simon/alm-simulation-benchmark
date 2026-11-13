# Seed 1 evaluation report (scenario bank-cobol-springboot-v2)

Full report: `reports/seed1-report.html`, also published as a private artifact at
https://claude.ai/artifact/H9af68fLAGwT9ggCj9n6ET.

## Setup
A simulated 14-agent bank modernization team ran the same four-sprint project once per arm:

| Arm | Memory | Run folder (`runs/`) |
|---|---|---|
| A0 | none (hooks and Claude Code auto-memory off) | `bank-cobol-springboot-v2-20261111-120632-A0-s1` |
| A1 | Claude Code built-in auto-memory | `bank-cobol-springboot-v2-20261111-120652-A1-s1` |
| C | Living Memory, remediation phases 1-3, semantic search on | `bank-cobol-springboot-v2-20261111-161109-C-s1` |

Seeds 2 and 3 were cancelled; `...-191400-A0-s2` is a partial run marked aborted.

## Headline numbers
| Measure | A0 | A1 | C |
|---|---|---|---|
| Work probes (mean of 9, 0-1) | 0.530 | 0.485 | 0.363 |
| Quiz with repo, should-know | 0.715 | 0.715 | 0.699 |
| Quiz memory only, should-know | - | - | 0.227 |
| Steps per probe | 12.0 | 11.9 | 10.3 |
| Cost per work session | $0.097 | $0.102 | $0.092 |
| Work cost (work sessions and merge resolves) | $13.73 | $14.46 | $13.14 |
| Harness cost (quizzes, grading, probe judging) | $3.06 | $3.38 | $4.73 |
| Run cost | $16.80 | $17.87 | $17.90 |

The run cost includes the harness measuring the run, and arm C takes one more quiz than A0 and A1, so compare arms on
work cost. The work-cost and harness rows were added on 2026-11-13 by re-analyzing the runs with metrics schema 2 (the
earlier analysis stays in each run folder as `metrics.v1.json`).

## Schema 2 work metrics (re-analysis, no new runs)
| Measure | A0 | A1 | C |
|---|---|---|---|
| Re-reads per work session | 6.41 | 7.11 | 5.53 |
| Tool calls before the first change | 11.3 | 12.1 | 11.5 |
| Repeated work failures (own / team) | 2 / 0 | 3 / 5 | 0 / 4 |
| Repeated failed Living Memory calls (own / team) | - | - | 6 / 12 |
| Stale code lines (heuristic) | 15 | 5 | 9 |
| Joiner cost ratio (2 joiners) | 1.96 | 0.85 | 0.82 |
| App-check regressions | 1 | 0 | 0 |

Probe score against A0, probe by probe: A1 -0.044 (95% CI -0.367 to +0.278), C -0.167 (95% CI -0.378 to +0.056); neither
interval excludes zero. Most of C's repeated failed Living Memory calls (13 sessions, 8 agents) are Bash commands that start
with the PowerShell call operator, `& "python.exe" ".../living_memory.py" ...`, which Bash rejects.

## Caveats
- One run per arm: a single probe flipping moves the probe mean by 0.11, so no arm is shown to be better.
- C was regraded from its transcripts after a harness fix: Living Memory's Stop reminder made agents save notes
  after answering, and the harness had read that housekeeping message instead of the answer. A0 and A1 evidence
  was identical under the new reader.
- Probes were re-graded on 2026-11-13 with the evidence fixes (tracker pages limited to the session's own edits, diffs
  from the merged main), for $0.53. Ten probes got a new judge call; two changed score, A0 PR7 (1.0 to 0.75) and C PR4
  (1.0 to 0.4). In both, the engineer's reply was unchanged and the judge's old and new reasons describe the same gap
  (C's reply never says the dates are Julian YYDDD; A0's draft calls the deviation list empty), so the flips look like
  judge variance on borderline answers rather than an effect of the removed evidence. The earlier grades are kept in
  each run folder as `probes.v1/`.
- C lost the fee-cap questions (D2, P3) and most of probe PR7 because its team recorded PC-2025-21 as
  unconfirmed and never built it; the NPC also revealed it in sprint 2, earlier than the scenario intended.
- The memory-only quiz ran after the repo quiz, so memory-only scores include some knowledge taken from the repo.
- Built-in memory (A1) saved one note in the whole run.

Reproduce: `python -I sim.py pipeline bank-cobol-springboot-v2 --memory off|builtin|on [--semantic] --label NAME`;
compare with `python -I sim.py compare-arms A0=RUN A1=RUN C=RUN`.
