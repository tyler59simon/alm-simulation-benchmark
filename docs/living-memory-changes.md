# Living Memory changes

_agentic-living-memory main_

98 merges on main; 68 not yet measured by any run.

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
- #44 Docs: rename lm-team-sim to alm-simulation-benchmark (2026-11-13)
- #45 Note currency: every note stays current, with a review worklist, an activity log and a user brief (2026-11-13)
- #46 Ingest prompt and pull guard for decision-document reminders (2026-11-13)
- #47 Refuse positional values in capture --title (extra --detail values replaced titles) (2026-11-13)
- #48 Note views: synced HTML dashboards for picked notes (2026-11-13)
- #49 Fix worklist and Bash hints, list all thirteen note types (2026-11-14)
- #50 Keep note freshness honest: verification baseline, source states, currency cache (2026-11-14)
- #51 Put child domains in scope, auto-resolve finished work, add unbind (2026-11-14)
- #52 remap keeps the verification baseline of a moved note (2026-11-14)
- recover refuses final-state reversals; marker before journal; report roll-forward results (2026-11-14)
- MAINT-1B: pinned notes, last_retirement record, restore and plan restore (2026-11-14)
- Pins block auto-resolve; damaged pending journals warn; pin-only vault edits keep updated (2026-11-14)
- MAINT-1C: maintenance configuration, accounting and run records (2026-11-14)
- Maintenance accounting keeps its gates when the checkpoint is lost (2026-11-14)
- Early retry after a config change needs the latest attempt to be the failure (2026-11-14)
- Releasing an older reservation keeps the latest attempt's failure (2026-11-14)
- release only frees reservations that never launched; recovery rolls forward first (2026-11-14)
- MAINT-1D: maintenance candidates and evidence packet (2026-11-14)
- MAINT-1D: tool-less Claude reviewer adapter (2026-11-14)
- MAINT-1D: maintenance executor and run() (2026-11-14)
- Maintenance executor rechecks successors and map currency; batches fit the report (2026-11-14)
- MAINT-1E: maintenance command, SessionStart scheduling and summary line (2026-11-14)
- Maintenance reports only a live provider block; decisions keep their reason (2026-11-14)
- MAINT-1E: persist maintenance state through backup, restore, relocation and Obsidian (2026-11-14)
- MAINT-1E: document automatic note maintenance and the archive exception (2026-11-14)
- Restore and relocation always leave maintenance disabled; damaged files do not block recovery (2026-11-14)
- inspect-plan shows a damaged file that a restore plan repairs (2026-11-14)
- MAINT-1F: dry-run gate script; a miscopied revision defers one note (2026-11-14)
- Maintenance report validation is idempotent; the gate scores patches (2026-11-14)
- Gate scores patches with the executor's rules; copy accepts _global (2026-11-14)
- Maintenance reviewer names candidates by one packet key (2026-11-14)
- FEAT-6: one-line summaries and actors in note history (2026-11-14)
- FEAT-2: recap command and Obsidian Recap page (2026-11-14)
- History and recap: fixes from the Codex review (2026-11-14)
- Fix Codex review findings in the alm renderer and installer retries (2026-11-14)
- Add the alm command: launcher, terminal text output, agent CMD (2026-11-14)
- alm: help line for recap; print markdown results as written (2026-11-14)
- #53 Support Python 3.10 to 3.15: parse Z timestamps everywhere, add manua… (2026-11-14)
- Capture coverage, and summary and actor on bare history rows (UX-C5) (2026-11-14)
- Stop: verified-fix reminder and plan approval as a decision (UX-C3, UX-C4) (2026-11-14)
- Stop: no second decision after an approved plan; grep misses are not fixes (2026-11-14)
- Stop: keep a plan approval next to a preference; count shell edits, not failed ones (2026-11-14)
- Stop: a shell command counts as the edit only when it plainly writes (2026-11-14)
- Stop: shell edits must also not be read-only; accept sed --in-place (2026-11-14)
- #54 Add a per-session off switch: alm off, alm on, alm status, LIVING_MEMORY_OFF (2026-11-14)
- Retrieval: resolved bugs and risks stay retrievable in prompts and file hints (UX-C6) (2026-11-14)
- Retrieval: portable notes from sibling projects on weak matches (UX-C7) (2026-11-14)
- Retrieval: review fixes for UX-C6 and UX-C7 (2026-11-14)
- Retrieval: resolve foreign-domain aliases in the prompt's own scope (2026-11-14)
- Retrieval: a one-word prompt never crosses projects (2026-11-14)
- Retrieval: a strongly matching resolved bug is placed, not halved (2026-11-15)
- Retrieval: place a resolved hit from its merged position before reinforcement (2026-11-15)
- Test clock: shift record time in headless runs for simulations (2026-11-15)
- eval: measure false injection through the whole prompt hook (2026-11-15)
- eval: start each hooked case with SessionStart, in its own session (2026-11-15)
- eval: no auto-resolve or background work in a hooked case's SessionStart (2026-11-15)


_98 merges · 5 runs_
