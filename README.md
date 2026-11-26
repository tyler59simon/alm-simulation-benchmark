# alm-simulation-benchmark

A repeatable harness that tests Agentic Living Memory (LM) in a simulated enterprise team. Each team member is a real headless Claude Code session (`claude -p`) with its **own private LM store**, so the full hook pipeline runs exactly as it does for a real user: session-start injection, prompt retrieval, guards, Stop reminders and capture receipts. The team works over several sprints on a shared git repo. Scripted events with known answers make memory measurable. At the end, a memory-only quiz and an analyzer score what each agent's memory actually kept.

Run folders are never deleted, so every run stays available for comparison (for example before and after an LM change).

## Layout
- `sim.py`: the CLI (see `python sim.py --help`).
- `simkit/`: the generic engine. Nothing in it is specific to a scenario.
  - `engine.py`: init, sprints (waves, merges, CI), handovers, quiz, grading, smoke test, isolation.
  - `sessions.py`: the `claude -p` launcher: per-agent `LIVING_MEMORY_ROOT`, budget, timeout, deny rules, stream-json transcript.
  - `clock.py`: the simulated calendar (`init --clock`, see below).
  - `stores.py`: store bootstrap (bind, then `migrate --schema`, then `taxonomy add`, then sandbox marker) and export/import handover. It never calls `setup`, so the real `config.json` is never touched.
  - `gitops.py`: bare origin, one persistent clone per agent, an integration clone that merges and runs CI.
  - `analyze.py`: `metrics.json` (fixed schema), the summary, and `compare`.
  - `config.json`: machine paths (Python, installed LM CLI, claude). Override any key with `SIMKIT_<KEY>`.
- `scenarios/<name>/`: a scenario, as data only.
  - `scenario.json`: roster (id, name, title, tier, briefing, `joins`, `leaves_after`), tiers (model, effort, per-session budget), waves, sprint count, parallelism, spend limit, seed copy map, toolchain env, prime and CI commands, tool allow and deny rules, extra taxonomy tags.
  - `events.json`: per-sprint `theme`, plus per-agent `task` and optional `memo` (`event`, `from`, `text`) for information only that agent receives. Also `handovers` (`before_sprint`, `from`, `to`, `import_bundle`) and `default_task`.
  - `ground_truth.json`: facts with `answer`, optional `stale_answer`, `should_know` (agent ids) and regex `patterns.current` / `patterns.stale`, which are used to find the fact in stores.
  - `quiz.json`: `intro`, plus `questions` (`id`, `fact`, `text`).
  - `app_checks.json`: regex presence checks over the final code (heuristic).
  - `briefings/_team.md` (with `{name} {title} {team_size} {roster}` placeholders) and one role file per agent. Briefings never mention memory; agents get the LM protocol only from the global CLAUDE.md and the hooks, the same as a real user.
  - `seed/` (copied into the repo) and `oracle/` (hidden material, such as a reference model). Agents are denied access to the scenario, the harness, other agents' clones and stores, and the real store.
- `runs/<scenario>-<timestamp>[-label]/` (gitignored, kept forever):
  - `manifest.json`: scenario hash, LM app tree hash, LM source commit (`living_memory.repo_commit`, from `lm_repo`), the CLI's `version --json` output (`living_memory.cli_version`; both null when they cannot be read), Claude Code version, harness hash, options and the `clock` record.
  - `scenario/`: a frozen copy of the scenario the run used.
  - `origin.git`, `integration/` and `ws/<agent>/`: the repos.
  - `stores/<agent>/`: the memory stores. `stores/_grader` is unbound, and grading runs with hooks disabled.
  - `transcripts/<key>.jsonl`: each session's prompt, stream-json output and stderr.
  - `state.json` (resumable steps and sessions), `costs.jsonl`, `ci.jsonl`, `merges.jsonl`, `branches.jsonl`, `handovers.jsonl`.
  - `quiz/answers`, `quiz/grades`, `stores-readout.json`, `review-at-quiz.json`, `metrics.json`, `sim.log`.

## Running
```
python sim.py smoke bank-cobol-springboot          # ~$0.10, checks hooks, isolation, deny rules, effort flag, memory calls
python sim.py smoke bank-cobol-springboot --clock  # also checks that a captured note carries the simulated time
python sim.py init  bank-cobol-springboot          # new run, primes Maven, CI on the seed
python sim.py run   [--through N]                  # sprints; resumable, stops at the spend limit
python sim.py quiz && python sim.py grade && python sim.py readout && python sim.py analyze
python sim.py verify-isolation                     # no run session in the real store or in another agent's store
python sim.py compare RUN_A RUN_B
```
Use the Python 3.10 interpreter in `simkit/config.json`, with `-I`. Runs are long (hours), so start `run` in the background. Every step is resumable: re-running a command skips the sessions and steps that already finished.

