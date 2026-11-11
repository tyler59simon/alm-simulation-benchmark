# lm-team-sim

A repeatable harness that tests Agentic Living Memory (LM) in a simulated enterprise team. Each team member is a real headless Claude Code session (`claude -p`) with its **own private LM store**, so the full hook pipeline runs exactly as it does for a real user: session-start injection, prompt retrieval, guards, Stop reminders and capture receipts. The team works over several sprints on a shared git repo. Scripted events with known answers make memory measurable. At the end, a memory-only quiz and an analyzer score what each agent's memory actually kept.

Run folders are never deleted, so every run stays available for comparison (for example before and after an LM change).

## Layout
- `sim.py`: the CLI (see `python sim.py --help`).
- `simkit/`: the generic engine. Nothing in it is specific to a scenario.
  - `engine.py`: init, sprints (waves, merges, CI), handovers, quiz, grading, smoke test, isolation.
  - `sessions.py`: the `claude -p` launcher: per-agent `LIVING_MEMORY_ROOT`, budget, timeout, deny rules, stream-json transcript.
  - `stores.py`: store bootstrap (bind, then migration plan and apply, then taxonomy plan and apply, then sandbox marker) and export/import handover. It never calls `setup`, so the real `config.json` is never touched.
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
  - `manifest.json`: scenario hash, LM app tree hash, Claude Code version, harness hash.
  - `scenario/`: a frozen copy of the scenario the run used.
  - `origin.git`, `integration/` and `ws/<agent>/`: the repos.
  - `stores/<agent>/`: the memory stores. `stores/_grader` is unbound, and grading runs with hooks disabled.
  - `transcripts/<key>.jsonl`: each session's prompt, stream-json output and stderr.
  - `state.json` (resumable steps and sessions), `costs.jsonl`, `ci.jsonl`, `merges.jsonl`, `branches.jsonl`, `handovers.jsonl`.
  - `quiz/answers`, `quiz/grades`, `metrics.json`, `sim.log`.

## Running
```
python sim.py smoke bank-cobol-springboot          # ~$0.10, checks hooks, isolation, deny rules, effort flag
python sim.py init  bank-cobol-springboot          # new run, primes Maven, CI on the seed
python sim.py run   [--through N]                  # sprints; resumable, stops at the spend limit
python sim.py quiz && python sim.py grade && python sim.py analyze
python sim.py verify-isolation                     # no run session in the real store or in another agent's store
python sim.py compare RUN_A RUN_B
```
Use the Python 3.10 interpreter in `simkit/config.json`, with `-I`. Runs are long (hours), so start `run` in the background. Every step is resumable: re-running a command skips the sessions and steps that already finished.

## Isolation guarantees
- Each child gets `LIVING_MEMORY_ROOT=<its store>` and debug or content logging, and the store is marked `sandbox.json`. Inherited `CLAUDE*` and `LIVING_MEMORY*` variables are stripped.
- `verify-isolation` searches the real store's logs and notes for every session hash of the run (`sha256(session_id)[:12]`, the same digest LM uses). It also checks that each store's logs contain only its own agent's sessions.
- Claude Code transcripts for children also land in `~/.claude/projects/<mangled clone path>/`. Their auto-memory folders are counted in `metrics.json` (`claude_automemory_files`).

## Writing a new scenario
Copy `scenarios/bank-cobol-springboot`, then change the roster, waves, seed, CI command, events, ground truth and quiz. Keep every scripted fact traceable: each memo has an `event` id that matches a `ground_truth.facts` key, and each quiz question names its fact.

## Known limits
- All sessions run on the same real day, so LM's time-based features (review_by dates, staleness) are not exercised.
- Governed LM operations (plans and apply) can't be approved in headless mode. Watch for agents trying them.
- Fact detection in stores is regex-based. The quiz grades and a qualitative review are the authoritative signals.
- Possible future addition: a per-run `CLAUDE_CONFIG_DIR`, to test an LM development build instead of the installed app (the hooks currently come from the user-level `~/.claude/settings.json`).
