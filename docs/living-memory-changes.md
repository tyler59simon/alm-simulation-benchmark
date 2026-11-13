# Living Memory changes

_agentic-living-memory main_

42 merges on main; 12 not yet measured by any run.

## Reading

Which Living Memory changes each run measured:

- **v1 C (first run):** main through PR #28, before any remediation work.
- **v1 A0, v2 A0 and v2 A1:** Living Memory was installed but switched off, so they measured no Living Memory change. Their installed tree hash is recorded only for completeness.
- **v2 C seed 1:** PR #30 (remediation phases 1 and 2: capture triggers for decisions and decision docs, the project brief, long-prompt retrieval, session-start gotchas and command hints) and PR #31 (phase 3: repo-keyed maps and briefs, change-aware staleness). These targeted the v1 findings: decisions never captured and maps that went stale.

The v1 and v2 C runs used different scenarios, so the difference between them is not a Living Memory effect.

Everything merged after v2 C seed 1 is unmeasured, including PR #35 (fixes from the seed-1 findings) and the knowledge-base phases #32 to #34. The next Living Memory run will measure all of them at once, so a gain or loss cannot be tied to one PR. Smaller runs between merges would be needed for that.

The installed tree hash changed twice with no merged PR in between: from v1 C to v1 A0, and from v1 A0 to v2 A0. The hash also covers compiled `__pycache__` files, so a recompile or a deploy of an unmerged branch could each explain it; which one is not confirmed. Neither matters for those runs' results, since Living Memory was off in both.


## Timeline

Each run with the Living Memory pull requests merged on main since the previous run. Merge time is not deploy time: the installed tree hash in the run manifest is the evidence of what ran, and it also covers compiled `__pycache__` files, so a hash can change with no code change.

| Run | Started | LM hooks | Installed tree | Tree vs previous run | PRs merged since the previous run |
|---|---|---|---|---|---|
| [v1 C](runs/bank-cobol-springboot-20261111-061514.md) | 2026-11-11 12:15 UTC | on | `6f7e6c5dc58571ab` | first run | main at #28 feat: reviewed procedural learning (phase 1) |
| [v1 A0](runs/bank-cobol-springboot-20261111-093450-memoff.md) | 2026-11-11 15:34 UTC | off | `6b94fa536ab5ccb5` | changed with no merged PR (redeploy or local build) | none |
| [v2 A0 seed 1](runs/bank-cobol-springboot-v2-20261111-120632-A0-s1.md) | 2026-11-11 18:06 UTC | off | `ff1474191da2317b` | changed with no merged PR (redeploy or local build) | none |
| [v2 A1 seed 1](runs/bank-cobol-springboot-v2-20261111-120652-A1-s1.md) | 2026-11-11 18:06 UTC | off | `ff1474191da2317b` | same | none |
| [v2 C seed 1](runs/bank-cobol-springboot-v2-20261111-161109-C-s1.md) | 2026-11-11 22:11 UTC | on | `bee03f6518524309` | changed | #30 Remediation phase 2: long-prompt retrieval, gotcha snippets, repo briefings, command hints; #31 Remediation phase 3: repo-keyed maps and briefs, change-aware staleness, hypothesis lifecycle |


## Merged since the last run (not yet measured)

- #32 Remediation phase 4: project knowledge base, part 1 (source library and ask) (2026-11-11)
- #33 Remediation phase 5: knowledge base digests (source provenance, ingest-scan, ingest_run driver) (2026-11-11)
- #34 Remediation phase 6: Confluence and Notion connectors for the knowledge base (2026-11-11)
- #35 Seed-1 fixes: Stop reminders, multi-question retrieval, UNCONFIRMED marking, latency caches, dogfood eval (2026-11-12)
- #36 Learning: Phase 2 real-agent evaluation; require an exclusion at admission (2026-11-12)
- #37 Change registry: changes.json, change-plan and changes (2026-11-12)
- #38 Backlog fixes: BOM bindings, default concerns, corrupt journals and plan pruning, private-tag gaps (2026-11-12)
- #39 Backlog quick wins: Python 3.10 tests, map budget, retag and store guards, ref flags (2026-11-12)
- #40 Plain lede-first note layout, per-type sections and style warnings (2026-11-12)
- #41 Section-level memory units, optional sqlite-vec search and a token-aware injection controller (2026-11-13)
- #42 Capture reliability: signal priority, covering-note settlement, ingest selection, protocol wording (2026-11-13)
- #43 Fix blocked ingest captures being recorded as skips; auto-allow single-quoted CLI paths (2026-11-13)


_42 merges · 5 runs_
