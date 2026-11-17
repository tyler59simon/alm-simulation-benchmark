"""One headless Claude Code session per agent-day: launch, budget, timeout, transcript and cost capture."""
import json
import subprocess
import time
from pathlib import Path

from . import clock, lmsource
from .common import append_jsonl, clean_env, config, kill_tree, lm_call, now, rule_path, session_hash


def deny_rules(run, agent_id):
    """Keep an agent inside its own clone and store: no harness, scenario, ground truth, other stores or real store."""
    blocked = [run.scenario_dir, run.dir.parent.parent / 'simkit', run.dir.parent.parent / 'scenarios',
               run.dir / 'quiz', run.dir / 'transcripts', run.dir / 'integration', run.dir / 'handover']
    blocked += [p for p in run.stores.glob('*') if p.name != agent_id]
    blocked += [p for p in run.ws.glob('*') if p.name != agent_id]
    real = config().get('real_store')
    if real:
        blocked.append(Path(real))
    rules = []
    for p in blocked:
        r = rule_path(p)
        rules += [f'Read({r}/**)', f'Edit({r}/**)', f'Write({r}/**)']
    # The harness's own bookkeeping in the run folder (state, costs, logs: other agents' replies live there).
    base = rule_path(run.dir)
    for pat in ('*.json', '*.jsonl', '*.log', '*.out', 'npcroom/**', 'chat/**'):
        rules += [f'Read({base}/{pat})', f'Edit({base}/{pat})', f'Write({base}/{pat})']
    if run.workspace_enabled:
        # Slack DMs are private: an engineer reads only their own threads (team_chat.py reads them on their behalf).
        chat = rule_path(run.workspace / 'chat')
        rules += [f'Read({chat}/**)', f'Edit({chat}/**)', f'Write({chat}/**)']
    return rules


LINGER_S = 30   # seconds a session may stay alive after its result event


def _is_result(line):
    try:
        ev = json.loads(line)
    except ValueError:
        return False
    return isinstance(ev, dict) and ev.get('type') == 'result'


USAGE_KEYS = ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')


def parse_transcript(path):
    """Session id, model, final result event, tool and LM call counts, and token usage summed over assistant messages
    (the only usage a session killed before its result event leaves behind)."""
    info = {'session_id': None, 'result': None, 'tool_calls': 0, 'lm_calls': 0}
    usage, seen = dict.fromkeys(USAGE_KEYS, 0), set()
    try:
        lines = Path(path).read_text(encoding='utf-8', errors='replace').splitlines()
    except FileNotFoundError:
        return info
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get('type') == 'system' and ev.get('subtype') == 'init' and not info['session_id']:
            info['session_id'] = ev.get('session_id')
            info['model'] = ev.get('model')
        elif ev.get('type') == 'assistant':
            msg = ev.get('message') or {}
            if isinstance(msg.get('usage'), dict) and msg.get('id') not in seen:   # one message spans several events
                seen.add(msg.get('id'))
                for k in USAGE_KEYS:
                    usage[k] += msg['usage'].get(k) or 0
            for c in msg.get('content') or []:
                if c.get('type') == 'tool_use':
                    info['tool_calls'] += 1
                    if lm_call((c.get('input') or {}).get('command')):
                        info['lm_calls'] += 1
        elif ev.get('type') == 'result':
            info['result'] = ev
    info['assistant_usage'] = usage
    return info


