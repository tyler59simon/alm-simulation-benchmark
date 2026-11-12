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
| Work probes (mean of 9, 0-1) | 0.557 | 0.485 | 0.430 |
| Quiz with repo, should-know | 0.715 | 0.715 | 0.699 |
| Quiz memory only, should-know | - | - | 0.227 |
| Steps per probe | 12.0 | 11.9 | 10.3 |
| Cost per work session | $0.097 | $0.102 | $0.092 |
| Run cost | $16.59 | $17.65 | $17.81 |

## Caveats
- One run per arm: a single probe flipping moves the probe mean by 0.11, so no arm is shown to be better.
- C was regraded from its transcripts after a harness fix: Living Memory's Stop reminder made agents save notes
  after answering, and the harness had read that housekeeping message instead of the answer. A0 and A1 evidence
  was identical under the new reader.
- C lost the fee-cap questions (D2, P3) and most of probe PR7 because its team recorded PC-2025-21 as
  unconfirmed and never built it; the NPC also revealed it in sprint 2, earlier than the scenario intended.
- The memory-only quiz ran after the repo quiz, so memory-only scores include some knowledge taken from the repo.
- Built-in memory (A1) saved one note in the whole run.

Reproduce: `python -I sim.py pipeline bank-cobol-springboot-v2 --memory off|builtin|on [--semantic] --label NAME`;
compare with `python -I sim.py compare-arms A0=RUN A1=RUN C=RUN`.
