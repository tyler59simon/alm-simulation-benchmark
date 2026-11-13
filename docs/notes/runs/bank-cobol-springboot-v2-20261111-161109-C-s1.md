Living Memory with remediation phases 1 to 3 (PR #30, phases 1 and 2; PR #31, phase 3) and semantic search on. It started after A0 and A1 had finished: after an out-of-memory crash, the user chose one run at a time.

**Grading history.** The first grading gave this run a repo-quiz should-know score of 0.348 and a probe mean of 0.457. Living Memory's Stop reminder made agents save notes after answering, and the harness had read that housekeeping message instead of the answer. After the reply-reader fix (harness commit `fe6a593`), the run was regraded from its transcripts (repo quiz 0.699, probes 0.430). A0 and A1 evidence was identical under the new reader. On 2026-11-13 the probes were re-graded again with the evidence fixes; PR4 fell from 1.0 to 0.4 when the judge failed the century-window check because the reply never says the dates are Julian YYDDD. The first judge had noted the same gap and passed it, so this is judge variance on a borderline answer. That gives the probe mean of 0.363 shown here.

**What went wrong.** The team recorded the fee-cap decision PC-2025-21 as unconfirmed and never built it, which cost the fee-cap questions and most of probe PR7. A colleague NPC also revealed that decision in sprint 2, earlier than the scenario intended; scenario v3 gates colleague knowledge by sprint to stop that.

**Memory friction.** Most repeated failed Living Memory calls were Bash commands that started with the PowerShell call operator (`& "python.exe" ".../living_memory.py" ...`), which Bash rejects: 13 sessions from 8 agents. This is recorded as a Living Memory bug.

On work cost and re-reads per session this arm was the lowest of seed 1; on probes and quizzes it was not better. See the [scenario v2 analysis](../analysis/v2.md).