def run_rev(cwd):
    try:
        r = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=cwd, capture_output=True, text=True, timeout=30)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def launch(run, key, agent, prompt, cwd, store, tier, allow=(), deny=(), settings=None, timeout_min=30,
           extra_env=None, system_append=None, memory=None):
    """Run `claude -p` with the prompt on stdin. Returns the session row (also appended to costs.jsonl/state).
    memory overrides the run's arm for this one session (arm D's fresh agent needs Living Memory on any run)."""
    cfg = config()
    out = run.transcripts / f'{key}.jsonl'
    out.parent.mkdir(parents=True, exist_ok=True)
    (run.transcripts / f'{key}.prompt.md').write_text(prompt, encoding='utf-8')
    args = [cfg['claude'], '-p', '--model', tier['model'], '--output-format', 'stream-json', '--verbose',
            '--max-budget-usd', str(tier.get('budget_usd', 1.0)), '--permission-mode', tier.get('permission_mode', 'acceptEdits')]
    if tier.get('effort'):
        args += ['--effort', tier['effort']]
    memory = memory or run.options.get('memory', 'on')
    mem_env = {}
    if memory in ('off', 'builtin'):
        # No Living Memory hooks, so no session line: the gated CLAUDE.md protocol block stays inert.
        # off (A0): Claude Code's own auto-memory is off too. builtin (A1): Claude Code as shipped, auto-memory on.
        settings = {**(settings or {}), 'disableAllHooks': True, 'autoMemoryEnabled': memory == 'builtin'}
        if memory == 'off':
            mem_env['CLAUDE_CODE_DISABLE_AUTO_MEMORY'] = '1'
    if settings:
        args += ['--settings', json.dumps(settings)]
    if system_append:
        args += ['--append-system-prompt', system_append]
    if allow:
        args += ['--allowedTools', *allow]
    if deny:
        args += ['--disallowedTools', *deny]
    tc_env, tc_path = run.toolchain_env()
    sim_env = ({'SIM_RUN': str(run.dir), 'SIM_AGENT': agent['id'], 'SIM_AGENT_NAME': agent.get('name', agent['id']),
                'SIM_WORKSPACE': str(run.workspace)} if run.workspace_enabled else {})
    home = lmsource.home_of(run)
    if home:   # lm_src run: this checkout's hooks and instruction block, not the user's ~/.claude
        extra_env = {**lmsource.env(home), **(extra_env or {})}
    sim_time = clock.session_time(run, key)   # None unless the run has a simulated calendar
    # clean_env strips inherited CLAUDE* and LIVING_MEMORY* variables; the clock variables are passed in, so they survive it.
    env = clean_env({**tc_env, 'LIVING_MEMORY_ROOT': str(store), 'LIVING_MEMORY_LOG_LEVEL': 'debug',
                     'LIVING_MEMORY_LOG_CONTENT': '1', 'LIVING_MEMORY_HEADLESS': '1', **sim_env,
                     **clock.session_env(sim_time), **(extra_env or {})}, tc_path)
    env.update(mem_env)   # after clean_env, which strips CLAUDE* variables
    rev = lambda: run_rev(cwd)   # noqa: E731  the agent's HEAD before and after, so probes can grade what this session committed
    rev_before = rev()
    t0, started = time.time(), now()
    with open(out, 'w', encoding='utf-8') as fo, open(out.with_suffix('.stderr.txt'), 'w', encoding='utf-8') as fe:
        proc = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=fo, stderr=fe,
                                text=True, encoding='utf-8')
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except OSError:
            pass
        timed_out, lingered = False, None
        deadline, result_at, pos, buf = time.monotonic() + timeout_min * 60, None, 0, b''
        while proc.poll() is None:
            if time.monotonic() >= deadline:
                timed_out = True
                kill_tree(proc.pid)
                try:
                    proc.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    proc.wait()   # as below: an uncaught error here would lose the row and re-pay the session on resume
                break
            if result_at is None:
                try:
                    with open(out, 'rb') as fr:
                        fr.seek(pos)
                        chunk = fr.read()
                        pos = fr.tell()
                except OSError:
                    chunk = b''
                *lines, buf = (buf + chunk).split(b'\n')
                if any(_is_result(line) for line in lines):
                    result_at = time.monotonic()
            elif time.monotonic() - result_at > LINGER_S:
                # The agent has answered but a background command it started keeps the process alive until that
                # command's own time limit; end it so one leftover wait loop does not hold up the whole wave.
                lingered = round(time.monotonic() - result_at, 1)
                kill_tree(proc.pid)
                try:
                    proc.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    proc.wait()   # could not kill it: wait as before rather than fail the run
                break
            time.sleep(2)
    info = parse_transcript(out)
    res = info['result'] or {}
    sid = info['session_id'] or res.get('session_id')
    row = {'key': key, 'agent': agent['id'], 'tier': agent.get('tier'), 'model': info.get('model') or tier['model'],
           'started': started, 'ended': now(), 'seconds': round(time.time() - t0, 1), 'exit': proc.returncode,
           'timed_out': timed_out, 'ended_after_result': lingered, 'subtype': res.get('subtype'), 'is_error': res.get('is_error'),
           'cost_usd': res.get('total_cost_usd'), 'turns': res.get('num_turns'), 'usage': res.get('usage') or info['assistant_usage'],
           'session_id': sid, 'session_hash': session_hash(sid) if sid else None,
           'tool_calls': info['tool_calls'], 'lm_calls': info['lm_calls'], 'final': (res.get('result') or '')[-1500:],
           'rev_before': rev_before, 'rev_after': rev(), 'memory': memory}
    if sim_time:
        row['sim_time'] = sim_time.isoformat(timespec='seconds')
    if row['cost_usd'] is None:
        # No result event (timeout, crash): the real cost is unknown, so the spend limit counts the session's budget cap.
        row['cost_bound_usd'] = float(tier.get('budget_usd', 1.0))
    append_jsonl(run.dir / 'costs.jsonl', {k: row.get(k) for k in ('key', 'agent', 'model', 'cost_usd', 'cost_bound_usd', 'seconds', 'session_hash')})
    run.update_state(lambda s: s['sessions'].__setitem__(key, row))
    return row
