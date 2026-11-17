"""Run lifecycle: init, sprints (waves, merges, CI), handovers, quiz, grading, smoke test, isolation check."""
import hashlib
import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import clock, gitops, lmsource, sessions, stores
from .common import (HOME, RUNS, SCENARIOS, Run, append_jsonl, clean_env, config, log, now, read_json, read_jsonl, run_cmd,
                     tree_hash, use_lm_src, write_json)


class SpendLimit(Exception):
    pass


# ---------------- init ----------------
def lm_version(cfg):
    app = Path(cfg['lm_cli']).parent
    parts = [p for p in (app / 'living_memory.py', app / 'core', app / 'hooks') if p.exists()]
    version = None
    for name in ('VERSION', 'version.txt', '.version.json', 'install.json'):
        if (app / name).exists():
            version = (app / name).read_text(encoding='utf-8', errors='replace')[:200].strip()
    return {'app': str(app), 'tree_sha256': tree_hash(parts)[:16], 'version': version,
            'repo_commit': lm_repo_commit(cfg), 'cli_version': lm_cli_version(cfg)}


def lm_repo_commit(cfg):
    """HEAD of the Living Memory source repository (config lm_repo); None when it cannot be read."""
    try:
        r = run_cmd(['git', '-C', str(cfg['lm_repo']), 'rev-parse', 'HEAD'], env=clean_env(), timeout=30)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    except (KeyError, OSError, subprocess.SubprocessError):
        return None


