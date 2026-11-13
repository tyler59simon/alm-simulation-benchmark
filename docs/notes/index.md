alm-simulation-benchmark runs a simulated bank modernization team of headless Claude Code agents through scripted sprints, then scores what they knew and how well they worked. Each run uses one memory arm:

- **A0:** memory off. From scenario v2 on, both Living Memory's hooks and Claude Code auto-memory are off; the v1 A0 run switched off only Living Memory.
- **A1:** Claude Code's built-in auto-memory.
- **C:** Agentic Living Memory, one private store per agent.

Runs are compared only within one scenario version, because each version changes prompts, tools and facts. Every number on these pages is generated from the run folders by `python -I sim.py docs`; the text under "Log entry" and "Reading" is written by hand in `docs/notes/`.

To add a run to the log: finish it with `sim.py pipeline`, run `sim.py analyze --run RUN`, write `docs/notes/runs/RUN.md`, then run `sim.py docs`.
