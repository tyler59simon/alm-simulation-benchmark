Which Living Memory changes each run measured:

- **v1 C (first run):** main through PR #28, before any remediation work.
- **v1 A0, v2 A0 and v2 A1:** Living Memory was installed but switched off, so they measured no Living Memory change. Their installed tree hash is recorded only for completeness.
- **v2 C seed 1:** PR #30 (remediation phases 1 and 2: capture triggers for decisions and decision docs, the project brief, long-prompt retrieval, session-start gotchas and command hints) and PR #31 (phase 3: repo-keyed maps and briefs, change-aware staleness). These targeted the v1 findings: decisions never captured and maps that went stale.

The v1 and v2 C runs used different scenarios, so the difference between them is not a Living Memory effect.

Everything merged after v2 C seed 1 is unmeasured, including PR #35 (fixes from the seed-1 findings) and the knowledge-base phases #32 to #34. The next Living Memory run will measure all of them at once, so a gain or loss cannot be tied to one PR. Smaller runs between merges would be needed for that.

The installed tree hash changed twice with no merged PR in between: from v1 C to v1 A0, and from v1 A0 to v2 A0. The hash also covers compiled `__pycache__` files, so a recompile or a deploy of an unmerged branch could each explain it; which one is not confirmed. Neither matters for those runs' results, since Living Memory was off in both.
