# Run log

_alm-simulation-benchmark_

Every simulation run, its statistics, the analyses across runs and the Living Memory changes each run measured.

## About this log

alm-simulation-benchmark runs a simulated bank modernization team of headless Claude Code agents through scripted sprints, then scores what they knew and how well they worked. Each run uses one memory arm:

- **A0:** memory off. From scenario v2 on, both Living Memory's hooks and Claude Code auto-memory are off; the v1 A0 run switched off only Living Memory.
- **A1:** Claude Code's built-in auto-memory.
- **C:** Agentic Living Memory, one private store per agent.

Runs are compared only within one scenario version, because each version changes prompts, tools and facts. Every number on these pages is generated from the run folders by `python -I sim.py docs`; the text under "Log entry" and "Reading" is written by hand in `docs/notes/`.

To add a run to the log: finish it with `sim.py pipeline`, run `sim.py analyze --run RUN`, write `docs/notes/runs/RUN.md`, then run `sim.py docs`.


## Latest run

**[v2 C seed 1](runs/bank-cobol-springboot-v2-20261111-161109-C-s1.md)**: bank-cobol-springboot-v2 · 2026-11-11 22:11 UTC · 3 h 2 min

| Probe score | Quiz with repo | Quiz memory only | Work cost | Sessions |
|---|---|---|---|---|
| 0.363 | 0.699 | 0.227 | $13.14 | 230 |


## Runs: scenario v2

- [v2 C seed 1](runs/bank-cobol-springboot-v2-20261111-161109-C-s1.md) (C): 2026-11-11 22:11 UTC · 230 sessions · work $13.14 (probes 0.363)
- [v2 A1 seed 1](runs/bank-cobol-springboot-v2-20261111-120652-A1-s1.md) (A1): 2026-11-11 18:06 UTC · 193 sessions · work $14.46 (probes 0.485)
- [v2 A0 seed 1](runs/bank-cobol-springboot-v2-20261111-120632-A0-s1.md) (A0): 2026-11-11 18:06 UTC · 193 sessions · work $13.73 (probes 0.53)


## Runs: scenario v1

- [v1 A0](runs/bank-cobol-springboot-20261111-093450-memoff.md) (A0): 2026-11-11 15:34 UTC · 99 sessions · work $5.48 (quiz 0.858)
- [v1 C](runs/bank-cobol-springboot-20261111-061514.md) (C): 2026-11-11 12:15 UTC · 88 sessions · work $6.32 (quiz 0.062)


## Analysis

- [Scenario v1](analysis/v1.md): 2 runs: A0, C
- [Scenario v2](analysis/v2.md): 3 runs: A0, A1, C


## Living Memory changes

- [Pull requests on the run timeline](living-memory-changes.md): 98 merges on main (68 not yet measured)


_5 runs · 2 scenario versions · generated from runs/ by sim.py docs_