## Scenario v2 (realistic) and evaluation arms
`scenarios/bank-cobol-springboot-v2` follows what published agent benchmarks found mattered for realism: TheAgentCompany (a company's tools outside the repo, plus simulated colleagues), MemoryCode (knowledge applied without being asked to recall it), MemoryAgentBench (facts that change), SWE-ContextBench (cost and time, not just accuracy), τ-bench (repeated runs) and the LoCoMo critiques (deterministic checks where possible, and an audited judge).

**How the scenario works:**
- **Short prompts in the engineer's voice:** an onboarding prompt on day 1 and for joiners, then task prompts such as "pick up LH-20". The engineer's identity goes in an appended system prompt, the way a personal `CLAUDE.md` would carry it.
- **Conventions live in the repo `CLAUDE.md`,** which points to the wiki.
- **Tools outside the repo (`runs/<run>/workspace`):**
  - `tracker/` (Jira-like, `bin/tracker.py` allocates unique keys);
  - `wiki/` (Confluence-like, including stale HTML exports);
  - `chat/` (Slack DMs through `bin/team_chat.py`, with business colleagues played by Haiku from `npcs.json`; only the current sprint is visible);
  - `hooks/` (company git hooks, installed via `core.hooksPath`).
- **Natural traps:** a commit-msg hook (policy ENG-7, a ticket key on the first line) and CI-only lint rules (`scenario.json` `lint`, reported in a `#ci-bot` message when main goes red).
- **Facts change twice** (the overdraft fee, money type, ownership). There are two handovers and a vacation with cover. Each sprint has 3 working days.
- **Work probes** (`probes.json`) in sprint 4: ordinary requests that silently need earlier knowledge. `sim.py probes` grades them with regex checks plus an LLM judge.
- **Grader audit:** `sim.py grade-audit` measures the judge's false-accept and false-reject rates on `grader_calibration.json`.

**Arms** (`init --memory ...`):

| Arm | Flag | What it is |
|---|---|---|
| A0 | `off` | No memory at all: hooks disabled and Claude Code auto-memory disabled. |
| A1 | `builtin` | Claude Code as shipped: auto-memory on, no Living Memory. |
| C | `on` | Living Memory as installed. |
| D | `kb-quiz` on a finished run | A brand-new agent whose fresh store indexes the finished repo, wiki and tracker as a knowledge base takes the memory-only quiz. Built, not yet run. |

**Commands:**
- `sim.py pipeline SCENARIO --memory M --label L` runs one arm end to end and is resumable with `--run`. Arm C takes the memory-only quiz before the repo quiz, and store contents are snapshotted (`stores-at-end.json`) before any quiz, so the repo quiz cannot feed the memory score.
- `sim.py kb-quiz --run RUN [--digests-budget USD]` runs arm D against a finished run; `--digests-budget` also has `scripts/ingest_run.py` write digest notes first.
- `sim.py compare-arms A0=r1,r2,r3 A1=... C=...` prints mean ± sd per metric across seeds: probe score, the quizzes, efficiency (turns, tool calls, $ per session), CI share, repeated mistakes and stale notes.

**Harness behaviour worth knowing:**
- A session ends 30 s after its final `result` event; background commands an agent left running are killed (`ended_after_result` in the session row).
- Replies are read with `simkit/replies.py`: the first result, plus the text written before any trailing Living Memory housekeeping.
- Agent sessions get `LIVING_MEMORY_HEADLESS=1`.
- A memory call is recognised by `common.lm_call(command)`, which returns the subcommand (`other` for an unknown one) or None. It accepts `python .../living_memory.py ...` and the `alm` / `alm.exe` launcher, with an optional leading `&`, quoted paths and the global options `--json`, `--domain`, `--root`, `--cwd` and `--actor` before the subcommand. It follows variables, shell functions and `eval` the command defines itself (`PY=...; LM=...; "$PY" "$LM" capture`). Only the first word of a command or chain stage counts, so `realm`, `palm` and an `alm` inside a path do not match. Run counts of memory calls made with the older substring test can differ slightly on re-analysis (for example `cat living_memory.py` is no longer a call).
- Probe grades are keyed by the evidence graded; an earlier verdict on identical evidence is reused.
- `metrics.json` `quiz_repo_reads` lists memory-quiz commands that named a repo path or `~/.claude/projects` (it should be empty); `quiz_other_shell` lists every non-Living-Memory shell command in the memory quiz.
- Quiz scores count every taker x question: an unanswered or ungraded question scores 0 as `missing`. A probe whose session never ran scores 0 (`missing`); an unparsed judge reply leaves the probe unscored (`judge_error`) for a re-grade.
- Probe evidence holds only tracker and wiki files the session's own tools named or created, and after a merge conflict the diff starts at the main the agent merged in. Source files come before documents, each capped at 4,000 characters.
- A session that ends without a result event (timeout) has no known cost; `spent()` and the spend limit count its budget cap (`cost_bound_usd`).

## Simulated calendar (`--clock`)
`init --clock` (also on `pipeline`) gives the run a calendar, so Living Memory's time-based features (review dates, staleness, the headless auto-resolve of finished plan, bug and risk notes after 3 simulated days) are exercised. It is off by default, so earlier scenarios and reruns stay reproducible. The choice is stored in the manifest (`options.clock` and `clock: {enabled, days_per_sprint, start}`); resumed runs read it from there.
- `clock_days_per_sprint` in `simkit/config.json` (default 14; `SIMKIT_CLOCK_DAYS_PER_SPRINT` overrides it) is the length of a sprint in simulated days. The simulated start is the run's creation time.
- Sprint `s`, working day `d` (1-based) is `start + (s-1) * D + (d-1) * floor(D / W)` days, with D = `clock_days_per_sprint` and W = the scenario's working days per sprint. With D = 14 and W = 3, days start 4 days apart.
- The end-of-sprint review runs on `start + s * days_per_sprint - 1` days, the last day before the next sprint starts.
- The quizzes, probe and grader sessions and the knowledge-base quiz (including its digest step) run on `start + (sprints + 1) * days_per_sprint` days: one sprint length after the last sprint ended. The readout runs one day later, because the quiz sessions' own clocks keep running in real time from that start.
- Agent sessions get `LIVING_MEMORY_CLOCK_OFFSET_SECONDS` (simulated session start minus real time at launch; Living Memory honours it only with `LIVING_MEMORY_HEADLESS=1`, which every session has) and `GIT_AUTHOR_DATE` / `GIT_COMMITTER_DATE` (ISO 8601 with offset), so the agent's own commits carry simulated dates. Harness Living Memory calls (`stores.lm`, which then also sets `LIVING_MEMORY_HEADLESS=1`) and harness git operations (auto-commits, merges) use the time of the phase being run. The session row records `sim_time`, and `workspace/.clock.json` records `time`.
- Sessions of one wave start at the same simulated time. Real time keeps running inside a session, so a long session ends a few simulated minutes after it started.

## End-of-run readout (`readout`, schema 4)
`sim.py readout [--run RUN]` runs in `pipeline` after the quizzes, grading and probes, before `analyze`. For each agent store of a run with Living Memory on it runs read-only commands with `LIVING_MEMORY_ROOT` set to that store and the scenario's domain, and writes `stores-readout.json`: `stats --days 120 --json`, `log --limit 100000 --json`, `recap --days <min(90, run length)> --json` and `maintenance history --limit 1000 --json`. A window the installed CLI caps (`stats` allows 30 days and `recap` 90) is retried at the cap and recorded under `days_used`. A command that fails is recorded under that store's `errors` and the others still run. Recap's `markdown` copy is dropped. The step is `readout`, so a resumed run does not repeat it. Before the first quiz the harness also writes `review-at-quiz.json`, the review worklist of every store at that moment (read-only); the readout folds it in as `review_at_quiz`.

`metrics.json` `readout` (schema 4; None or empty when the run has no `stores-readout.json`, and the log-based fields are 0 for runs that logged no debug detail):
- `capture_coverage`: per store `{days, mutating, covered, ratio}` and `mean_ratio` over the stores that have a ratio. A run with `--clock` takes a `stats` snapshot per store at the end of each sprint (inside the review step, appended to `stats.jsonl`; the window is `clock_days_per_sprint - 1` days, at most 30, which starts on the sprint's first day and does not overlap the previous snapshot), because the CLI's stats window is 30 days and such a run spans about 70. The per-sprint mutating and covered counts are summed (`source: sprints`). Without snapshots (no clock, or older runs) the end-of-run `stats` is used.
- `reminders_by_kind`: the Stop reminders by kind (`fix`, `decision`, ...) from the same stats, summed over the stores and sprints.
- `recap_days_needed`, `recap_truncated`: the readout's `recap` window is `min(90, simulated run length)` days; `recap_truncated` is true when the run is longer than 90 days.
- `fix_reminder_followthrough`: sessions with a Stop hook row `reason: reminded:fix` in a store's logs, how many had a successful `capture` command in the same session after it, and the rate.
- `actors`: the `log` rows by actor (maintenance, auto_resolve, plan for operations before 2026-11-26, undo, obsidian, `agent:<harness>`, command).
- `auto_resolved`: `log` rows with actor `auto_resolve` and event `resolved`.
- `due_at_quiz`: the review worklist size per store (`due`) and in total at the first quiz.
- `call_operator_denies`: pre-tool-use hook rows with decision `deny:call-operator` (a leading `&` in a Bash command).
`compare-arms` lists these next to the other metrics.

## Review metrics (schema 3)
Schema 3 adds `status_snapshots` (active notes of type `status`, per store and in `totals`) and, for runs with Living Memory on, an end-of-sprint review:
- After each sprint's last day the harness runs `review --domain D --limit 100` on every agent store and appends `{sprint, agent, counts, items}` to `reviews.jsonl` (a failing store is logged and skipped). The step is `sN/review`, so a resumed run does not repeat it.
- `init --review-user` (also on `pipeline`) adds a simulated user: for each `archive` row it runs `archive REF` (a direct, undoable write), recorded under `applied`. Merge, update, confirm and other rows are only logged.
- `metrics.json` `review` (absent when the run has no `reviews.jsonl`): `worklist_precision` (real / judged, null when nothing was judged), `judged`, `unjudged`, `by_kind` {rows, judged, real}, `review_rows` (worklist size by kind per sprint) and `review_archives` (`plans_applied` in runs before 2026-11-26). A row is judged under its first kind against the note as it is in the store at analysis time (the row's title and type when the note is gone): stale and due are real for a status note or a note matching a fact's stale and not its current patterns, false when it matches a current pattern; duplicate is real when the note and its pair match the same fact; warned and noisy are real when the text matches the noise patterns and false when the note holds a current fact. Anything else is unjudged.

## Work metrics (schema 2)
`analyze` computes these offline from transcripts, git and stores, so older runs can be re-analyzed at no model cost (keep the old file as `metrics.v1.json` first):
- **Cost split** (`totals`): `work_cost_usd` (work sessions and merge resolves), `chat_cost_usd` (simulated colleagues) and `harness_cost_usd` (quizzes, grading, probe judging). Compare arms on work cost: arm C takes one more quiz than A0 and A1, so its run total carries more harness cost.
- **Tokens** (`efficiency.*.tokens`): mean input, cache-read, cache-creation and output tokens per session.
- **Rediscovery** (`rediscovery`): files and searches a session read that the same agent had read in an earlier session, and tool calls before the first edit or commit.
- **Repeated failures** (`repeat_failures`): tool errors normalized to a signature; an own repeat is an error the agent hit in an earlier session, a team repeat one a teammate hit earlier. Failed Living Memory calls are counted apart (`lm_*`).
- **Stale actions** (`stale_actions`): code lines a session added that match a fact's stale patterns, after the first scripted message stating the current answer. Heuristic: read the hits before quoting the number.
- **Ramp-up** (`ramp_up`): joiners' first three sessions' cost, turns and tool calls as a ratio of the steady team's median on the same days.
- **Regressions** (`app_history`): `app_checks.json` evaluated on main after every CI step; a check that passed and later fails is a regression.
- **Paired probes** (`compare-arms`): each arm against the first, probe by probe, with a bootstrap 95% interval and win/tie/loss counts.

## Scenario v3
`scenarios/bank-cobol-springboot-v3` is v2 plus three fixes found in seed 1 (v2 stays unchanged so its runs reproduce):
- Colleagues know decisions only from the sprint they are made (`knows` entries with `from_sprint` / `until_sprint`).
- A recurring trap for the repeated-mistake metric: `tracker.py list --owner` wants a user handle (`tracker.py people`), not a display name (mistake `M4`).
- Stricter fact patterns in `ground_truth.json`, so capture and retrieval misses are not inflated by loose matches.

## Run log (`docs/`)
`docs/` is the committed history of every run, in Markdown (`docs/README.md`) and HTML (`docs/index.html`, styled like the Hivemind app). `python -I sim.py docs` regenerates it from `runs/*/` (manifest, `metrics.json`, probe grades), the hand-written notes in `docs/notes/` and the Living Memory repo's merges on main (`lm_repo` in `simkit/config.json`):
- `docs/runs/<run>`: one page per run with all its statistics, plus its log entry from `docs/notes/runs/<run>.md`.
- `docs/analysis/<version>`: one page per scenario version (runs compare only within a version): the arms side by side, probes by arm, paired probe differences with bootstrap intervals and a power estimate, and the quiz by fact.
- `docs/living-memory-changes`: each run with the Living Memory pull requests merged since the previous run, and the ones no run has measured yet.

To add a run: `sim.py analyze --run RUN`, write `docs/notes/runs/RUN.md`, run `sim.py docs`, commit `docs/`. Generated pages replace home-folder paths with `~`. Generated pages are overwritten on every build; the notes are never touched.

## Testing another Living Memory build (`--lm-src`, `--work-model`)
`init` and `pipeline` take `--lm-src PATH`, a Living Memory source checkout (for example a git worktree of main or of a feature branch). The run then uses that checkout everywhere:
- the harness CLI (`stores.lm`, bootstrap, readout) and the manifest's version stamps (`SIMKIT_LM_CLI` / `SIMKIT_LM_REPO` are set for the process from `options.lm_src`, so resumed runs keep it);
- a private Claude config folder `runs/<run>/claude-home/` built by `simkit/lmsource.py`: `settings.json` with the hooks that checkout's `integrations/setup.py` generates (they run its `hooks/claude_hooks.py`), `CLAUDE.md` holding exactly its `core.instructions.instruction_block('claude')`, a copy of the real `~/.claude/.credentials.json`, and a minimal `.claude.json`. Every session gets `CLAUDE_CONFIG_DIR` and `CLAUDE_HOME` pointing there, so SessionStart sees the block and takes the short path, and the real `~/.claude` is only read (for the login), never written. The agents see only the block, not the user's personal `CLAUDE.md`.
- the `CMD` the hooks give agents is `python <checkout>/living_memory.py ...` (the `alm` launcher on PATH belongs to the installed app, so it is not used).
`--work-model M` runs every agent except the grader on model M and drops the tier's `--effort` (not every model takes it). Both options go in `manifest.json` `options`. `smoke --lm-src PATH` also checks `short_session_start` and `hooks_from_lm_src`.

Compare two runs: `sim.py analyze` writes `metrics.json` `block_ab` (computed offline from transcripts and stores): captures per work session, sessions with a capture, capture coverage, results carrying `quality_warnings` (and their texts), failed and malformed `alm` calls, hook denies, `alm help` calls and topics, brief notes (title, size, text) and the memory-quiz scores. `sim.py ab RUN_A RUN_B` prints them side by side with the brief contents; `compare-arms` lists the same scalars. Captures come from the stores' command logs, matched to sessions by session hash, because an agent that pipes `alm` through `| tail` never sees its result. Warnings, failed calls and `help` calls come from the transcripts, as what the agent saw: each `{"ok": ...}` JSON result in a tool's output is one call (a shell command can run several, and its exit code can hide a failed one), a successful write is named by its `status`, and a call with no JSON result of its own counts only when its output shows a crash.

## Tests
`py -3.10 -m unittest discover -s tests` runs offline harness tests (no agents, no model).

## Isolation guarantees
- Each child gets `LIVING_MEMORY_ROOT=<its store>` and debug or content logging, and the store is marked `sandbox.json`. Inherited `CLAUDE*` and `LIVING_MEMORY*` variables are stripped.
- `verify-isolation` searches the real store's logs and notes for every session hash of the run (`sha256(session_id)[:12]`, the same digest LM uses). It also checks that each store's logs contain only its own agent's sessions.
- Claude Code transcripts for children also land in `~/.claude/projects/<mangled clone path>/`. Their auto-memory folders are counted in `metrics.json` (`claude_automemory_files`).

## Writing a new scenario
Copy `scenarios/bank-cobol-springboot`, then change the roster, waves, seed, CI command, events, ground truth and quiz. Keep every scripted fact traceable: each memo has an `event` id that matches a `ground_truth.facts` key, and each quiz question names its fact.

## Known limits
- Without `--clock` all sessions run on the same real day, so LM's time-based features (review_by dates, staleness, auto-resolve) are not exercised. With it, they are exercised on a simulated calendar, but notes' ages come from the offset, not from real waiting (see above).
- The bulk Living Memory writes (delete, merge, retag, migrate, restore-backup, import, ingest) are not auto-allowed, so a headless agent can't run them. Watch for agents trying them.
- Fact detection in stores is regex-based. The quiz grades and a qualitative review are the authoritative signals.
- Runs without `--lm-src` still use the user's real `~/.claude` (hooks and `CLAUDE.md`) and the installed app; see below for testing another Living Memory build.