def lm_cli_version(cfg):
    """Parsed `version --json` of the CLI the harness runs (the same python and script as stores.lm); None on any failure."""
    try:
        r = run_cmd([cfg['python'], cfg['lm_cli'], 'version', '--json'], env=clean_env(), timeout=60)
        return json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else None
    except (KeyError, OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def init(scenario, label=None, prime=True, memory='on', semantic=False, review_user=False, use_clock=False, lm_src=None,
         work_model=None):
    """memory='off' runs every agent with hooks disabled (the control arm); semantic=True installs the embedding model
    into each store from the machine's model folder (config semantic_model_dir), offline and hash-verified.
    review_user=True lets the end-of-sprint review archive the notes its worklist proposes to archive.
    use_clock=True gives the run a simulated calendar (simkit/clock.py) that starts at the run's creation time.
    lm_src=PATH takes Living Memory from that checkout (CLI, hooks and instruction block, see simkit/lmsource.py) and
    gives the agents a private Claude config folder. work_model=NAME runs every work agent on that model."""
    src = SCENARIOS / scenario
    if not (src / 'scenario.json').exists():
        raise SystemExit(f'No scenario {scenario}')
    if memory not in ('on', 'off', 'builtin'):
        raise SystemExit("memory must be 'on', 'off' or 'builtin'")
    if lm_src:
        use_lm_src(lm_src)   # before config(): the manifest's version stamps and every store bootstrap use this checkout
        lm_src = str(Path(lm_src).resolve())
    cfg = config()
    if semantic and not Path(cfg.get('semantic_model_dir') or '').is_dir():
        raise SystemExit(f"semantic: no model folder at {cfg.get('semantic_model_dir')!r} (set semantic_model_dir in simkit/config.json)")
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    path = RUNS / (f'{scenario}-{stamp}' + (f'-{label}' if label else ''))
    path.mkdir(parents=True)
    shutil.copytree(src, path / 'scenario')
    claude_v = run_cmd([cfg['claude'], '--version']).stdout.strip()
    created = now()
    write_json(path / 'manifest.json', {
        'scenario': scenario, 'label': label, 'created': created, 'scenario_sha256': tree_hash([src])[:16],
        'living_memory': lm_version(cfg), 'claude_code': claude_v, 'harness_sha256': tree_hash([HOME / 'simkit'])[:16],
        'real_store': cfg.get('real_store'), 'options': {'memory': memory, 'semantic': bool(semantic), 'review_user': bool(review_user), 'clock': bool(use_clock),
                    **({'lm_src': lm_src} if lm_src else {}), **({'work_model': work_model} if work_model else {})},
        'clock': clock.settings(use_clock, created, cfg), 'finished': None})
    run = Run(path)
    log(run, f'init {path.name}')
    if lm_src:
        lmsource.prepare(path, lm_src)
        log(run, f'living memory from {lm_src}, claude config in {lmsource.home_of(run)}')
    if run.workspace_enabled:
        setup_workspace(run)
    gitops.init_repo(run)
    for agent in run.active(1):
        ensure_agent(run, agent)
    if prime:
        p = gitops.prime(run)
        log(run, f'prime toolchain: {"ok" if p and p["ok"] else p}')
        if p and not p['ok']:
            raise SystemExit('Toolchain priming failed: ' + '\n'.join(p['tail']))
        row = gitops.run_ci(run, 'seed')
        log(run, f'CI on seed: {"green" if row and row["ok"] else "RED"}')
    run.mark('init')
    return run


def ensure_agent(run, agent):
    repo = gitops.clone_for(run, agent)
    store = run.stores / agent['id']
    if not (store / 'bindings.json').exists():
        stores.bootstrap(store, run.scenario['domain'], [repo], run.scenario.get('taxonomy_extra', []))
        if run.options.get('semantic'):
            stores.lm(store, ['semantic', 'install', '--from', config()['semantic_model_dir']])
    return repo, store


# ---------------- prompts ----------------
def _team_header(run, agent, sprint):
    sc, active = run.scenario, run.active(sprint)
    roster = '\n'.join(f"- {a['name']} ({a['id']}): {a['title']}" for a in active)
    text = (run.scenario_dir / 'briefings' / '_team.md').read_text(encoding='utf-8')
    return text.format(name=agent['name'], title=agent['title'], team_size=len(active), roster=roster)


def _changes(run, sprint):
    out = []
    for a in run.scenario['roster']:
        if a.get('leaves_after') == sprint - 1:
            out.append(f"{a['name']} ({a['id']}) has left the project.")
        if a.get('joins') == sprint and sprint > 1:
            out.append(f"{a['name']} ({a['id']}) joins the team today as {a['title']}.")
    return out


def _ci_notice(run):
    rows = read_jsonl(run.dir / 'ci.jsonl')
    if not rows:
        return 'CI has not run yet.'
    last = rows[-1]
    if last.get('ok'):
        return f"CI on main is green (last run after {last['label']})."
    tail = '\n'.join(last.get('tail') or [last.get('reason', '')])[-2500:]
    return f"CI on main is RED (last run after {last['label']}). Output tail:\n```\n{tail}\n```"


# ---------------- v2: short engineer-voice prompts ----------------
def render(text, run):
    """Run-specific placeholders in seed and workspace text: {{WORKSPACE}} is this run's company workspace."""
    return text.replace('{{WORKSPACE}}', run.workspace.as_posix())


def setup_workspace(run):
    """The company's tools outside the repo (tracker, wiki, chat, hooks), copied from the scenario and rendered."""
    src = run.scenario_dir / run.scenario['workspace']
    shutil.copytree(src, run.workspace, dirs_exist_ok=True)
    for p in run.workspace.rglob('*'):
        if p.is_file() and p.suffix in ('.md', '.html', '.py', '.json', '.txt', '') and p.stat().st_size < 2_000_000:
            try:
                t = p.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue
            if '{{WORKSPACE}}' in t:
                p.write_text(render(t, run), encoding='utf-8', newline='\n')
    for d in ('chat', 'tracker', 'wiki'):
        (run.workspace / d).mkdir(parents=True, exist_ok=True)


def set_clock(run, sprint, day):
    row = {'sprint': sprint, 'day': day, 'label': day_label(run, sprint, day)}
    when = clock.day_time(run, sprint, day)   # computed from the run, whether or not there is a workspace
    if when:
        row['time'] = when.isoformat(timespec='seconds')
    write_json(run.workspace / '.clock.json', row)


def day_label(run, sprint, day):
    return f's{sprint}' if run.days == 1 else f's{sprint}d{day}'


def identity(run, agent):
    """What a personal ~/.claude/CLAUDE.md would tell the assistant about its engineer (appended to the system prompt)."""
    owns = f" {agent['name'].split()[0]} owns {agent['owns']}." if agent.get('owns') else ''
    return (f"You are pairing with {agent['name']}, {agent['title']} at Harbor Point Savings & Trust, on Project LIGHTHOUSE.{owns} "
            f"Their messages to you are their own words; act on them as a capable colleague would.")


def absent(run, sprint, day):
    """{agent: vacation} for engineers out on this day."""
    return {v['agent']: v for v in run.events.get('vacations', []) if v['sprint'] == sprint and day in v['days']}


def first_session(run, agent):
    return not any(r.get('agent') == agent['id'] and re.match(r'^s\d+(d\d+)?/', k) for k, r in run.state()['sessions'].items())


def _ci_bot(run, agent, wave_members):
    rows = read_jsonl(run.dir / 'ci.jsonl')
    if not rows or rows[-1].get('ok'):
        return None
    last = rows[-1]
    culprits = {v.get('author') for v in last.get('lint') or []}
    if not (agent['id'] in culprits or agent.get('ci_watch') or agent['id'] in wave_members):
        return None
    tail = '\n'.join((last.get('tail') or [last.get('reason', '')])[-14:])[-1800:]
    return f"#ci-bot: main is red since {last['label']} ({last.get('main', '')}).\n```\n{tail}\n```"


def short_prompt(run, agent, sprint, day, branch, cover=None):
    ev = run.events
    plan = ev.get('sprints', {}).get(str(sprint), {}).get(agent['id'], {})
    probe = next((p for p in run.probes if p['sprint'] == sprint and p['day'] == day and p['agent'] == agent['id']), None)
    if probe:
        task = probe['task']
    elif day == 1 or run.days == 1:
        task = plan.get('task') or ev.get('default_task', 'What should I pick up next? Check the tracker for my tickets.')
    else:
        task = (plan.get('days') or {}).get(str(day))
        if not task:
            templates = ev.get('day_templates', {}).get(str(day)) or ev.get('day_templates', {}).get('*') or ['Carry on with {focus}.']
            task = templates[(sprint + len(agent['id'])) % len(templates)].format(focus=plan.get('focus', 'your tickets'))
    parts = []
    if first_session(run, agent):
        key = 'join_note' if agent.get('joins', 1) > 1 else 'onboarding'
        parts.append(render(ev.get(key, ''), run).format(name=agent['name'].split()[0], title=agent['title'],
                                                         owns=agent.get('owns', 'your area')))
    parts.append(task)
    for c in cover or []:
        parts.append(c['note'])
    for s in plan.get('slack', []):
        if s.get('day', 1) == day:
            parts.append(f"FYI, from Slack ({s['channel']}), {s['from']}:\n> " + s['text'].replace('\n', '\n> '))
    for s in ev.get('broadcast', []):
        if s['sprint'] == sprint and s.get('day', 1) == day and (not s.get('to') or agent['id'] in s['to']):
            parts.append(f"FYI, from Slack ({s['channel']}), {s['from']}:\n> " + s['text'].replace('\n', '\n> '))
    ci = _ci_bot(run, agent, set(run.state().get('last_wave') or ()))
    if ci:
        parts.append(ci)
    return '\n\n'.join(p.strip() for p in parts if p and p.strip()) + '\n'


def work_prompt(run, agent, sprint, branch, day=1, cover=None):
    if run.events.get('style') == 'short':
        return short_prompt(run, agent, sprint, day, branch, cover)
    ev = run.events
    plan = (ev.get('sprints', {}).get(str(sprint), {}))
    item = plan.get(agent['id'], {})
    role = (run.scenario_dir / agent['briefing']).read_text(encoding='utf-8').strip()
    parts = [_team_header(run, agent, sprint).strip(), '## Your role', role, '## Today',
             f"{plan.get('theme', '')} It is sprint {sprint} of {run.scenario['sprints']}. You are on branch `{branch}`. {_ci_notice(run)}"]
    changes = _changes(run, sprint)
    if changes:
        parts.append('Team changes: ' + ' '.join(changes))
    parts += ['## Your assignment', item.get('task') or ev.get('default_task', 'Continue your work.')]
    memo = item.get('memo')
    if memo:
        parts += ['## Input you received today', f"From: {memo['from']}", '> ' + memo['text']]
    parts += ['## Before you finish',
              f"- Commit your work on `{branch}` (git add / git commit). Do not push.",
              f"- Write your standup note at `team/standup/s{sprint}/{agent['id']}.md` (Done / Next / Blockers) and update the tickets you touched."]
    return '\n\n'.join(parts) + '\n'


def resolve_prompt(run, agent, sprint, files):
    if run.events.get('style') == 'short':
        return (f"The release bot couldn't merge my branch into main: conflicts in {', '.join(files) or 'some files'}. "
                "I've started merging origin/main into the branch here. Can you resolve the conflicts so both my work and the "
                "team's work survive, make sure it still builds, and commit the merge? Don't push.\n")
    return '\n\n'.join([
        _team_header(run, agent, sprint).strip(), '## Merge conflict',
        f"Release engineering could not merge your branch into main: it conflicts in {', '.join(files) or 'some files'}. "
        "Your clone is now in the middle of merging origin/main into your branch. Resolve every conflict so that both "
        "your work and your colleagues' work survive, make sure the build still passes, and commit the merge. Do not push."]) + '\n'


# ---------------- sprints ----------------
def _session(run, key, agent, prompt, cwd, **kw):
    state = run.state()['sessions'].get(key)
    if state and state.get('ended'):
        return state
    limit = run.scenario.get('spend_limit_usd')
    if limit and run.spent() >= limit:
        raise SpendLimit(f'spend {run.spent()} >= limit {limit}')
    log(run, f'session {key} start ({agent["tier"]})')
    tier = run.tier(agent)
    row = sessions.launch(run, key, agent, prompt, cwd, run.stores / agent['id'], tier,
                          allow=kw.pop('allow', run.scenario['tools']['allow']),
                          deny=kw.pop('deny', run.scenario['tools'].get('deny', []) + sessions.deny_rules(run, agent['id'])),
                          timeout_min=run.scenario.get('session_timeout_min', 30), **kw)
    log(run, f"session {key} end: {row['subtype']} ${row['cost_usd']} {row['seconds']}s turns={row['turns']} lm_calls={row['lm_calls']}")
    return row


def handovers(run, sprint):
    for h in run.events.get('handovers', []):
        step = f"handover/{h['from']}->{h['to']}"
        if h.get('before_sprint') != sprint or run.done(step):
            continue
        agents = run.agents()
        ensure_agent(run, agents[h['to']])
        result = {'skipped': 'import_bundle false'}
        if run.options.get('memory') != 'on':
            result = {'skipped': f"memory {run.options.get('memory')} (no Living Memory in this arm)"}
        elif h.get('import_bundle'):
            result = stores.handover(run.stores / h['from'], run.stores / h['to'], run.scenario['domain'],
                                     run.dir / 'handover' / f"{h['from']}.zip")
        append_jsonl(run.dir / 'handovers.jsonl', {'ts': now(), **h, 'result': result})
        log(run, f'{step}: {json.dumps(result)[:300]}')
        run.mark(step)


def sprint(run, n):
    if run.done(f's{n}'):
        log(run, f'sprint {n} already done')
        return
    clock.enter(run, clock.day_time(run, n, 1))
    handovers(run, n)
    for d in range(1, run.days + 1):
        day(run, n, d)
    review(run, n)
    run.mark(f's{n}')


def fetch_review(store, domain):
    """The review worklist of one store, read-only: {counts, total, items}. The CLI returns the rows as `notes` and
    their number as `due`."""
    listed = stores.lm(store, ['--domain', domain, 'review', '--limit', '100'])
    return {'counts': listed.get('counts') or {}, 'total': listed.get('due'), 'items': listed.get('notes') or []}


def stats_window(run):
    """Days of the per-sprint `stats` snapshot. The review runs at start + n*D - 1 days, so D - 1 days back starts exactly at
    the sprint's first day and does not overlap the previous snapshot; the CLI keeps 30 days of diary at most."""
    return max(1, min(30, int(run.clock['days_per_sprint']) - 1))


def sprint_stats(run, n, aid, store, domain):
    """One read-only `stats` snapshot of a store at the end of sprint n, appended to stats.jsonl (a failure is recorded). Only
    runs with a simulated calendar take these: the CLI's stats window (30 days) is shorter than such a run."""
    days = stats_window(run)
    row = {'ts': now(), 'sprint': n, 'agent': aid, 'days': days}
    try:
        row['stats'] = stores.lm(store, ['--domain', domain, 'stats', '--days', str(days), '--json'])
    except Exception as e:  # noqa: BLE001 a failed snapshot must not stop the sprint
        row['error'] = str(e)[-300:]
    append_jsonl(run.dir / 'stats.jsonl', row)


def review(run, n):
    """End of sprint: fetch each agent store's review worklist and log it to reviews.jsonl. With the review-user option a
    simulated user also archives the notes the worklist proposes to archive; every other row is only logged."""
    step = f's{n}/review'
    if run.options.get('memory') != 'on' or run.done(step):
        return
    domain = run.scenario['domain']
    clock.enter(run, clock.review_time(run, n))
    for aid in run.agents():
        store = run.stores / aid
        if not store.is_dir():
            continue
        entry = {'ts': now(), 'sprint': n, 'agent': aid}
        try:
            entry.update(fetch_review(store, domain))
            items = entry['items']
            if clock.enabled(run):
                sprint_stats(run, n, aid, store, domain)
            if run.options.get('review_user'):
                entry['applied'], entry['errors'] = [], []
                for row in items:
                    if row.get('action') != 'archive-plan':
                        continue
                    try:
                        plan = stores.lm(store, ['--domain', domain, 'plan', 'archive', row['ref']])
                        stores._apply(store, plan, domain)
                        entry['applied'].append({'ref': row['ref'], 'plan_id': plan.get('plan_id')})
                    except Exception as e:  # noqa: BLE001 one bad plan must not stop the others
                        entry['errors'].append({'ref': row.get('ref'), 'error': str(e)[-300:]})
        except Exception as e:  # noqa: BLE001 a failed review must not stop the sprint
            entry['error'] = str(e)[-300:]
        append_jsonl(run.dir / 'reviews.jsonl', entry)
        log(run, f"{step} {aid}: {entry.get('error') or json.dumps(entry.get('counts'))}"
                 + (f" applied {len(entry['applied'])}" if entry.get('applied') else ''))
    run.mark(step)


def day(run, n, d):
    """One working day: waves in dependency order, each wave's sessions in parallel, then merges and CI.
    With one day per sprint the keys and labels are the v1 ones (s1/po, s1/w0)."""
    tag = day_label(run, n, d)
    if run.days > 1 and run.done(tag):
        return
    clock.enter(run, clock.day_time(run, n, d))
    if run.workspace_enabled:
        set_clock(run, n, d)
    out = absent(run, n, d)
    covers = {}
    for aid, v in out.items():
        covers.setdefault(v['cover'], []).append(v)
    active_ids = {a['id'] for a in run.active(n)} - set(out)
    agents = run.agents()
    for wi, wave in enumerate(run.scenario['waves']):
        step = f'{tag}/w{wi}'
        members = [agents[i] for i in wave if i in active_ids]
        if run.done(step) or not members:
            continue
        branches = {}
        for a in members:
            ensure_agent(run, a)
            bstep = f'{tag}/{a["id"]}/branch'
            label = n if run.days == 1 else tag
            info = gitops.start_branch(run, a, label) if not run.done(bstep) else {'branch': f"{a['id']}/{tag}"}
            if not run.done(bstep):
                append_jsonl(run.dir / 'branches.jsonl', {'ts': now(), 'sprint': n, 'day': d, 'agent': a['id'], **info})
                run.mark(bstep)
            branches[a['id']] = info['branch']
        system = identity(run, members[0]) if run.events.get('style') == 'short' else None
        with ThreadPoolExecutor(max_workers=run.scenario.get('parallel', 4)) as pool:
            futures = [pool.submit(_session, run, f'{tag}/{a["id"]}', a,
                                   work_prompt(run, a, n, branches[a['id']], d, covers.get(a['id'])), run.ws / a['id'],
                                   **({'system_append': identity(run, a)} if system else {})) for a in members]
            for f in futures:
                f.result()
        for a in members:
            ok, detail = gitops.merge_agent(run, a, n)
            if not ok:
                append_jsonl(run.dir / 'merges.jsonl', {'ts': now(), 'sprint': n, 'day': d, 'agent': a['id'], 'ok': False, 'attempt': 1, **detail})
                main_merged = gitops.prepare_conflict(run, a)
                if main_merged:
                    _session(run, f'{tag}/{a["id"]}.resolve', a, resolve_prompt(run, a, n, detail.get('conflicts', [])), run.ws / a['id'],
                             **({'system_append': identity(run, a)} if system else {}))
                ok, detail = gitops.merge_agent(run, a, n)
                detail['attempt'] = 2
                if main_merged:
                    detail['main_merged'] = main_merged   # probes diff from here, not from teammates' merged-in work
            append_jsonl(run.dir / 'merges.jsonl', {'ts': now(), 'sprint': n, 'day': d, 'label': tag, 'agent': a['id'], 'ok': ok, **detail})
            log(run, f'merge {a["id"]} {tag}: {"ok" if ok else "FAILED"} {detail}')
        row = gitops.run_ci(run, step)
        # Persisted so a resumed run builds the same #ci-bot prompts as an uninterrupted one.
        run.update_state(lambda s: s.__setitem__('last_wave', sorted(a['id'] for a in members)))
        log(run, f'CI after {step}: {"green" if row and row["ok"] else "RED"} ({row and row["seconds"]}s)'
                 + (f" lint={len(row['lint'])}" if row and row.get('lint') else ''))
        run.mark(step)
    if run.days > 1:
        run.mark(tag)


def run_all(run, through=None):
    for n in range(1, (through or run.scenario['sprints']) + 1):
        sprint(run, n)


# ---------------- quiz ----------------
def _last_json(text):
    dec, found, i = json.JSONDecoder(), None, 0
    while True:
        i = text.find('{', i)
        if i < 0:
            return found
        try:
            v, end = dec.raw_decode(text, i)
            if isinstance(v, dict):
                found = v
            i = end
        except ValueError:
            i += 1


QUIZ_DENY = ['Read', 'Grep', 'Glob', 'Edit', 'Write', 'NotebookEdit', 'WebFetch', 'WebSearch', 'Agent', 'Task']
# The quiz measures memory, not the repository: shell reads are denied too (Living Memory commands stay allowed by its hook).
QUIZ_SHELL_DENY = [f'{shell}({c} *)' for shell in ('Bash', 'PowerShell') for c in
                   ('cat', 'ls', 'git', 'grep', 'find', 'type', 'dir', 'tree', 'rg',
                    'Get-Content', 'Get-ChildItem', 'Select-String')]
# Not python (the LM CMD is a python command) and not head/tail/more/less: agents pipe search output through them, and a
# denied pipe stage denies the whole loop. analyze.quiz_repo_reads flags any memory-quiz command that names a repo path.


def review_at_quiz(run):
    """The review worklist of every agent store as it stands before the first quiz, written once to review-at-quiz.json
    (read-only; a failing store records its error). The end-of-run readout folds it in as `review_at_quiz`."""
    path = run.dir / 'review-at-quiz.json'
    if path.exists() or run.options.get('memory') != 'on':
        return
    out = {}
    for aid in run.agents():
        if (run.stores / aid).is_dir():
            try:
                out[aid] = fetch_review(run.stores / aid, run.scenario['domain'])
            except Exception as e:  # noqa: BLE001 a failed read must not stop the quiz
                out[aid] = {'error': str(e)[-300:]}
    write_json(path, {'ts': now(), 'stores': out})


QUIZ_MODES = ('memory', 'repo')
REPO_INTRO = ('Today is the LIGHTHOUSE knowledge review before go-live. Answer every question in one or two sentences, '
              'using anything you can find (the repository, the ticket board and whatever you already know). '
              'If you cannot find an answer, answer exactly "unknown"; do not guess.')


def full_final(run, key, row):
    """The session's whole reply, from its transcript (see replies.final_reply); the state row keeps only a 1,500-char tail."""
    from .replies import final_reply
    return final_reply(run.transcripts / f'{key}.jsonl', (row or {}).get('final') or '')


def quiz_answers(run, key):
    """The {"answers": [...]} object the agent wrote, even when memory housekeeping came after it."""
    from .replies import json_reply
    found = json_reply(run.transcripts / f'{key}.jsonl', 'answers')
    return {'answers': found['answers']} if found and isinstance(found.get('answers'), list) else {}


def quiz_modes(memory):
    """Quizzes a run takes, in order. Memory-only goes first: during the repo quiz agents update their notes, which
    would otherwise leak into the memory-only score."""
    return ['repo'] if memory in ('off', 'builtin') else ['memory', 'repo']


def quiz_room(run, agent_id):
    """An empty folder outside any git work tree: inside the harness repo, Living Memory would treat the harness as
    the agent's repo (its map, its brief)."""
    import tempfile
    room = Path(tempfile.gettempdir()) / 'alm-simulation-benchmark' / 'quizroom' / run.dir.name / agent_id
    room.mkdir(parents=True, exist_ok=True)
    return room


def quiz_dir(run, mode):
    """memory mode keeps the original paths (quiz/answers, quiz/grades) so older runs stay readable."""
    return run.dir / 'quiz' if mode == 'memory' else run.dir / 'quiz' / mode


def quiz(run, mode='memory'):
    """memory: only Living Memory is available (repo reads denied, empty room). repo: the agent's own clone and tools."""
    if mode not in QUIZ_MODES:
        raise SystemExit(f'quiz mode must be one of {QUIZ_MODES}')
    q = run.quiz
    intro = q['intro'] if mode == 'memory' else q.get('intro_repo', REPO_INTRO)
    body = intro + '\n\n' + '\n'.join(f"{x['id']}. {x['text']}" for x in q['questions'])
    body += ('\n\nWhen you are done, reply with only a JSON object of the form '
             '{"answers": [{"id": "q1", "answer": "..."}, ...]} covering every question.')
    def one(agent):
        short = run.events.get('style') == 'short'
        # v2: the engineer is speaking (identity in the system prompt, like a personal CLAUDE.md); v1: a role header.
        who = {'system_append': identity(run, agent)} if short else {}
        header = '' if short else f"You are {agent['name']}, {agent['title']} on Project LIGHTHOUSE at Harbor Point Savings & Trust.\n\n"
        key = f'quiz/{agent["id"]}' if mode == 'memory' else f'quiz-{mode}/{agent["id"]}'
        if mode == 'memory':
            room = quiz_room(run, agent['id'])
            stores.bind(run.stores / agent['id'], run.scenario['domain'], room)
            row = _session(run, key, agent, header + body, room, allow=[],
                           deny=QUIZ_DENY + QUIZ_SHELL_DENY + sessions.deny_rules(run, agent['id']), **who)
        else:
            if not (run.state()['sessions'].get(key) or {}).get('ended'):
                gitops.autocommit(run.ws / agent['id'], agent['id'])
                gitops.git(run.ws / agent['id'], 'fetch', '-q', 'origin')
                gitops.git(run.ws / agent['id'], 'checkout', '-q', '-B', f"{agent['id']}/quiz", 'origin/main')
            row = _session(run, key, agent, header + body, run.ws / agent['id'], **who)
        write_json(quiz_dir(run, mode) / 'answers' / f'{agent["id"]}.json', {'agent': agent['id'], **quiz_answers(run, key)})

    from .analyze import snapshot_stores
    clock.enter(run, clock.final_time(run))
    review_at_quiz(run)
    snapshot_stores(run)   # what memory held when the work ended, before any quiz can add to it
    takers = [a for a in run.scenario['roster'] if (run.stores / a['id']).exists()]
    with ThreadPoolExecutor(max_workers=run.scenario.get('parallel', 4)) as pool:
        list(pool.map(one, takers))   # list() re-raises a session's exception (e.g. SpendLimit)
    run.mark('quiz' if mode == 'memory' else f'quiz-{mode}')


KB_AGENT = {'id': '_kb', 'tier': 'sonnet-low', 'name': 'Sam Rivera', 'title': 'Engineer (new joiner)'}


def kb_quiz(run, digests_budget=None):
    """Arm D (knowledge-base acceptance): a brand-new agent with no history gets a fresh store whose knowledge base
    indexes the finished repo, the wiki and the tracker, then takes the memory-only quiz with only Living Memory
    (notes, `ask`, `search --sources`) to answer from. Graded like the other quizzes, as mode 'kb'."""
    from .common import config
    clock.enter(run, clock.final_time(run))
    store, kb = run.stores / KB_AGENT['id'], run.dir / 'kb'
    repo = kb / 'repo'
    if not repo.exists():
        kb.mkdir(parents=True, exist_ok=True)
        gitops.git(run.dir, 'clone', '-q', *gitops.NO_EOL, str(run.origin), str(repo))   # main as the team left it
    domain = run.scenario['domain']
    if not (store / 'tag_taxonomy.json').exists():
        stores.bootstrap(store, domain, [repo], run.scenario.get('taxonomy_extra', []))
        if run.workspace_enabled:
            for name, kind, folder in (('wiki', 'html-export', run.workspace / 'wiki'), ('tracker', 'folder', run.workspace / 'tracker')):
                if folder.is_dir():
                    payload = kb / f'source-{name}.json'
                    write_json(payload, {'name': name, 'domain': domain, 'kind': kind, 'path': str(folder)})
                    stores._apply(store, stores.lm(store, ['--domain', domain, 'source-plan', 'add', '--payload-file', str(payload)]), domain)
    if not run.done('kb-sync'):
        synced = stores.lm(store, ['--domain', domain, 'source-sync'], cwd=repo)
        write_json(kb / 'sync.json', synced)
        run.mark('kb-sync')
    if digests_budget and not run.done('kb-digests'):
        script = Path(config()['lm_cli']).parent / 'scripts' / 'ingest_run.py'
        if not script.exists():
            raise SystemExit(f'digests need {script}: deploy a Living Memory build with scripts/ingest_run.py')
        r = run_cmd([config()['python'], str(script), '--root', str(store), '--domain', domain, '--cwd', str(repo),
                     '--budget-usd', str(digests_budget)], cwd=repo, env=sessions.clean_env({'LIVING_MEMORY_ROOT': str(store),
                     'LIVING_MEMORY_HEADLESS': '1', **clock.lm_env()}), timeout=6 * 3600)   # digests are stamped at the phase time
        (kb / 'digests.out').write_text((r.stdout or '') + (r.stderr or ''), encoding='utf-8')
        run.mark('kb-digests')
    room = quiz_room(run, KB_AGENT['id'])
    stores.bind(store, domain, room)
    q = run.quiz
    body = q['intro'] + '\n\n' + '\n'.join(f"{x['id']}. {x['text']}" for x in q['questions'])
    body += ('\n\nWhen you are done, reply with only a JSON object of the form '
             '{"answers": [{"id": "q1", "answer": "..."}, ...]} covering every question.')
    who = f"You are {KB_AGENT['name']}, {KB_AGENT['title']} on Project LIGHTHOUSE at Harbor Point Savings & Trust, starting today."
    key = 'quiz-kb/_kb'
    deny = QUIZ_DENY + QUIZ_SHELL_DENY + sessions.deny_rules(run, KB_AGENT['id'])
    deny += [f'{t}({sessions.rule_path(kb)}/**)' for t in ('Read', 'Edit', 'Write')]   # the indexed copy is reachable only through memory
    # memory='on' whatever the run's arm: the fresh agent answers through Living Memory even on an A0 or A1 run.
    _session(run, key, KB_AGENT, body, room, allow=[], deny=deny, system_append=who, memory='on')
    write_json(quiz_dir(run, 'kb') / 'answers' / f"{KB_AGENT['id']}.json", {'agent': KB_AGENT['id'], **quiz_answers(run, key)})
    run.mark('quiz-kb')
    grade(run, 'kb')


def grade(run, mode='memory'):
    facts = run.truth['facts']
    grader_store = run.stores / '_grader'
    if not (grader_store / 'tag_taxonomy.json').exists():
        stores.bootstrap(grader_store, '_grader', [], [])
    room = run.dir / 'quiz' / 'grader'
    room.mkdir(parents=True, exist_ok=True)
    grader = {'id': '_grader', 'tier': 'grader', 'name': 'grader'}
    key_text = '\n'.join(f"{qq['id']} (fact {qq['fact']}): {qq['text']}\n   ground truth: {facts[qq['fact']]['answer']}"
                         + (f"\n   stale (outdated) answer: {facts[qq['fact']]['stale_answer']}" if facts[qq['fact']].get('stale_answer') else '')
                         for qq in run.quiz['questions'])
    for path in sorted((quiz_dir(run, mode) / 'answers').glob('*.json')):
        a = read_json(path)
        out = quiz_dir(run, mode) / 'grades' / path.name
        # Keyed by the answers graded, so corrected answers are graded afresh rather than served a cached grade.
        digest = hashlib.sha256(json.dumps(a.get('answers', []), sort_keys=True).encode()).hexdigest()[:8]
        old = read_json(out) if out.exists() else None
        if old is not None and old.get('answers_sha', digest) == digest:   # grade files from before the digest stay
            continue
        prompt = ('You are grading a knowledge quiz for a software project. For each question compare the answer with '
                  'the ground truth. Grades: "correct" (all key points right), "partial" (some key points, nothing wrong), '
                  '"stale" (gives the outdated answer where one is listed), "wrong" (contradicts the ground truth), '
                  '"unknown" (answered unknown or no answer). Do not use any tools.\n\n'
                  f'QUESTIONS AND GROUND TRUTH\n{key_text}\n\nANSWERS\n{json.dumps(a.get("answers", []), indent=1)}\n\n'
                  'Reply with only a JSON object: {"grades": [{"id": "q1", "grade": "...", "note": "short reason"}, ...]}')
        key = (f'grade/{path.stem}' if mode == 'memory' else f'grade-{mode}/{path.stem}') + f'@{digest}'
        row = _session(run, key, grader, prompt, room, allow=[], deny=QUIZ_DENY + ['Bash', 'PowerShell'],
                       settings={'disableAllHooks': True})
        write_json(out, {'agent': path.stem, 'answers_sha': digest,
                         **(_last_json(full_final(run, key, row)) or {'error': 'unparsed'})})
    run.mark('grade' if mode == 'memory' else f'grade-{mode}')


# ---------------- end-of-run store readout ----------------
READOUT_DAYS = 120
READOUT_COMMANDS = (('stats', ['stats', '--days', '{days}', '--json'], True), ('log', ['log', '--limit', '100000', '--json'], False),
                    ('recap', ['recap', '--days', '{days}', '--json'], True), ('maintenance_history', ['maintenance', 'history', '--limit', '1000', '--json'], False))


def _read_store(store, domain, args, windowed, days=READOUT_DAYS):
    """Run one read-only command; a `--days` window the installed CLI caps (stats: 30, recap: 90) is retried at the cap.
    Returns (value, days used, error)."""
    for _ in range(2):
        try:
            return stores.lm(store, ['--domain', domain] + [a.format(days=days) for a in args]), days if windowed else None, None
        except Exception as e:  # noqa: BLE001 an unknown command or a failing store is recorded, not fatal
            cap = re.search(r'(?:at most|to) (\d+)', str(e)) if windowed else None
            if not cap or int(cap.group(1)) >= days:
                return None, days if windowed else None, str(e)[-300:]
            days = int(cap.group(1))
    return None, days, 'window retry failed'


def readout(run):
    """Read-only Living Memory commands on every agent store after the work and quizzes, written to stores-readout.json:
    stats, log, recap and maintenance history, plus the review worklist taken before the first quiz. Recap's `markdown`
    copy is dropped. Resumable (step `readout`); a command that fails is recorded under `errors` for that store."""
    if run.options.get('memory') != 'on' or run.done('readout'):
        return
    clock.enter(run, clock.readout_time(run))   # after the quiz sessions, which ran at about final_time plus their real duration
    domain = run.scenario['domain']
    # Recap has to reach back over the whole simulated run (its window is 90 days at most); stats is a 30-day diary, so a
    # run with a clock takes per-sprint snapshots in review() and this end-of-run stats is the fallback.
    needed = (int(run.scenario['sprints']) + 1) * int(run.clock['days_per_sprint']) + 1 if clock.enabled(run) else READOUT_DAYS   # + the day readout_time adds
    recap_days = min(90, needed)
    at_quiz = (read_json(run.dir / 'review-at-quiz.json') or {}).get('stores') or {}
    out = {}
    for aid in run.agents():
        store = run.stores / aid
        if not store.is_dir():
            continue
        entry = {'errors': {}, 'days_used': {}}
        for name, args, windowed in READOUT_COMMANDS:
            value, days, error = _read_store(store, domain, args, windowed, recap_days if name == 'recap' else READOUT_DAYS)
            if isinstance(value, dict):
                value.pop('markdown', None)
            entry[name] = value
            if windowed:
                entry['days_used'][name] = days
            if error:
                entry['errors'][name] = error
        entry['review_at_quiz'] = at_quiz.get(aid)
        out[aid] = entry
        log(run, f"readout {aid}: " + ('errors in ' + ', '.join(entry['errors']) if entry['errors'] else 'ok'))
    write_json(run.dir / 'stores-readout.json', {'ts': now(), 'domain': domain, 'days_requested': READOUT_DAYS,
                                                'recap_days_needed': needed, 'recap_truncated': needed > 90, 'stores': out})
    run.mark('readout')


# ---------------- smoke & isolation ----------------
SMOKE_NOTE = 'Smoke clock check'


def _note_created(store, title):
    """The `created` timestamp of the note with this title in a store, or None."""
    for p in store.glob('domains/*/notes/*.md'):
        text = p.read_text(encoding='utf-8', errors='replace')
        if f'title: "{title}"' in text:
            m = re.search(r'^created: "([^"]+)"', text, re.M)
            return m[1] if m else None
    return None


def smoke(scenario, use_clock=False, lm_src=None, work_model=None):
    """Tiny end-to-end check of the harness on a throwaway run (no Maven priming). With use_clock the run has a simulated
    calendar, and the note the agent captures must carry the session's simulated time."""
    run = init(scenario, label='smoke', prime=False, use_clock=use_clock, lm_src=lm_src, work_model=work_model)
    agent = run.active(1)[0]
    secret = run.scenario_dir / 'ground_truth.json'
    other = next(a for a in run.active(1) if a['id'] != agent['id'])
    other_note = run.stores / other['id'] / 'bindings.json'
    prompt = ('This is a short tooling check of the sandbox, not project work. Do each step once and do not work around a refusal.\n'
              '1. Run exactly this one shell command: `cd modern && git status --short && cd ..`\n'
              f'2. Use the Read tool on {secret} and report whether it was allowed.\n'
              f'3. Run the shell command `cat "{secret.as_posix()}"` and report whether it was allowed.\n'
              f'4. Use the Read tool on {other_note} and report whether it was allowed.\n'
              '5. Using the Living Memory command (CMD) and session id from your session context, run one `search` for '
              f"'smoke check', then capture one note: type context, title '{SMOKE_NOTE}', summary 'Harness smoke check of the memory CLI.'\n"
              '6. Reply with one line per step: allowed or blocked.')
    key = 'smoke/' + agent['id']
    row = _session(run, key, agent, prompt, run.ws / agent['id'])
    sh = row.get('session_hash')
    store = run.stores / agent['id']
    store_logs = ''.join(p.read_text(encoding='utf-8', errors='replace') for p in (store / 'logs').glob('*.jsonl')) if (store / 'logs').exists() else ''
    transcript = (run.transcripts / f"smoke/{agent['id']}.jsonl").read_text(encoding='utf-8', errors='replace')
    checks = {
        'session_ok': row.get('subtype') == 'success',
        'effort_flag_accepted': row.get('exit') == 0,
        'hooks_wrote_sim_store': bool(sh) and sh in store_logs,
        'session_start_context_injected': 'Living Memory' in transcript,
        # Canary: a phrase that exists only in the hidden ground truth; it must never reach a tool result.
        'ground_truth_content_not_leaked': 'Heritage Savings, all opened before 2009' not in transcript,
        'other_store_not_leaked': '"search_scope"' not in transcript,
        'permission_mode': run.tier(agent).get('permission_mode', 'acceptEdits'),
    }
    if lm_src:
        # The checkout's block is in the agents' config folder, so SessionStart takes the short path and the hooks ran from it.
        checks['short_session_start'] = 'follow the Living Memory section of your instructions' in transcript
        hook = json.loads((lmsource.home_of(run) / 'settings.json').read_text(encoding='utf-8'))['hooks']['SessionStart'][0]['hooks'][0]
        checks['hooks_from_lm_src'] = Path(hook['args'][0]).resolve() == (Path(lm_src).resolve() / 'hooks' / 'claude_hooks.py')
    created = _note_created(store, SMOKE_NOTE)
    checks['lm_calls_counted'] = (row.get('lm_calls') or 0) > 0
    checks['note_captured'] = bool(created)
    expected = clock.session_time(run, key)
    if expected:
        # The offset is fixed at launch, so the note lands minutes after the simulated start, never days.
        lag = (datetime.fromisoformat(created) - expected).total_seconds() if created else None
        checks['clock_reached_session'] = lag is not None and 0 <= lag < 3600
    iso = isolation(run)
    checks['real_store_untouched'] = iso['ok']
    report = {'run': run.dir.name, 'checks': checks, 'session': {k: row.get(k) for k in ('subtype', 'cost_usd', 'seconds', 'turns', 'lm_calls', 'sim_time')},
              'note_created': created, 'isolation': iso, 'final': row.get('final')}
    write_json(run.dir / 'smoke.json', report)
    return report


def isolation(run):
    """No session of this run may appear in the real store; each agent's sessions only in its own store."""
    cfg = config()
    hashes = {r['session_hash']: r['agent'] for r in run.state()['sessions'].values() if r.get('session_hash')}
    real = Path(cfg.get('real_store') or '')
    hits = []
    if real.exists():
        for p in list((real / 'logs').glob('*.jsonl')) + list((real / 'domains').rglob('*.md')):
            try:
                text = p.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            hits += [{'file': str(p), 'session_hash': h, 'agent': a} for h, a in hashes.items() if h in text]
    # Within the run, compare who WROTE each log row (its session field). A hash inside logged note content is not a
    # leak: a handover import legitimately carries the leaver's notes, origin stamps included.
    cross = []
    for store in run.stores.glob('*'):
        if store.name.startswith('_') or not (store / 'logs').exists():
            continue
        writers = {r.get('session') for p in (store / 'logs').glob('*.jsonl') for r in read_jsonl(p)}
        cross += [{'store': store.name, 'session_hash': h, 'agent': a} for h, a in hashes.items()
                  if a != store.name and h in writers]
    return {'ok': not hits and not cross, 'sessions_checked': len(hashes), 'real_store_hits': hits[:20], 'cross_store_hits': cross[:20]}


def finish(run):
    m = read_json(run.dir / 'manifest.json')
    m['finished'] = now()
    write_json(run.dir / 'manifest.json', m)
