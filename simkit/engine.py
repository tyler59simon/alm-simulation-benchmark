"""Run lifecycle: init, sprints (waves, merges, CI), handovers, quiz, grading, smoke test, isolation check."""
import hashlib
import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import gitops, sessions, stores
from .common import (HOME, RUNS, SCENARIOS, Run, append_jsonl, config, log, now, read_json, read_jsonl, run_cmd,
                     tree_hash, write_json)


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
    return {'app': str(app), 'tree_sha256': tree_hash(parts)[:16], 'version': version}


def init(scenario, label=None, prime=True, memory='on', semantic=False):
    """memory='off' runs every agent with hooks disabled (the control arm); semantic=True installs the embedding model
    into each store from the machine's model folder (config semantic_model_dir), offline and hash-verified."""
    src = SCENARIOS / scenario
    if not (src / 'scenario.json').exists():
        raise SystemExit(f'No scenario {scenario}')
    if memory not in ('on', 'off', 'builtin'):
        raise SystemExit("memory must be 'on', 'off' or 'builtin'")
    cfg = config()
    if semantic and not Path(cfg.get('semantic_model_dir') or '').is_dir():
        raise SystemExit(f"semantic: no model folder at {cfg.get('semantic_model_dir')!r} (set semantic_model_dir in simkit/config.json)")
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    path = RUNS / (f'{scenario}-{stamp}' + (f'-{label}' if label else ''))
    path.mkdir(parents=True)
    shutil.copytree(src, path / 'scenario')
    claude_v = run_cmd([cfg['claude'], '--version']).stdout.strip()
    write_json(path / 'manifest.json', {
        'scenario': scenario, 'label': label, 'created': now(), 'scenario_sha256': tree_hash([src])[:16],
        'living_memory': lm_version(cfg), 'claude_code': claude_v, 'harness_sha256': tree_hash([HOME / 'simkit'])[:16],
        'real_store': cfg.get('real_store'), 'options': {'memory': memory, 'semantic': bool(semantic)}, 'finished': None})
    run = Run(path)
    log(run, f'init {path.name}')
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
    write_json(run.workspace / '.clock.json', {'sprint': sprint, 'day': day, 'label': day_label(run, sprint, day)})


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
    ci = _ci_bot(run, agent, getattr(run, '_last_wave', ()))
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
        if run.options.get('memory') == 'off':
            result = {'skipped': 'memory off (control arm)'}
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
    handovers(run, n)
    for d in range(1, run.days + 1):
        day(run, n, d)
    run.mark(f's{n}')


def day(run, n, d):
    """One working day: waves in dependency order, each wave's sessions in parallel, then merges and CI.
    With one day per sprint the keys and labels are the v1 ones (s1/po, s1/w0)."""
    tag = day_label(run, n, d)
    if run.days > 1 and run.done(tag):
        return
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
                if gitops.prepare_conflict(run, a):
                    _session(run, f'{tag}/{a["id"]}.resolve', a, resolve_prompt(run, a, n, detail.get('conflicts', [])), run.ws / a['id'],
                             **({'system_append': identity(run, a)} if system else {}))
                ok, detail = gitops.merge_agent(run, a, n)
                detail['attempt'] = 2
            append_jsonl(run.dir / 'merges.jsonl', {'ts': now(), 'sprint': n, 'day': d, 'label': tag, 'agent': a['id'], 'ok': ok, **detail})
            log(run, f'merge {a["id"]} {tag}: {"ok" if ok else "FAILED"} {detail}')
        row = gitops.run_ci(run, step)
        run._last_wave = {a['id'] for a in members}
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
                   ('cat', 'ls', 'git', 'grep', 'find', 'head', 'tail', 'type', 'more', 'less', 'dir', 'tree', 'rg',
                    'Get-Content', 'Get-ChildItem', 'Select-String')]   # not python: the LM CMD is a python command


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
            room = run.dir / 'quizroom' / agent['id']
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

    takers = [a for a in run.scenario['roster'] if (run.stores / a['id']).exists()]
    with ThreadPoolExecutor(max_workers=run.scenario.get('parallel', 4)) as pool:
        list(pool.map(one, takers))   # list() re-raises a session's exception (e.g. SpendLimit)
    run.mark('quiz' if mode == 'memory' else f'quiz-{mode}')


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
        if out.exists():
            continue
        prompt = ('You are grading a knowledge quiz for a software project. For each question compare the answer with '
                  'the ground truth. Grades: "correct" (all key points right), "partial" (some key points, nothing wrong), '
                  '"stale" (gives the outdated answer where one is listed), "wrong" (contradicts the ground truth), '
                  '"unknown" (answered unknown or no answer). Do not use any tools.\n\n'
                  f'QUESTIONS AND GROUND TRUTH\n{key_text}\n\nANSWERS\n{json.dumps(a.get("answers", []), indent=1)}\n\n'
                  'Reply with only a JSON object: {"grades": [{"id": "q1", "grade": "...", "note": "short reason"}, ...]}')
        # Keyed by the answers graded, so corrected answers are graded afresh rather than served a cached grade.
        digest = hashlib.sha256(json.dumps(a.get('answers', []), sort_keys=True).encode()).hexdigest()[:8]
        key = (f'grade/{path.stem}' if mode == 'memory' else f'grade-{mode}/{path.stem}') + f'@{digest}'
        row = _session(run, key, grader, prompt, room, allow=[], deny=QUIZ_DENY + ['Bash', 'PowerShell'],
                       settings={'disableAllHooks': True})
        write_json(out, {'agent': path.stem, **(_last_json(full_final(run, key, row)) or {'error': 'unparsed'})})
    run.mark('grade' if mode == 'memory' else f'grade-{mode}')


# ---------------- smoke & isolation ----------------
def smoke(scenario):
    """Tiny end-to-end check of the harness on a throwaway run (no Maven priming)."""
    run = init(scenario, label='smoke', prime=False)
    agent = run.active(1)[0]
    secret = run.scenario_dir / 'ground_truth.json'
    other = next(a for a in run.active(1) if a['id'] != agent['id'])
    other_note = run.stores / other['id'] / 'bindings.json'
    prompt = ('This is a short tooling check of the sandbox, not project work. Do each step once and do not work around a refusal.\n'
              '1. Run exactly this one shell command: `cd modern && git status --short && cd ..`\n'
              f'2. Use the Read tool on {secret} and report whether it was allowed.\n'
              f'3. Run the shell command `cat "{secret.as_posix()}"` and report whether it was allowed.\n'
              f'4. Use the Read tool on {other_note} and report whether it was allowed.\n'
              '5. Reply with one line per step: allowed or blocked.')
    row = _session(run, 'smoke/' + agent['id'], agent, prompt, run.ws / agent['id'])
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
    iso = isolation(run)
    checks['real_store_untouched'] = iso['ok']
    report = {'run': run.dir.name, 'checks': checks, 'session': {k: row.get(k) for k in ('subtype', 'cost_usd', 'seconds', 'turns', 'lm_calls')},
              'isolation': iso, 'final': row.get('final')}
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
