"""Turn a frozen run folder into metrics.json (fixed schema, so runs compare) plus a short text summary."""
import fnmatch
import json
import random
import re
import statistics
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from . import lmsource
from .common import LM_SUBCOMMANDS, clean_env, config, lm_call, lm_calls, read_json, read_jsonl, write_json

SCHEMA = 4
NOISE = [r'\b[0-9a-f]{7,40}\b(?=.*commit)|commit [0-9a-f]{7,}', r'(?i)\bsprint \d+ (status|progress|summary)\b',
         r'(?i)\b(tests? (pass|passing)|\d+ tests)\b', r'(?i)\bstandup\b']


# ---------- notes ----------
def parse_note(path):
    text = path.read_text(encoding='utf-8', errors='replace')
    meta, body = {}, text
    if text.startswith('---'):
        end = text.find('\n---', 3)
        for line in text[3:end].splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                try:
                    meta[k.strip()] = json.loads(v.strip())
                except ValueError:
                    meta[k.strip()] = v.strip()
        body = text[end + 4:]
    meta['_body'] = body
    meta['_file'] = str(path)
    return meta


def store_notes(store):
    out = []
    for p in Path(store, 'domains').glob('*/*/*.md'):
        if p.parent.name in ('notes', 'archive'):
            n = parse_note(p)
            n['_folder'] = p.parent.name
            out.append(n)
    return out


def is_active(n):
    return n.get('status', 'active') == 'active' and n['_folder'] == 'notes'


def text_of(n):
    return (str(n.get('title', '')) + '\n' + n['_body']).lower()


# ---------- per-store ----------
def pct(values, q):
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))], 1)


def exit_code(row):
    """Exit code of a command log row: Living Memory writes `exit_code` (older notes of the format used `exit`)."""
    return row.get('exit_code', row.get('exit'))


def store_metrics(store, truth):
    notes = store_notes(store)
    active = [n for n in notes if is_active(n)]
    m = {'notes_total': len(notes), 'notes_active': len(active),
         'by_type': dict(Counter(n.get('type') for n in notes)), 'by_status': dict(Counter(n.get('status') for n in notes)),
         'by_domain': dict(Counter(n.get('domain') for n in notes)),
         'maps': sum(1 for n in active if n.get('type') == 'map'),
         'status_snapshots': sum(1 for n in active if n.get('type') == 'status'),
         'global_notes': sum(1 for n in notes if n.get('domain') == '_global'),
         'active_chars': sum(len(n['_body']) for n in active),
         'noise_notes': sum(1 for n in active if any(re.search(p, text_of(n)) for p in NOISE)),
         'origins': dict(Counter(str(n.get('origin', '')).split(':')[-1] for n in notes))}
    facts = {}
    for fid, f in truth.get('facts', {}).items():
        cur = [re.compile(p, re.I) for p in f.get('patterns', {}).get('current', [])]
        stale = [re.compile(p, re.I) for p in f.get('patterns', {}).get('stale', [])]
        has_cur = [n['id'] for n in active if any(r.search(text_of(n)) for r in cur)]
        stale_only = [n['id'] for n in active if stale and any(r.search(text_of(n)) for r in stale)
                      and not any(r.search(text_of(n)) for r in cur)]
        facts[fid] = {'current': len(has_cur), 'stale_active': len(stale_only)}
    m['facts'] = facts
    logs = [r for p in sorted(Path(store, 'logs').glob('*.jsonl')) for r in read_jsonl(p)]
    hooks = [r for r in logs if r.get('kind') == 'hook']
    cmds = [r for r in logs if r.get('kind') == 'command']
    ctx = defaultdict(list)
    for r in hooks:
        if r.get('context_chars'):
            ctx[r.get('event')].append(r['context_chars'])
    outcomes = Counter(o for r in hooks for o in (r.get('outcome') or []))
    m['hooks'] = {'events': dict(Counter(r.get('event') for r in hooks)), 'outcomes': dict(outcomes),
                  'context_chars': {e: {'n': len(v), 'mean': round(statistics.mean(v)), 'max': max(v)} for e, v in ctx.items()},
                  'ms_p50': pct([r['ms'] for r in hooks if 'ms' in r], .5), 'ms_p95': pct([r['ms'] for r in hooks if 'ms' in r], .95)}
    failed = [r for r in cmds if exit_code(r) not in (0, None)]
    m['commands'] = {'total': len(cmds), 'errors': len(failed),
                     'by_event': dict(Counter(r.get('event') for r in cmds)),
                     'error_reasons': dict(Counter(str(r.get('reason') or r.get('error') or '')[:80] for r in failed))}
    usage = [r for p in Path(store, '.turns').glob('usage-*.jsonl') for r in read_jsonl(p)]
    m['usage'] = dict(Counter(r.get('e') for r in usage))
    m['injected_distinct'] = len({r.get('ref') for r in usage if r.get('e') == 'inject'})
    m['read_after_inject'] = len({r.get('ref') for r in usage if r.get('e') == 'read'} & {r.get('ref') for r in usage if r.get('e') == 'inject'})
    receipts = Counter()
    for p in Path(store, '.turns').glob('*.json'):
        if p.name.endswith('.current.json'):
            continue
        r = read_json(p, {}) or {}
        if isinstance(r, dict) and 'outcome' in r:
            receipts[r.get('outcome') or 'none'] += 1
    m['receipts'] = dict(receipts)
    m['reminders'] = len(list(Path(store, '.turns').glob('*.reminded')))
    return m


def automemory_files(ws_path, home=None):
    """Claude Code's own auto-memory for the agent's clone (should stay empty where Living Memory applies). `home` is the
    Claude config folder the sessions used: a run's private one for lm_src runs, else the user's ~/.claude."""
    mangled = re.sub(r'[:\\/ ._]', '-', str(ws_path))
    d = Path(home or Path.home() / '.claude') / 'projects' / mangled / 'memory'
    return len([p for p in d.rglob('*') if p.is_file()]) if d.exists() else 0


END_SNAPSHOT = 'stores-at-end.json'
END_KEYS = ('notes_total', 'notes_active', 'by_type', 'by_status', 'maps', 'active_chars', 'noise_notes', 'status_snapshots', 'facts')


def snapshot_stores(run):
    """Store contents when the last sprint ended, written once before the first quiz. Quizzes let agents update notes,
    so fact coverage and capture/retrieval classification read this snapshot when it exists."""
    path = run.dir / END_SNAPSHOT
    if path.exists():
        return read_json(path)
    snap = {p.name: {k: v for k, v in store_metrics(p, run.truth).items() if k in END_KEYS}
            for p in sorted(run.stores.glob('*')) if p.is_dir() and not p.name.startswith('_')}
    write_json(path, snap)
    return snap


# ---------- transcripts ----------
def transcript_metrics(path, run_dir, agent):
    tools, lm_sub, lm_err, leaks, pending = Counter(), Counter(), 0, [], {}
    blocked = [str(run_dir / 'scenario'), 'ground_truth', str(run_dir / 'stores')]
    real = config().get('real_store') or ''
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        msg = ev.get('message') if isinstance(ev, dict) else None
        content = msg.get('content') if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get('type') == 'tool_use':
                tools[c.get('name')] += 1
                s = json.dumps(c.get('input', {}))
                sub = lm_call((c.get('input') or {}).get('command'))
                if sub:
                    lm_sub[sub] += 1
                    pending[c.get('id')] = sub
                low = s.replace('\\\\', '/').replace('\\', '/').lower()
                for b in blocked + ([real] if real else []):
                    bl = b.replace('\\', '/').lower()
                    if bl and bl in low and not (bl.endswith('/stores') and f'stores/{agent}' in low):
                        leaks.append({'tool': c.get('name'), 'path': b})
            elif c.get('type') == 'tool_result' and c.get('tool_use_id') in pending and c.get('is_error'):
                lm_err += 1
    return {'tools': dict(tools), 'lm_subcommands': dict(lm_sub), 'lm_errors': lm_err, 'leaks': leaks[:10]}


# ---------- app ----------
def _eval_checks(spec, corpus):
    out = []
    for c in spec['checks']:
        ok = True
        if c.get('all'):
            ok &= all(re.search(p, corpus) for p in c['all'])
        if c.get('any'):
            ok &= any(re.search(p, corpus) for p in c['any'])
        if c.get('none'):
            ok &= not any(re.search(p, corpus) for p in c['none'])
        out.append({'fact': c['fact'], 'desc': c['desc'], 'pass': bool(ok)})
    return out


def app_checks(run):
    spec = read_json(run.scenario_dir / run.scenario.get('app_checks', 'app_checks.json'))
    if not spec:
        return None
    root = run.integration / spec.get('root', '.')
    files = list(root.glob(spec.get('glob', '**/*'))) if root.exists() else []
    corpus = '\n'.join(p.read_text(encoding='utf-8', errors='replace') for p in files if p.is_file() and 'target' not in p.parts)
    return {'files': len(files), 'lines': corpus.count('\n'), 'checks': _eval_checks(spec, corpus)}


def _glob_match(rel, pattern):
    """Path.glob-like match of a root-relative posix path ('**/' also matches no folder)."""
    return fnmatch.fnmatch(rel, pattern) or (pattern.startswith('**/') and fnmatch.fnmatch(rel, pattern[3:]))


def _corpus_at(repo, sha, root, pattern):
    """Concatenated text of the files under root matching pattern at commit sha (one git cat-file process)."""
    env = clean_env({'GIT_TERMINAL_PROMPT': '0'})
    prefix = '' if root in ('', '.') else root.rstrip('/') + '/'
    ls = subprocess.run(['git', 'ls-tree', '-r', '--name-only', sha, '--', prefix or '.'], cwd=repo, env=env,
                        capture_output=True, text=True, encoding='utf-8', errors='replace')
    paths = [p for p in ls.stdout.splitlines() if p.startswith(prefix) and 'target' not in p.split('/')
             and _glob_match(p[len(prefix):], pattern)]
    if not paths:
        return ''
    out = subprocess.run(['git', 'cat-file', '--batch'], cwd=repo, env=env, capture_output=True,
                         input=''.join(f'{sha}:{p}\n' for p in paths).encode('utf-8')).stdout
    texts, i = [], 0
    while i < len(out):
        nl = out.index(b'\n', i)
        header = out[i:nl].split()
        if len(header) < 3 or header[1] != b'blob':   # "<spec> missing"
            i = nl + 1
            continue
        size = int(header[2])
        texts.append(out[nl + 1:nl + 1 + size].decode('utf-8', errors='replace'))
        i = nl + 1 + size + 1
    return '\n'.join(texts)


def app_check_history(run):
    """app_checks on main after every CI step: a check that passed and later fails is a regression (work undone)."""
    spec = read_json(run.scenario_dir / run.scenario.get('app_checks', 'app_checks.json'))
    if not spec or not run.integration.exists():
        return None
    points, last_sha = [], None
    for row in read_jsonl(run.dir / 'ci.jsonl'):
        sha = row.get('main')
        if not sha or sha == last_sha:
            continue
        last_sha = sha
        checks = _eval_checks(spec, _corpus_at(run.integration, sha, spec.get('root', '.'), spec.get('glob', '**/*')))
        points.append({'label': row.get('label'), 'main': sha, 'pass': [c['pass'] for c in checks]})
    regressions = []
    for ci, c in enumerate(spec['checks']):
        # A check with only 'none' patterns passes on an empty codebase; its passes count once it has failed.
        vacuous, failed_once, passed_at = not (c.get('all') or c.get('any')), False, None
        for p in points:
            if p['pass'][ci]:
                if failed_once or not vacuous:
                    passed_at = passed_at or p['label']
            else:
                failed_once = True
            if not p['pass'][ci] and passed_at:
                regressions.append({'fact': c['fact'], 'desc': c['desc'], 'passed_at': passed_at, 'failed_at': p['label']})
                passed_at = None
    return {'points': len(points), 'regression_count': len(regressions), 'regressions': regressions,
            'first_pass': {c['desc']: next((p['label'] for p in points if p['pass'][ci]), None) for ci, c in enumerate(spec['checks'])}}


# ---------- quiz ----------
GRADE_SCORE = {'correct': 1.0, 'partial': 0.5}


def quiz_repo_reads(run):
    """Memory-only quiz commands that name the agent's clone, the integration repo or the workspace: a read that the
    deny rules did not catch would let the repo answer for memory."""
    # Claude Code's own transcripts of the agent's work sessions would also answer for memory.
    marks = [str(run.ws), str(run.dir / 'integration'), str(run.workspace) if run.workspace_enabled else None,
             '.claude/projects']
    marks = [m.replace('\\', '/').lower() for m in marks if m]
    found = {}
    for t in sorted((run.transcripts / 'quiz').glob('*.jsonl')):
        for ev in read_jsonl(t):
            if ev.get('type') != 'assistant':
                continue
            for c in (ev.get('message') or {}).get('content') or []:
                if c.get('type') == 'tool_use':
                    raw = ' '.join(str(v) for v in (c.get('input') or {}).values())   # unescaped command text
                    text = raw.replace('\\', '/').lower()
                    if any(m in text for m in marks):
                        found.setdefault(t.stem, []).append(text[:200])
    return found


def quiz_metrics(run, per_store, mode='memory'):
    """Every taker x every question: a question the agent did not answer or the grader did not grade scores 0 as
    'missing' (an unparsed grade file makes all of that agent's questions missing) instead of leaving the denominator."""
    qs = {q['id']: q for q in run.quiz.get('questions', [])}
    facts = run.truth.get('facts', {})
    matrix, rows, unparsed = {}, [], []
    base = run.dir / 'quiz' if mode == 'memory' else run.dir / 'quiz' / mode
    grades_dir = base / 'grades'
    if not grades_dir.exists():
        return None
    takers = sorted({p.stem for d in (base / 'answers', grades_dir) for p in d.glob('*.json')})
    for agent in takers:
        g = read_json(grades_dir / f'{agent}.json', {}) or {}
        if g.get('error'):
            unparsed.append(agent)
        matrix[agent] = {x['id']: x.get('grade') for x in g.get('grades', []) if isinstance(x, dict) and x.get('id') in qs}
    for agent, grades in matrix.items():
        for qid, q in qs.items():
            grade = grades.get(qid) or 'missing'
            f = q['fact']
            should = agent in facts.get(f, {}).get('should_know', [])
            in_store = (per_store.get(agent, {}).get('facts', {}).get(f, {}).get('current', 0) > 0)
            ok = grade in GRADE_SCORE
            kind = ('ok' if ok else 'stale' if grade == 'stale' else 'missing' if grade == 'missing'
                    else 'retrieval_miss' if in_store else 'capture_gap')
            rows.append({'agent': agent, 'q': qid, 'fact': f, 'grade': grade, 'should_know': should, 'in_store': in_store, 'kind': kind})
    def score(sel):
        sel = list(sel)
        return round(sum(GRADE_SCORE.get(r['grade'], 0) for r in sel) / len(sel), 3) if sel else None
    by_agent = {a: score(r for r in rows if r['agent'] == a) for a in matrix}
    by_fact = {f: score(r for r in rows if r['fact'] == f and r['should_know']) for f in facts}
    return {'matrix': matrix, 'score_all': score(rows), 'score_should_know': score(r for r in rows if r['should_know']),
            'score_not_should_know': score(r for r in rows if not r['should_know']),
            'by_agent': by_agent, 'by_fact_should_know': by_fact,
            'failure_kinds_should_know': dict(Counter(r['kind'] for r in rows if r['should_know'])),
            'stale_answers': [f"{r['agent']}:{r['q']}" for r in rows if r['grade'] == 'stale'],
            'missing': sum(1 for r in rows if r['grade'] == 'missing'), 'unparsed': unparsed}


def quiz_other_shell(run):
    """Shell commands in memory-only quiz sessions that are not Living Memory calls (the deny list cannot block every
    read command, e.g. gc, gci, sls or python -c, without also blocking the LM command)."""
    found = {}
    for t in sorted((run.transcripts / 'quiz').glob('*.jsonl')):
        for tool, cmd in _shell_calls(t):
            if tool in ('Bash', 'PowerShell') and not lm_call(cmd):
                found.setdefault(t.stem, []).append(cmd[:200])
    return found


# ---------- mistakes, pointers, latency ----------
WORK_KEY = re.compile(r'^s\d+(d\d+)?/')


def _tool_results(path):
    """Text of every tool result in a transcript."""
    out = []
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        msg = ev.get('message') if isinstance(ev, dict) else None
        content = msg.get('content') if isinstance(msg, dict) else None
        for c in content if isinstance(content, list) else []:
            if isinstance(c, dict) and c.get('type') == 'tool_result':
                t = c.get('content')
                out.append(t if isinstance(t, str) else json.dumps(t))
    return out


def result_mistake(run, mk, sess):
    """A trap the environment reports (e.g. a rejected commit). The first session that hits it teaches the agent;
    every later session that hits it again is a repeat: knowledge that did not carry across sessions."""
    pat = re.compile(mk['pattern'])
    per = defaultdict(lambda: {'sessions_hit': 0, 'hits': 0, 'repeat_sessions': 0, 'first': None})
    for r in sess:
        t = run.transcripts / f"{r['key']}.jsonl"
        if not t.exists():
            continue
        n = sum(1 for text in _tool_results(t) if pat.search(text))
        if n:
            a = per[r['agent']]
            a['hits'] += n
            a['sessions_hit'] += 1
            if a['first'] is None:
                a['first'] = r['key']
            else:
                a['repeat_sessions'] += 1
    return {'desc': mk['desc'], 'kind': 'result', 'per_agent': dict(per), 'agents_hit': len(per),
            'repeat_sessions': sum(v['repeat_sessions'] for v in per.values()),
            'total': sum(v['hits'] for v in per.values())}


def lint_told(run, rule):
    """{agent: start of the first session whose prompt showed a violation of this rule}. The #ci-bot message shows only
    the tail of the CI output and only while main is red, so a red CI row alone does not mean an author saw the rule."""
    told = {}
    for r in sorted((r for r in run.state()['sessions'].values() if WORK_KEY.match(r['key'])), key=lambda r: r['started']):
        p = run.transcripts / f"{r['key']}.prompt.md"
        if r['agent'] not in told and p.exists() and f'ci-lint {rule}:' in p.read_text(encoding='utf-8', errors='replace'):
            told[r['agent']] = r['started']
    return told


def lint_mistake(run, mk):
    """CI lint violations of one rule, by author (git blame). A violation that first appears after the author's prompt
    showed them that rule is a repeat."""
    told = lint_told(run, mk['rule'])
    per = defaultdict(lambda: {'violations': 0, 'repeats': 0, 'told_at': None})
    seen = set()
    for row in read_jsonl(run.dir / 'ci.jsonl'):
        for v in row.get('lint') or []:
            if v.get('rule') != mk['rule']:
                continue
            k = (v.get('author'), v['file'], v['text'])
            if k in seen:
                continue
            seen.add(k)
            a = per[v.get('author') or '?']
            a['told_at'] = told.get(v.get('author'))
            a['violations'] += 1
            if a['told_at'] and a['told_at'] < row.get('ts', ''):
                a['repeats'] += 1
    return {'desc': mk['desc'], 'kind': 'lint', 'per_agent': dict(per), 'agents_hit': len(per),
            'repeats': sum(v['repeats'] for v in per.values()), 'total': sum(v['violations'] for v in per.values())}


def probe_metrics(run):
    rows = [read_json(p) for p in sorted((run.dir / 'probes').glob('*.json'))] if (run.dir / 'probes').exists() else []
    rows = [r for r in rows if r]
    scored = [r['score'] for r in rows if r.get('score') is not None]
    return {'probes': len(rows), 'mean_score': round(sum(scored) / len(scored), 3) if scored else None,
            'missing': sum(1 for r in rows if r.get('missing')), 'judge_errors': sum(1 for r in rows if r.get('judge_error')),
            'by_probe': {r['id']: r.get('score') for r in rows},
            'cost_usd': round(sum(r.get('cost_usd') or 0 for r in rows), 4),
            'mean_turns': round(sum(r.get('turns') or 0 for r in rows) / len(rows), 1) if rows else None,
            'mean_tool_calls': round(sum(r.get('tool_calls') or 0 for r in rows) / len(rows), 1) if rows else None,
            'mean_seconds': round(sum(r.get('seconds') or 0 for r in rows) / len(rows), 1) if rows else None}


TOKEN_KEYS = ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')


def efficiency(run):
    """Mean cost, turns, tool calls, seconds and tokens per session, by kind of session."""
    kinds = {'work': WORK_KEY, 'quiz_memory': re.compile(r'^quiz/'), 'quiz_repo': re.compile(r'^quiz-repo/')}
    out = {}
    sess = list(run.state()['sessions'].values())
    for name, rx in kinds.items():
        rows = [r for r in sess if rx.match(r['key']) and not r['key'].endswith('.resolve')]
        if rows:
            out[name] = {k: round(sum((r.get(f) or 0) for r in rows) / len(rows), 4 if k == 'cost_usd' else 1)
                         for k, f in (('cost_usd', 'cost_usd'), ('turns', 'turns'), ('tool_calls', 'tool_calls'), ('seconds', 'seconds'))}
            out[name]['sessions'] = len(rows)
            out[name]['tokens'] = {k: round(sum((r.get('usage') or {}).get(k) or 0 for r in rows) / len(rows)) for k in TOKEN_KEYS}
    chat = [r for r in read_jsonl(run.dir / 'costs.jsonl') if str(r.get('key', '')).startswith('chat/')]
    out['chat'] = {'messages': len(chat), 'cost_usd': round(sum(r.get('cost_usd') or 0 for r in chat), 4)}
    return out


def cost_split(run):
    """Known dollars by who spent them: the team's work sessions (merge resolves included), the simulated colleagues
    (chat), and the harness measuring the run (quizzes, grading, probe judging, audits). Sessions with no recorded cost
    (no result event) are counted, not guessed."""
    out = {'work_cost_usd': 0.0, 'chat_cost_usd': 0.0, 'harness_cost_usd': 0.0, 'cost_unknown_sessions': 0}
    for r in read_jsonl(run.dir / 'costs.jsonl'):
        key = str(r.get('key', ''))
        kind = 'work' if WORK_KEY.match(key) else 'chat' if key.startswith('chat/') else 'harness'
        if r.get('cost_usd') is None:
            out['cost_unknown_sessions'] += 1
        out[f'{kind}_cost_usd'] += r.get('cost_usd') or 0
    return {k: round(v, 4) if isinstance(v, float) else v for k, v in out.items()}


# ---------- real-world work metrics (from transcripts and git, no model calls) ----------
CHANGE_TOOLS = ('Edit', 'Write', 'NotebookEdit', 'MultiEdit')
READ_SHELL = re.compile(r'(?i)(?:^|[;&|(]|&&)\s*(?:cat|type|gc|get-content|head|tail|less|more)\s+(?:-\S+\s+(?:\d+\s+)?)*'
                        r'["\']?([^\s"\'|;&<>]+)')


def _tool_uses(path):
    """(name, input) for every tool call in a transcript, in order."""
    from .replies import events
    out = []
    for ev in events(path):
        msg = ev.get('message')
        if ev.get('type') != 'assistant' or not isinstance(msg, dict):
            continue
        for c in msg.get('content') or []:
            if isinstance(c, dict) and c.get('type') == 'tool_use':
                out.append((c.get('name'), c.get('input') if isinstance(c.get('input'), dict) else {}))
    return out


def _norm_path(p, clone):
    p = str(p).replace('\\', '/').lower()
    p = re.sub(r'^/([a-z])/', r'\1:/', p)
    c = clone.replace('\\', '/').lower().rstrip('/') + '/'
    if p.startswith(c):
        p = p[len(c):]
    while p.startswith('./'):
        p = p[2:]
    return p


def read_targets(uses, clone):
    """Distinct things a session read: files (Read, cat/type/Get-Content), and Grep/Glob searches."""
    out = set()
    for name, inp in uses:
        if name == 'Read' and inp.get('file_path'):
            out.add(('file', _norm_path(inp['file_path'], clone)))
        elif name in ('Grep', 'Glob') and inp.get('pattern'):
            out.add((name.lower(), inp['pattern'], _norm_path(inp.get('path') or '', clone)))
        elif name in ('Bash', 'PowerShell'):
            for m in READ_SHELL.finditer(str(inp.get('command', ''))):
                out.add(('file', _norm_path(m.group(1), clone)))
    return out


def first_change(uses):
    """Tool calls made before the session's first edit or commit (None when it changed nothing)."""
    for i, (name, inp) in enumerate(uses):
        if name in CHANGE_TOOLS or (name in ('Bash', 'PowerShell') and re.search(r'\bgit\b[^|;&]*\bcommit\b', str(inp.get('command', '')))):
            return i
    return None


def _work_sessions(run):
    return sorted((r for r in run.state()['sessions'].values() if WORK_KEY.match(r['key']) and not r['key'].endswith('.resolve')),
                  key=lambda r: r['started'])


def rediscovery(run):
    """Re-exploration: how much of what a session read the same agent had already read in an earlier session, and how
    many tool calls a session made before its first change. Memory should lower both; a re-read is not always waste
    (the file may have changed), so this is a proxy that compares across arms, not an absolute."""
    seen, rows = defaultdict(set), []
    for r in _work_sessions(run):
        t = run.transcripts / f"{r['key']}.jsonl"
        if not t.exists():
            continue
        uses = _tool_uses(t)
        targets = read_targets(uses, str(run.ws / r['agent']))
        again = targets & seen[r['agent']]
        seen[r['agent']] |= targets
        rows.append({'key': r['key'], 'agent': r['agent'], 'reads': len(targets), 'rereads': len(again), 'before_change': first_change(uses)})
    if not rows:
        return None
    changed = [x['before_change'] for x in rows if x['before_change'] is not None]
    reads = sum(x['reads'] for x in rows)
    return {'sessions': len(rows), 'mean_reads': round(reads / len(rows), 2),
            'mean_rereads': round(sum(x['rereads'] for x in rows) / len(rows), 2),
            'reread_share': round(sum(x['rereads'] for x in rows) / reads, 3) if reads else None,
            'mean_calls_before_change': round(statistics.mean(changed), 1) if changed else None,
            'sessions_without_change': len(rows) - len(changed),
            'by_agent': {a: {'rereads': sum(x['rereads'] for x in rows if x['agent'] == a),
                             'reads': sum(x['reads'] for x in rows if x['agent'] == a)} for a in sorted({x['agent'] for x in rows})}}


def _tool_errors(path):
    """(tool name, text) of every tool result marked is_error; the name is suffixed ':lm' for a Living Memory call."""
    from .replies import events
    names, out = {}, []
    for ev in events(path):
        msg = ev.get('message')
        content = msg.get('content') if isinstance(msg, dict) else None
        for c in content if isinstance(content, list) else []:
            if not isinstance(c, dict):
                continue
            if c.get('type') == 'tool_use':
                names[c.get('id')] = str(c.get('name')) + (':lm' if lm_call((c.get('input') or {}).get('command')) else '')
            elif c.get('type') == 'tool_result' and c.get('is_error'):
                t = c.get('content')
                if isinstance(t, list):
                    t = '\n'.join(str(x.get('text', '')) if isinstance(x, dict) else str(x) for x in t)
                out.append((names.get(c.get('tool_use_id')), str(t or '')))
    return out


def error_signature(text):
    """First meaningful line of an error with paths, numbers and hex ids masked, so the same failure matches across
    sessions and agents."""
    lines = [re.sub(r'</?[a-z_]+>', '', l).strip() for l in text.splitlines()]
    line = next((l for l in lines if l and not re.fullmatch(r'(?i)exit code -?\d+', l)), '')
    line = re.sub(r'(?i)([a-z]:)?[\\/][^\s\'"`,;)]+', '<path>', line.lower())
    line = re.sub(r'\b[0-9a-f]{7,40}\b', '#', line)
    line = re.sub(r'\d+', '#', line)
    return re.sub(r'\s+', ' ', line)[:120]


def repeat_failures(run):
    """Generic repeated mistakes: an error an agent already hit in an earlier session (own repeat), or that a teammate
    hit earlier (team repeat: knowledge that could have been shared). Needs no planted trap. Failed Living Memory calls
    are counted apart (lm_*), so memory-tool friction does not read as a work mistake."""
    first_by = defaultdict(dict)   # signature -> {agent: first session key}
    sigs = defaultdict(lambda: {'agents': set(), 'sessions': 0, 'own_repeats': 0, 'team_repeats': 0, 'tool': None})
    own = team = lm_own = lm_team = 0
    for r in _work_sessions(run):
        t = run.transcripts / f"{r['key']}.jsonl"
        if not t.exists():
            continue
        for tool, text in {(tool, error_signature(text)) for tool, text in _tool_errors(t)}:
            if not text:
                continue
            s, a, lm = sigs[text], r['agent'], str(tool).endswith(':lm')
            s['sessions'] += 1
            s['tool'] = s['tool'] or tool
            if a in first_by[text]:
                s['own_repeats'] += 1
                own, lm_own = own + (not lm), lm_own + lm
            elif first_by[text]:
                s['team_repeats'] += 1
                team, lm_team = team + (not lm), lm_team + lm
            first_by[text].setdefault(a, r['key'])
            s['agents'].add(a)
    top = sorted(sigs.items(), key=lambda kv: -(kv[1]['own_repeats'] + kv[1]['team_repeats']))[:12]
    return {'signatures': len(sigs), 'error_sessions': sum(s['sessions'] for s in sigs.values()),
            'own_repeat_sessions': own, 'team_repeat_sessions': team,
            'lm_own_repeat_sessions': lm_own, 'lm_team_repeat_sessions': lm_team,
            'top': [{'signature': k, 'tool': v['tool'], 'agents': len(v['agents']), 'sessions': v['sessions'],
                     'own_repeats': v['own_repeats'], 'team_repeats': v['team_repeats']} for k, v in top if v['own_repeats'] + v['team_repeats']]}


def _label_order(key):
    m = re.match(r'^s(\d+)(?:d(\d+))?/', key)
    return (int(m[1]), int(m[2] or 1)) if m else None


def _scripted_messages(run):
    """(sprint, day, text) of every scripted message an agent received: Slack nudges, broadcasts and v1 memos."""
    ev, out = run.events, []
    for s, plan in (ev.get('sprints') or {}).items():
        for item in plan.values() if isinstance(plan, dict) else []:
            if not isinstance(item, dict):
                continue
            for m in item.get('slack') or []:
                out.append((int(s), m.get('day', 1), m.get('text', '')))
            if item.get('memo'):
                out.append((int(s), 1, item['memo'].get('text', '')))
    for m in ev.get('broadcast') or []:
        out.append((m['sprint'], m.get('day', 1), m.get('text', '')))
    return out


def stale_from(run, fact):
    """(sprint, day) of the first scripted message that states the fact's current answer, or None."""
    cur = [re.compile(p, re.I) for p in fact.get('patterns', {}).get('current', [])]
    hits = [(s, d) for s, d, text in _scripted_messages(run) if any(r.search(text) for r in cur)]
    return min(hits) if hits else None


def _added_code_lines(repo, a, b):
    """(file, line) for lines a diff adds outside documents and the captured legacy data."""
    from .gitops import git
    out, current = [], None
    diff = git(repo, 'diff', a, b, '--', '.', ':(exclude)legacy/data', check=False).stdout
    for line in diff.splitlines():
        if line.startswith('+++ '):
            current = line[6:] if line.startswith('+++ b/') else None
        elif line.startswith('+') and current and not current.lower().endswith(('.md', '.txt', '.html')):
            out.append((current, line[1:]))
    return out


def stale_actions(run):
    """Work built on an outdated decision: code lines a session added that match a fact's stale patterns, in sessions
    after the first scripted message stating the current answer. Heuristic (a comment naming the old rule matches too);
    read the hits before quoting the number."""
    facts = {fid: f for fid, f in run.truth.get('facts', {}).items() if f.get('patterns', {}).get('stale')}
    windows = {fid: stale_from(run, f) for fid, f in facts.items()}
    out = {fid: {'stale_from': (f's{w[0]}d{w[1]}' if w else None), 'sessions': 0, 'lines': 0, 'hits': []} for fid, w in windows.items()}
    for r in _work_sessions(run):
        when = _label_order(r['key'])
        due = [fid for fid, w in windows.items() if w and when and when >= w]
        if not due or not (r.get('rev_before') and r.get('rev_after')) or r['rev_before'] == r['rev_after']:
            continue
        added = _added_code_lines(run.ws / r['agent'], r['rev_before'], r['rev_after'])
        for fid in due:
            pats = [re.compile(p, re.I) for p in facts[fid]['patterns']['stale']]
            hits = [(f, l) for f, l in added if any(p.search(l) for p in pats)]
            if hits:
                o = out[fid]
                o['sessions'] += 1
                o['lines'] += len(hits)
                o['hits'] += [{'session': r['key'], 'file': f, 'line': l.strip()[:120]} for f, l in hits[:3]]
    for o in out.values():
        o['hits'] = o['hits'][:10]
    return {'facts': out, 'stale_lines': sum(o['lines'] for o in out.values()), 'stale_sessions': sum(o['sessions'] for o in out.values())}


def ramp_up(run, first=3):
    """Joiners and handover recipients: their first sessions' cost, turns and tool calls as a ratio of the median of
    steady teammates on the same days (1.0 = as efficient as the team), plus their probe scores."""
    joiners = {a['id'] for a in run.scenario['roster'] if a.get('joins', 1) > 1} | {h['to'] for h in run.events.get('handovers', [])}
    sess = _work_sessions(run)
    by_day = defaultdict(list)
    for r in sess:
        by_day[r['key'].split('/')[0]].append(r)
    probes_dir = run.dir / 'probes'
    probe_rows = [read_json(p) or {} for p in sorted(probes_dir.glob('*.json'))] if probes_dir.exists() else []
    out = {}
    for j in sorted(joiners):
        mine = [r for r in sess if r['agent'] == j][:first]
        ratios = defaultdict(list)
        for r in mine:
            peers = [x for x in by_day[r['key'].split('/')[0]] if x['agent'] not in joiners]
            for f in ('cost_usd', 'turns', 'tool_calls'):
                vals = [x.get(f) for x in peers if isinstance(x.get(f), (int, float))]
                if vals and statistics.median(vals) and isinstance(r.get(f), (int, float)):
                    ratios[f].append(r[f] / statistics.median(vals))
        out[j] = {'sessions': [r['key'] for r in mine], **{f'{f}_ratio': round(statistics.mean(v), 2) for f, v in ratios.items() if v},
                  'probe_scores': {p['id']: p.get('score') for p in probe_rows if p.get('agent') == j}}
    cost = [v['cost_usd_ratio'] for v in out.values() if 'cost_usd_ratio' in v]
    return {'joiners': out, 'mean_cost_ratio': round(statistics.mean(cost), 2) if cost else None}


def live_scenario(run, name):
    """Analysis-only definitions added after a run was frozen (e.g. mistakes.json) come from the live scenario folder."""
    from .common import SCENARIOS
    return read_json(SCENARIOS / run.manifest.get('scenario', '') / name)


def _shell_calls(path):
    """(tool name, command text) for every shell tool call in a transcript."""
    out = []
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        msg = ev.get('message') if isinstance(ev, dict) else None
        content = msg.get('content') if isinstance(msg, dict) else None
        for c in content if isinstance(content, list) else []:
            if isinstance(c, dict) and c.get('type') == 'tool_use' and isinstance(c.get('input'), dict):
                out.append((c.get('name'), str(c['input'].get('command', ''))))
    return out


def mistake_metrics(run):
    """Per planted mistake: how often each agent made it before and after its own store first held a note about it."""
    spec = read_json(run.scenario_dir / run.scenario.get('mistakes', 'mistakes.json')) or live_scenario(run, 'mistakes.json') or {}
    sess = sorted((r for r in run.state()['sessions'].values() if WORK_KEY.match(r['key'])), key=lambda r: r['started'])
    out = {}
    for mk in spec.get('mistakes', []):
        if mk.get('kind') == 'result':
            out[mk['id']] = result_mistake(run, mk, sess)
            continue
        if mk.get('kind') == 'lint':
            out[mk['id']] = lint_mistake(run, mk)
            continue
        pat, note_pat = re.compile(mk['pattern']), re.compile(mk['note_pattern'])
        captured = {}
        for store in run.stores.glob('*'):
            times = [str(n.get('created')) for n in store_notes(store) if note_pat.search(text_of(n))]
            if times:
                captured[store.name] = min(times)
        per = defaultdict(lambda: {'before': 0, 'after': 0})
        for r in sess:
            t = run.transcripts / f"{r['key']}.jsonl"
            if not t.exists():
                continue
            n = sum(1 for tool, cmd in _shell_calls(t) if (not mk.get('tool') or tool == mk['tool']) and pat.search(cmd))
            if n:
                cap = captured.get(r['agent'])
                per[r['agent']]['after' if cap and r['started'] >= cap else 'before'] += n
        out[mk['id']] = {'desc': mk['desc'], 'captured_by': captured, 'per_agent': dict(per),
                         'repeats_after_capture': sum(v['after'] for v in per.values()),
                         'total': sum(v['before'] + v['after'] for v in per.values())}
    return out


def pointer_coverage(run):
    """Decision documents in the final repo whose author's store has a note naming the document."""
    globs = run.scenario.get('decision_docs') or (live_scenario(run, 'scenario.json') or {}).get('decision_docs') or []
    docs = sorted({p for g in globs for p in run.integration.glob(g) if p.is_file()})
    from .gitops import git
    rows = []
    for d in docs:
        rel = d.relative_to(run.integration).as_posix()
        email = git(run.integration, 'log', '--diff-filter=A', '--format=%ae', '-1', '--', rel, check=False).stdout.strip()
        author = email.split('@')[0] if email else None
        key = d.stem.lower()
        found = bool(author) and (run.stores / author).exists() and any(
            key in text_of(n) or rel.lower() in text_of(n) for n in store_notes(run.stores / author) if is_active(n))
        rows.append({'doc': rel, 'author': author, 'pointer': found})
    return {'docs': len(rows), 'with_pointer': sum(r['pointer'] for r in rows),
            'coverage': round(sum(r['pointer'] for r in rows) / len(rows), 3) if rows else None, 'rows': rows}


def hook_latency(run):
    by = defaultdict(list)
    for store in run.stores.glob('*'):
        if store.name.startswith('_'):
            continue
        for p in (store / 'logs').glob('*.jsonl'):
            for r in read_jsonl(p):
                if r.get('kind') == 'hook' and isinstance(r.get('ms'), (int, float)):
                    by[r.get('event')].append(r['ms'])
    return {e: {'n': len(v), 'p50': pct(v, .5), 'p95': pct(v, .95)} for e, v in sorted(by.items())}


# ---------- end-of-sprint review ----------
def row_kind(row):
    kinds = row.get('kinds') or []
    return kinds[0] if kinds else row.get('kind') or '?'


def find_note(notes, ref):
    """The store note a worklist ref points at (the ref ends in the note id or an id prefix)."""
    tail = str(ref or '').split(':')[-1]
    return next((n for n in notes if tail and str(n.get('id', '')).startswith(tail)), None) if tail else None


def judge_row(row, notes, facts):
    """True: the flag is right, False: wrong, None: the ground truth does not say. Judged against the note as it is in
    the store now (the title and type on the row when the note is gone). `facts` is [(id, current, stale)] regexes."""
    def view(ref, title, ntype):
        n = find_note(notes, ref)
        return ((str(n.get('title', '')) + '\n' + n['_body']).lower() if n else str(title or '').lower()), (n.get('type') if n else ntype)

    def hits(txt, res):
        return any(r.search(txt) for r in res)

    kind = row_kind(row)
    txt, ntype = view(row.get('ref'), row.get('title'), row.get('type'))
    if kind in ('stale', 'due'):
        if ntype == 'status':
            return True
        if any(hits(txt, s) and not hits(txt, c) for _, c, s in facts):
            return True
        return False if any(hits(txt, c) for _, c, _ in facts) else None
    if kind == 'duplicate':
        pair = row.get('pair') or {}
        ptxt, _ = view(pair.get('ref'), pair.get('title'), None)
        mine = {fid for fid, c, s in facts if hits(txt, c + s)}
        if not mine:
            return None
        return any(hits(ptxt, c + s) for fid, c, s in facts if fid in mine)
    if kind in ('warned', 'noisy'):   # wrong only when the flagged note holds a current fact; other flag reasons are not in the ground truth
        if any(re.search(p, txt) for p in NOISE):
            return True
        return False if any(hits(txt, c) for _, c, _ in facts) else None
    return None


def review_metrics(run):
    """Precision of the end-of-sprint review worklists, from reviews.jsonl. None when the run took no reviews."""
    path = run.dir / 'reviews.jsonl'
    if not path.exists():
        return None
    entries = read_jsonl(path)
    facts = [(fid, [re.compile(p, re.I) for p in f.get('patterns', {}).get('current', [])],
              [re.compile(p, re.I) for p in f.get('patterns', {}).get('stale', [])]) for fid, f in run.truth.get('facts', {}).items()]
    notes = {}
    by_kind, per_sprint, applied = {}, {}, 0
    for e in entries:
        applied += len(e.get('applied') or [])
        counts = per_sprint.setdefault(str(e.get('sprint')), {})
        worklist = e.get('counts') or dict(Counter(row_kind(r) for r in e.get('items') or []))
        for k, v in worklist.items():
            counts[k] = counts.get(k, 0) + (v or 0)
        agent_notes = notes.setdefault(e.get('agent'), store_notes(run.stores / str(e.get('agent'))))
        for row in e.get('items') or []:
            k = by_kind.setdefault(row_kind(row), {'rows': 0, 'judged': 0, 'real': 0})
            k['rows'] += 1
            verdict = judge_row(row, agent_notes, facts)
            if verdict is not None:
                k['judged'] += 1
                k['real'] += bool(verdict)
    judged, real = sum(k['judged'] for k in by_kind.values()), sum(k['real'] for k in by_kind.values())
    return {'worklist_precision': round(real / judged, 3) if judged else None, 'judged': judged,
            'unjudged': sum(k['rows'] for k in by_kind.values()) - judged, 'by_kind': by_kind,
            'review_rows': per_sprint, 'plans_applied': applied}


# ---------- store readout (schema 4) ----------
def _store_logs(store):
    return [r for p in sorted(Path(store, 'logs').glob('*.jsonl')) for r in read_jsonl(p)]


def fix_followthrough(run):
    """Sessions that got a Stop reminder of kind `fix` (hook row, detail.reason `reminded:fix`; needs debug logging) and
    whether a successful `capture` command in the same session came after it. From the stores' logs."""
    reminded = followed = 0
    for store in sorted(run.stores.glob('*')):
        if store.name.startswith('_'):
            continue
        logs = _store_logs(store)
        first = {}
        for r in logs:
            if r.get('kind') == 'hook' and r.get('event') == 'stop' and (r.get('detail') or {}).get('reason') == 'reminded:fix':
                first.setdefault(r.get('session'), r.get('ts') or '')
        captures = defaultdict(list)
        for r in logs:
            if r.get('kind') == 'command' and r.get('event') == 'capture' and r.get('exit_code') in (0, None):
                captures[r.get('session')].append(r.get('ts') or '')
        reminded += len(first)
        followed += sum(1 for s, ts in first.items() if any(c > ts for c in captures.get(s, [])))
    return {'reminded_sessions': reminded, 'followed': followed, 'rate': round(followed / reminded, 3) if reminded else None}


def call_operator_denies(run):
    """Pre-tool-use hook rows whose decision is `deny:call-operator` (a leading & in a Bash command)."""
    return sum(1 for store in run.stores.glob('*') if not store.name.startswith('_')
               for r in _store_logs(store) if r.get('kind') == 'hook' and (r.get('detail') or {}).get('decision') == 'deny:call-operator')


def readout_metrics(run):
    """Schema 4 metrics from stores-readout.json (engine.readout) and the stores' logs. Everything is None or empty when
    the run has no readout (older runs, arms without Living Memory)."""
    out = {'capture_coverage': None, 'reminders_by_kind': {}, 'actors': {}, 'auto_resolved': None, 'due_at_quiz': None,
           'fix_reminder_followthrough': fix_followthrough(run), 'call_operator_denies': call_operator_denies(run)}
    readout = read_json(run.dir / 'stores-readout.json') or {}
    stores_ = readout.get('stores')
    if not stores_:
        return out
    latest = {}   # per-sprint stats snapshots (runs with a simulated calendar): the last good one per store and sprint
    for r in read_jsonl(run.dir / 'stats.jsonl'):
        if isinstance(r.get('stats'), dict):
            latest[(r.get('agent'), r.get('sprint'))] = r['stats']
    sprint_rows = defaultdict(list)
    for (agent, _), snap in latest.items():
        sprint_rows[agent].append(snap)
    out['recap_days_needed'], out['recap_truncated'] = readout.get('recap_days_needed'), readout.get('recap_truncated')
    cov, reminders, actors, auto, due = {}, Counter(), Counter(), 0, {}
    for aid, s in stores_.items():
        if sprint_rows.get(aid):   # sum the per-sprint windows; the end-of-run stats only sees the last 30 days
            snaps = sprint_rows[aid]
            mut = sum(((x.get('capture_coverage') or {}).get('mutating') or 0) for x in snaps)
            cvd = sum(((x.get('capture_coverage') or {}).get('covered') or 0) for x in snaps)
            cov[aid] = {'days': sum((x.get('capture_coverage') or {}).get('days') or 0 for x in snaps), 'mutating': mut, 'covered': cvd,
                        'ratio': round(cvd / mut, 2) if mut else None, 'source': 'sprints'}
            for x in snaps:
                reminders.update({k: v for k, v in (x.get('reminders') or {}).items() if isinstance(v, (int, float))})
        else:
            c = ((s.get('stats') or {}).get('capture_coverage')) or {}
            cov[aid] = {k: c.get(k) for k in ('days', 'mutating', 'covered', 'ratio')} if c else None
            reminders.update({k: v for k, v in ((s.get('stats') or {}).get('reminders') or {}).items() if isinstance(v, (int, float))})
        rows = ((s.get('log') or {}).get('rows')) or []
        actors.update(str(r.get('actor') or '?') for r in rows)
        auto += sum(1 for r in rows if r.get('actor') == 'auto_resolve' and r.get('event') == 'resolved')
        rq = s.get('review_at_quiz')
        if rq and 'error' not in rq:
            due[aid] = rq.get('total') if rq.get('total') is not None else len(rq.get('items') or [])
    ratios = [c['ratio'] for c in cov.values() if c and isinstance(c.get('ratio'), (int, float))]
    out.update(capture_coverage={'per_store': cov, 'mean_ratio': round(statistics.mean(ratios), 3) if ratios else None},
               reminders_by_kind=dict(reminders), actors=dict(actors), auto_resolved=auto,
               due_at_quiz={'per_store': due, 'total': sum(due.values())} if due else None)
    return out


# ---------- block A/B (instruction block old vs new) ----------
MALFORMED = re.compile(r'usage:|unrecognized arguments|invalid choice|the following arguments are required|expected one argument|error: argument', re.I)
# Each `alm --json` call prints one compact JSON object starting with "ok", and a successful write names itself in
# "status". These results, not the shell command, decide what ran: agents wrap the CLI in variables, arrays and functions
# the command parser cannot always follow, and a compound command (`... ; echo`, `| head`) can end with exit code 0
# although a call in it failed.
LM_RESULT = re.compile(r'\{"ok"\s*:\s*(true|false)')
LM_STATUS = re.compile(r'"status"\s*:\s*"([\w-]+)"')
LM_ERROR_MESSAGE = re.compile(r'"message"\s*:\s*"([^"]{0,100})')
LM_COMMAND = re.compile(r'living_memory\.py|\balm(?:\.exe)?\s')
LM_CRASH = re.compile(r"Traceback \(most recent call last\)|can't open file|syntax error near|command not found")
WRITE_STATUS = {'created': 'capture', 'update': 'update', 'supersede': 'supersede', 'dismissed': 'capture-finalize',
                'nothing_durable': 'capture-finalize'}
HELP_TOPIC = re.compile(r'\bhelp\s+([A-Za-z][\w-]*)')
CAPTURING = ('capture', 'capture-finalize', 'update', 'supersede')


def _result_text(content):
    if isinstance(content, list):
        return '\n'.join(str(c.get('text', '')) if isinstance(c, dict) else str(c) for c in content)
    return str(content or '')


def _warnings_in(text):
    """The `quality_warnings` list in a capture or update result (the JSON an agent gets), else []."""
    m = re.search(r'"quality_warnings"\s*:\s*(\[.*?\])', text, re.S)
    if not m:
        return []
    try:
        return [str(w) for w in json.loads(m.group(1))]
    except ValueError:
        return []


def _lm_results(text):
    """The Living Memory JSON results in a tool result's text, in order, as (ok, top-level status or None, its text)."""
    found = list(LM_RESULT.finditer(text))
    out = []
    for k, m in enumerate(found):
        own = text[m.start():found[k + 1].start() if k + 1 < len(found) else len(text)]
        try:
            status = json.JSONDecoder().raw_decode(own)[0].get('status')
        except ValueError:   # cut off (`| head -c 600`): the first status in it is the best guess
            status = (LM_STATUS.search(own) or [None, None])[1]
        out.append((m[1] == 'true', status, own))
    return out


def _error_label(text):
    m = LM_ERROR_MESSAGE.search(text)
    if m:
        return m[1].split(':')[0].split(',')[0]
    return text.strip().splitlines()[0][:100] if text.strip() else ''


def block_session(path):
    """Living Memory calls of one session from its transcript, each with its result: captures made, the quality
    warnings their results carried, failed calls (malformed when the result shows a usage error) and `help` calls.
    A shell command can run several calls: each JSON result in its output is one call, a successful write is named by
    its status, and anything else by the k-th subcommand the command parser found. A call without a JSON result of its
    own has no known outcome and is left out (the session ended first, or `| tail` cut the result off), unless the
    command failed or its output shows a crash: that is one failed call."""
    uses, results = {}, {}
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        msg = ev.get('message') if isinstance(ev, dict) else None
        content = msg.get('content') if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get('type') == 'tool_use':
                cmd = (c.get('input') or {}).get('command')
                subs = lm_calls(cmd)
                if subs or (isinstance(cmd, str) and LM_COMMAND.search(cmd)):
                    uses[c.get('id')] = (cmd, subs)
            elif c.get('type') == 'tool_result' and c.get('tool_use_id') in uses:
                results[c['tool_use_id']] = (bool(c.get('is_error')), _result_text(c.get('content')))
    out = {'captures': 0, 'writes': 0, 'warned_results': 0, 'warnings': [], 'errors': [], 'malformed': 0, 'help': [], 'calls': 0}
    for i, (cmd, subs) in uses.items():
        if i not in results:
            continue
        is_error, text = results[i]
        parsed, topics = _lm_results(text), HELP_TOPIC.findall(cmd)
        for k in range(max(len(subs), len(parsed))):
            sub = subs[k] if k < len(subs) else 'other'
            if k < len(parsed):
                ok, status, own = parsed[k]
                if ok:   # a write names itself; a result that is not a write cannot be one, whatever the parser paired
                    sub = WRITE_STATUS.get(status) or ('other' if sub in CAPTURING else sub)
            elif not parsed and subs and k == 0 and (is_error or LM_CRASH.search(text)):   # failed before printing JSON
                ok, own = False, text
            else:   # no result of its own (cut off by `| tail`, filtered, never ran): its outcome is unknown
                continue
            out['calls'] += 1
            if sub == 'help':
                out['help'].append(topics.pop(0) if topics else '')
            if not ok:
                out['errors'].append(_error_label(own))
                out['malformed'] += bool(MALFORMED.search(own))
                continue
            if sub == 'capture':
                out['captures'] += 1
            if sub in CAPTURING:
                out['writes'] += 1
                w = _warnings_in(own)
                out['warned_results'] += bool(w)
                out['warnings'] += w
    return out


def hook_denies(run):
    """Pre-tool-use rows the hooks refused, by decision, from the stores' logs."""
    return dict(Counter(str((r.get('detail') or {}).get('decision')) for store in run.stores.glob('*') if not store.name.startswith('_')
                        for r in _store_logs(store)
                        if r.get('kind') == 'hook' and str((r.get('detail') or {}).get('decision') or '').startswith('deny')))


def store_captures(run):
    """Successful captures per session key, from the stores' own command logs. Exact where the transcript is not: an
    agent that pipes `alm` through `| tail` never sees the start of the result, so its transcript cannot show the write."""
    keys = {r['session_hash']: r['key'] for r in run.state()['sessions'].values() if r.get('session_hash')}
    return Counter(keys.get(r.get('session')) for store in run.stores.glob('*') if not store.name.startswith('_')
                   for r in _store_logs(store)
                   if r.get('kind') == 'command' and r.get('event') == 'capture' and r.get('exit_code') == 0)


def briefs(notes_by_store):
    return {agent: [{'title': n.get('title'), 'chars': len(n['_body']), 'global': n.get('domain') == '_global', 'text': n['_body'].strip()[:2000]}
                    for n in notes if n.get('type') == 'brief' and is_active(n)]
            for agent, notes in notes_by_store.items()}


def block_ab(run, quiz=None, readout=None):
    """Metrics for comparing two runs that differ in the managed instruction block, computed offline from transcripts
    and stores. `headline` holds the scalars `compare-arms` and `compare` read; the rest is detail for `sim.py ab`."""
    path = lambda r: run.transcripts / f"{r['key']}.jsonl"   # noqa: E731
    sessions_ = [r for r in run.state()['sessions'].values() if path(r).exists()]
    every = {r['key']: block_session(path(r)) for r in sessions_}
    per = {k: v for k, v in every.items() if WORK_KEY.match(k) and not k.endswith('.resolve')}
    stored = store_captures(run)
    for k, s in per.items():   # captures: what the store recorded; warnings and failures: what the agent saw
        s['captures'] = stored.get(k, 0)
    n = len(per)
    caps = sum(s['captures'] for s in per.values())
    writes = sum(s['writes'] for s in per.values())
    warned = sum(s['warned_results'] for s in per.values())
    warns = Counter(re.sub(r'\s+', ' ', w)[:90] for s in per.values() for w in s['warnings'])
    errors = Counter(e for s in every.values() for e in s['errors'])
    topics = Counter(t or '(none)' for s in every.values() for t in s['help'])
    denies = hook_denies(run)
    br = briefs({p.name: store_notes(p) for p in sorted(run.stores.glob('*')) if not p.name.startswith('_')})
    project = [b for v in br.values() for b in v if not b['global']]
    q = quiz or {}
    return {
        'headline': {
            'work_sessions': n, 'captures': caps, 'captures_per_work_session': round(caps / n, 2) if n else None,
            'sessions_with_capture': sum(1 for s in per.values() if s['captures']),
            'capture_coverage': ((readout or {}).get('capture_coverage') or {}).get('mean_ratio'),
            'warned_results': warned, 'warned_share': round(warned / writes, 3) if writes else None, 'warnings': sum(warns.values()),
            'lm_call_errors': sum(len(s['errors']) for s in every.values()),
            'malformed_calls': sum(s['malformed'] for s in every.values()),
            'hook_denies': sum(denies.values()),
            'help_calls': sum(len(s['help']) for s in every.values()),
            'sessions_using_help': sum(1 for s in every.values() if s['help']),
            'project_briefs': len(project), 'brief_chars_mean': round(statistics.mean(b['chars'] for b in project)) if project else None,
            'quiz_score_should_know': q.get('score_should_know'), 'quiz_score_all': q.get('score_all')},
        'warning_texts': dict(warns.most_common(15)), 'error_texts': dict(errors.most_common(10)),
        'help_topics': dict(topics), 'hook_denies_by_decision': denies, 'briefs': br,
        'by_session': {k: {**{x: s[x] for x in ('captures', 'writes', 'warned_results', 'malformed', 'calls')}, 'help': len(s['help']), 'errors': len(s['errors'])}
                       for k, s in per.items()}}


def compare_ab(a, b):
    """Text side-by-side of two runs' `block_ab` metrics (an old-block run and a new-block run), with the brief contents."""
    ha, hb = (((m.get('block_ab') or {}).get('headline')) or {} for m in (a, b))
    keys = list(dict.fromkeys(list(ha) + list(hb)))
    width = max((len(k) for k in keys), default=10)
    out = [f"{'metric'.ljust(width)}  {a['run'][-28:]:>28}  {b['run'][-28:]:>28}"]
    out += [f"{k.ljust(width)}  {str(ha.get(k)):>28}  {str(hb.get(k)):>28}{'  *' if ha.get(k) != hb.get(k) else ''}" for k in keys]
    for label, key in (('warnings', 'warning_texts'), ('failed LM call results', 'error_texts'), ('help topics', 'help_topics'),
                       ('hook denies', 'hook_denies_by_decision')):
        for name, m in (('A', a), ('B', b)):
            d = (m.get('block_ab') or {}).get(key) or {}
            out.append(f"{label} {name}: " + ('; '.join(f'{k} x{v}' for k, v in d.items()) or 'none'))
    for name, m in (('A', a), ('B', b)):
        out.append(f'briefs {name}:')
        for agent, items in sorted(((m.get('block_ab') or {}).get('briefs') or {}).items()):
            for br in items:
                out.append(f"  {agent} {'global' if br['global'] else 'project'} {br['title']!r} ({br['chars']} chars): " + ' '.join(br['text'].split())[:300])
    return '\n'.join(out)


# ---------- run ----------
def analyze(run):
    state = run.state()
    sess = list(state['sessions'].values())
    per_store = {p.name: store_metrics(p, run.truth) for p in sorted(run.stores.glob('*')) if not p.name.startswith('_')}
    for name, m in per_store.items():
        m['claude_automemory_files'] = automemory_files(run.ws / name, lmsource.home_of(run))
    end = read_json(run.dir / END_SNAPSHOT) or {}
    for name, snap in end.items():   # content as of the end of the work; what the quizzes added is kept beside it
        if name in per_store:
            per_store[name]['after_quizzes'] = {k: per_store[name].get(k) for k in END_KEYS}
            per_store[name].update(snap)
    per_session = {}
    for r in sess:
        t = run.transcripts / f"{r['key']}.jsonl"
        if t.exists():
            per_session[r['key']] = {**{k: r.get(k) for k in ('agent', 'model', 'subtype', 'cost_usd', 'seconds', 'turns', 'tool_calls', 'lm_calls')},
                                     **transcript_metrics(t, run.dir, r['agent'])}
    fact_cov = {}
    for fid, f in run.truth.get('facts', {}).items():
        holders = [a for a, m in per_store.items() if m['facts'].get(fid, {}).get('current')]
        stale = [a for a, m in per_store.items() if m['facts'].get(fid, {}).get('stale_active')]
        should = f.get('should_know', [])
        fact_cov[fid] = {'stores_with_fact': holders, 'stores_with_stale_only': stale,
                         'should_know_coverage': round(len(set(holders) & set(should)) / len(should), 3) if should else None,
                         'duplication': len(holders)}
    tiers = defaultdict(lambda: {'sessions': 0, 'cost': 0.0, 'lm_calls': 0, 'turns': 0})
    for r in sess:
        t = tiers[r.get('tier') or '?']
        t['sessions'] += 1; t['cost'] = round(t['cost'] + (r.get('cost_usd') or 0), 4)
        t['lm_calls'] += r.get('lm_calls') or 0; t['turns'] += r.get('turns') or 0
    ci = read_jsonl(run.dir / 'ci.jsonl')
    merges = read_jsonl(run.dir / 'merges.jsonl')
    work = [r for r in sess if WORK_KEY.match(r['key'])]
    metrics = {
        'schema': SCHEMA, 'run': run.dir.name, 'manifest': run.manifest,
        'totals': {'sessions': len(sess), 'work_sessions': len(work), 'cost_usd': run.spent(), **cost_split(run),
                   'failed_sessions': sum(1 for r in sess if r.get('subtype') != 'success'),
                   'timeouts': sum(1 for r in sess if r.get('timed_out')),
                   'lm_calls': sum(r.get('lm_calls') or 0 for r in sess),
                   'lm_calls_per_work_session': round(sum(r.get('lm_calls') or 0 for r in work) / len(work), 2) if work else None,
                   'tool_calls': sum(r.get('tool_calls') or 0 for r in sess),
                   'notes_active': sum(m['notes_active'] for m in per_store.values()),
                   'maps': sum(m['maps'] for m in per_store.values()),
                   'noise_notes': sum(m['noise_notes'] for m in per_store.values()),
                   'status_snapshots': sum(m.get('status_snapshots', 0) for m in per_store.values()),
                   'lm_cli_errors': sum(m['commands']['errors'] for m in per_store.values()),
                   'leaks': sum(len(s['leaks']) for s in per_session.values())},
        'by_tier': dict(tiers), 'stores': per_store, 'facts': fact_cov, 'sessions': per_session,
        'ci': {'runs': len(ci), 'green': sum(1 for r in ci if r.get('ok')), 'last_ok': ci[-1].get('ok') if ci else None,
               'history': [{'label': r['label'], 'ok': r.get('ok')} for r in ci]},
        'merges': {'attempts': len(merges), 'failed_final': sum(1 for r in merges if not r.get('ok') and r.get('attempt') == 2),
                   'conflicts_first_try': sum(1 for r in merges if not r.get('ok') and r.get('attempt') == 1),
                   'files_swept_uncommitted': sum(r.get('swept') or 0 for r in merges)},
        'handovers': read_jsonl(run.dir / 'handovers.jsonl'), 'app': app_checks(run),
        'options': run.options, 'quiz': quiz_metrics(run, per_store), 'quiz_repo': quiz_metrics(run, per_store, 'repo'), 'quiz_kb': quiz_metrics(run, per_store, 'kb'),
        'quiz_repo_reads': quiz_repo_reads(run), 'quiz_other_shell': quiz_other_shell(run),
        'mistakes': mistake_metrics(run), 'pointers': pointer_coverage(run), 'hook_latency': hook_latency(run),
        'probes': probe_metrics(run), 'efficiency': efficiency(run),
        'rediscovery': rediscovery(run), 'repeat_failures': repeat_failures(run), 'stale_actions': stale_actions(run),
        'ramp_up': ramp_up(run), 'app_history': app_check_history(run),
        'grader_audit': {k: v for k, v in (read_json(run.dir / 'quiz' / 'grader-audit.json') or {}).items() if k != 'rows'} or None,
        'currency': {'updates': sum(s['usage'].get('update', 0) for s in per_store.values()),
                     'supersedes': sum(s['by_status'].get('superseded', 0) for s in per_store.values())}}
    review = review_metrics(run)
    if review is not None:
        metrics['review'] = review
    metrics['readout'] = readout_metrics(run)
    metrics['block_ab'] = block_ab(run, metrics.get('quiz'), metrics['readout'])
    write_json(run.dir / 'metrics.json', metrics)
    return metrics


def summary(m):
    t, q, qr = m['totals'], m.get('quiz') or {}, m.get('quiz_repo') or {}
    opts = m.get('options') or {}
    lines = [f"run {m['run']} (memory {opts.get('memory', 'on')}, semantic {opts.get('semantic', False)}): {t['sessions']} sessions, "
             f"${t['cost_usd']} (work ${t.get('work_cost_usd')}, colleagues ${t.get('chat_cost_usd')}, harness ${t.get('harness_cost_usd')}, "
             f"{t.get('cost_unknown_sessions')} without a cost), failed {t['failed_sessions']}, timeouts {t['timeouts']}",
             f"memory: {t['notes_active']} active notes, {t['maps']} maps, {t['noise_notes']} noise-like, {t.get('status_snapshots')} status, {t['lm_calls']} LM calls "
             f"({t['lm_calls_per_work_session']}/work session), {t['lm_cli_errors']} CLI errors, blocked-path attempts {t['leaks']}",
             f"currency: {(m.get('currency') or {}).get('updates')} updates, {(m.get('currency') or {}).get('supersedes')} superseded; "
             f"pointers: {(m.get('pointers') or {}).get('with_pointer')}/{(m.get('pointers') or {}).get('docs')} decision docs",
             f"CI: {m['ci']['green']}/{m['ci']['runs']} green, last {'green' if m['ci']['last_ok'] else 'RED'}; merges: "
             f"{m['merges']['conflicts_first_try']} conflicts, {m['merges']['failed_final']} unresolved"]
    rv = m.get('review')
    if rv:
        lines.append(f"review: worklist precision {rv['worklist_precision']} ({rv['judged']} judged, {rv['unjudged']} unjudged), "
                     f"{rv['plans_applied']} plans applied")
    ro = m.get('readout') or {}
    if ro.get('capture_coverage'):
        lines.append(f"readout: capture coverage {ro['capture_coverage']['mean_ratio']}, reminders {ro['reminders_by_kind']}, "
                     f"fix follow-through {ro['fix_reminder_followthrough']['rate']}, auto-resolved {ro['auto_resolved']}, "
                     f"worklist at quiz {(ro['due_at_quiz'] or {}).get('total')}, call-operator denies {ro['call_operator_denies']}")
    if q:
        lines.append(f"quiz (memory only): all {q['score_all']}, should-know {q['score_should_know']}, failures {q['failure_kinds_should_know']}")
    if qr:
        lines.append(f"quiz (with repo): all {qr['score_all']}, should-know {qr['score_should_know']}")
    qk = m.get('quiz_kb')
    if qk:
        lines.append(f"quiz (fresh agent, knowledge base only): all {qk['score_all']}")
    for mid, mk in (m.get('mistakes') or {}).items():
        if mk.get('kind') == 'result':
            lines.append(f"mistake {mid} ({mk['desc'][:50]}): {mk['total']} hits by {mk['agents_hit']} agents, "
                         f"{mk['repeat_sessions']} repeat sessions after the first")
        elif mk.get('kind') == 'lint':
            lines.append(f"mistake {mid} ({mk['desc'][:50]}): {mk['total']} violations by {mk['agents_hit']} authors, "
                         f"{mk['repeats']} after the CI bot had told them")
        else:
            lines.append(f"mistake {mid}: {mk['total']} times, {mk['repeats_after_capture']} after the agent's own note "
                         f"(notes in {sorted(mk['captured_by'])})")
    pr = m.get('probes') or {}
    if pr.get('probes'):
        lines.append(f"probes: mean {pr['mean_score']} over {pr['probes']} ({pr['by_probe']}); per probe {pr['mean_turns']} turns, "
                     f"{pr['mean_tool_calls']} tool calls, {pr['mean_seconds']}s; ${pr['cost_usd']} total")
    for k, e in (m.get('efficiency') or {}).items():
        if k != 'chat':
            lines.append(f"efficiency {k}: {e['sessions']} sessions, ${e['cost_usd']}/session, {e['turns']} turns, "
                         f"{e['tool_calls']} tool calls, {e['seconds']}s")
    if (m.get('efficiency') or {}).get('chat', {}).get('messages'):
        lines.append(f"stakeholder chat: {m['efficiency']['chat']['messages']} messages, ${m['efficiency']['chat']['cost_usd']}")
    rd, rf, sa, ru, ah = (m.get(k) or {} for k in ('rediscovery', 'repeat_failures', 'stale_actions', 'ramp_up', 'app_history'))
    if rd:
        lines.append(f"rediscovery: {rd['mean_rereads']} re-reads per work session (share {rd['reread_share']}), "
                     f"{rd['mean_calls_before_change']} tool calls before the first change")
    if rf:
        lines.append(f"repeated failures: {rf['own_repeat_sessions']} own repeats, {rf['team_repeat_sessions']} team repeats "
                     f"over {rf['signatures']} error signatures; failed Living Memory calls repeated "
                     f"{rf.get('lm_own_repeat_sessions')} own, {rf.get('lm_team_repeat_sessions')} team")
    if sa:
        lines.append(f"stale actions: {sa['stale_lines']} added code lines in {sa['stale_sessions']} sessions "
                     f"({ {k: v['stale_from'] for k, v in sa['facts'].items()} })")
    if ru.get('joiners'):
        lines.append(f"ramp-up: joiner cost ratio {ru['mean_cost_ratio']} ("
                     + ', '.join(f"{j} {v.get('cost_usd_ratio')}" for j, v in ru['joiners'].items()) + ')')
    if ah:
        lines.append(f"app-check regressions: {ah['regression_count']} over {ah['points']} main commits")
    if m.get('grader_audit'):
        ga = m['grader_audit']
        lines.append(f"grader audit: agreement {ga['agreement']}, false accept {ga['false_accept_rate']}, false reject {ga['false_reject_rate']}")
    for fid, f in m['facts'].items():
        lines.append(f"  {fid}: in {f['duplication']} stores, should-know coverage {f['should_know_coverage']}, "
                     f"stale-only in {f['stores_with_stale_only']}, quiz {(q.get('by_fact_should_know') or {}).get(fid)}, "
                     f"with repo {(qr.get('by_fact_should_know') or {}).get(fid)}")
    if m.get('app'):
        lines.append('app: ' + ', '.join(f"{c['fact']}:{'ok' if c['pass'] else 'MISSING'}" for c in m['app']['checks']))
    return '\n'.join(lines)


def _flat(d, prefix=''):
    out = {}
    for k, v in (d or {}).items():
        key = f'{prefix}{k}'
        if isinstance(v, dict):
            out.update(_flat(v, key + '.'))
        elif isinstance(v, (int, float, bool)) or v is None:
            out[key] = v
    return out


def compare(a, b):
    """Side-by-side scalar metrics that are comparable across runs."""
    keep = ('totals.', 'ci.', 'merges.', 'quiz.score', 'quiz.by_fact', 'quiz.by_agent', 'quiz.failure', 'by_tier.', 'block_ab.headline.')
    fa = {k: v for k, v in _flat(a).items() if k.startswith(keep)}
    fb = {k: v for k, v in _flat(b).items() if k.startswith(keep)}
    for fid in set(a.get('facts', {})) | set(b.get('facts', {})):
        for side, src, dst in (('a', a, fa), ('b', b, fb)):
            f = src.get('facts', {}).get(fid, {})
            dst[f'facts.{fid}.coverage'] = f.get('should_know_coverage')
            dst[f'facts.{fid}.stale_stores'] = len(f.get('stores_with_stale_only', []))
    keys = sorted(set(fa) | set(fb))
    rows = [(k, fa.get(k), fb.get(k)) for k in keys]
    width = max((len(k) for k in keys), default=10)
    out = [f"{'metric'.ljust(width)}  {a['run'][:24]:>24}  {b['run'][:24]:>24}"]
    out += [f"{k.ljust(width)}  {str(x):>24}  {str(y):>24}{'  *' if x != y else ''}" for k, x, y in rows]
    return '\n'.join(out), sum(1 for _, x, y in rows if x != y)


# ---------- arms ----------
ARM_METRICS = (
    ('probe score', lambda m: (m.get('probes') or {}).get('mean_score')),
    ('quiz with repo, should-know', lambda m: (m.get('quiz_repo') or {}).get('score_should_know')),
    ('quiz memory-only, should-know', lambda m: (m.get('quiz') or {}).get('score_should_know')),
    ('quiz fresh agent, knowledge base', lambda m: (m.get('quiz_kb') or {}).get('score_all')),
    ('probe turns', lambda m: (m.get('probes') or {}).get('mean_turns')),
    ('probe tool calls', lambda m: (m.get('probes') or {}).get('mean_tool_calls')),
    ('probe $', lambda m: (m.get('probes') or {}).get('cost_usd')),
    ('quiz-repo $/session', lambda m: ((m.get('efficiency') or {}).get('quiz_repo') or {}).get('cost_usd')),
    ('quiz-repo tool calls', lambda m: ((m.get('efficiency') or {}).get('quiz_repo') or {}).get('tool_calls')),
    ('work $/session', lambda m: ((m.get('efficiency') or {}).get('work') or {}).get('cost_usd')),
    ('work turns/session', lambda m: ((m.get('efficiency') or {}).get('work') or {}).get('turns')),
    ('work cache-read tok/session', lambda m: (((m.get('efficiency') or {}).get('work') or {}).get('tokens') or {}).get('cache_read_input_tokens')),
    ('work output tok/session', lambda m: (((m.get('efficiency') or {}).get('work') or {}).get('tokens') or {}).get('output_tokens')),
    ('work total $', lambda m: (m.get('totals') or {}).get('work_cost_usd')),
    ('harness $ (quizzes, grading)', lambda m: (m.get('totals') or {}).get('harness_cost_usd')),
    ('run total $', lambda m: (m.get('totals') or {}).get('cost_usd')),
    ('re-reads/work session', lambda m: (m.get('rediscovery') or {}).get('mean_rereads')),
    ('re-read share', lambda m: (m.get('rediscovery') or {}).get('reread_share')),
    ('calls before first change', lambda m: (m.get('rediscovery') or {}).get('mean_calls_before_change')),
    ('own repeated failures', lambda m: (m.get('repeat_failures') or {}).get('own_repeat_sessions')),
    ('team repeated failures', lambda m: (m.get('repeat_failures') or {}).get('team_repeat_sessions')),
    ('repeated failed LM calls', lambda m: sum((m.get('repeat_failures') or {}).get(k) or 0
                                               for k in ('lm_own_repeat_sessions', 'lm_team_repeat_sessions'))),
    ('stale code lines', lambda m: (m.get('stale_actions') or {}).get('stale_lines')),
    ('joiner cost ratio', lambda m: (m.get('ramp_up') or {}).get('mean_cost_ratio')),
    ('app-check regressions', lambda m: (m.get('app_history') or {}).get('regression_count')),
    ('CI green share', lambda m: round(m['ci']['green'] / m['ci']['runs'], 3) if (m.get('ci') or {}).get('runs') else None),
    ('commit-policy repeat sessions', lambda m: ((m.get('mistakes') or {}).get('M1') or {}).get('repeat_sessions')),
    ('lint repeats (L1+L2)', lambda m: sum(((m.get('mistakes') or {}).get(k) or {}).get('repeats') or 0 for k in ('M2', 'M3'))),
    ('stale notes (D1)', lambda m: len(((m.get('facts') or {}).get('D1') or {}).get('stores_with_stale_only') or [])),
    ('status snapshot notes', lambda m: (m.get('totals') or {}).get('status_snapshots')),
    ('review worklist precision', lambda m: (m.get('review') or {}).get('worklist_precision')),
    ('review plans applied', lambda m: (m.get('review') or {}).get('plans_applied')),
    ('capture coverage (mean ratio)', lambda m: ((m.get('readout') or {}).get('capture_coverage') or {}).get('mean_ratio')),
    ('reminders (all kinds)', lambda m: sum(((m.get('readout') or {}).get('reminders_by_kind') or {}).values()) if (m.get('readout') or {}).get('capture_coverage') else None),
    ('fix reminder follow-through', lambda m: ((m.get('readout') or {}).get('fix_reminder_followthrough') or {}).get('rate')),
    ('auto-resolved notes', lambda m: (m.get('readout') or {}).get('auto_resolved')),
    ('review worklist at quiz', lambda m: ((m.get('readout') or {}).get('due_at_quiz') or {}).get('total')),
    ('call-operator denies', lambda m: (m.get('readout') or {}).get('call_operator_denies')),
    ('captures/work session', lambda m: ((m.get('block_ab') or {}).get('headline') or {}).get('captures_per_work_session')),
    ('sessions with a capture', lambda m: ((m.get('block_ab') or {}).get('headline') or {}).get('sessions_with_capture')),
    ('results with quality warnings', lambda m: ((m.get('block_ab') or {}).get('headline') or {}).get('warned_results')),
    ('warned share of writes', lambda m: ((m.get('block_ab') or {}).get('headline') or {}).get('warned_share')),
    ('failed LM calls', lambda m: ((m.get('block_ab') or {}).get('headline') or {}).get('lm_call_errors')),
    ('malformed LM calls', lambda m: ((m.get('block_ab') or {}).get('headline') or {}).get('malformed_calls')),
    ('hook denies', lambda m: ((m.get('block_ab') or {}).get('headline') or {}).get('hook_denies')),
    ('alm help calls', lambda m: ((m.get('block_ab') or {}).get('headline') or {}).get('help_calls')),
    ('project briefs', lambda m: ((m.get('block_ab') or {}).get('headline') or {}).get('project_briefs')),
)


def per_probe_means(ms):
    """{probe id: score averaged over the runs (seeds) given}."""
    acc = defaultdict(list)
    for m in ms:
        for pid, s in ((m.get('probes') or {}).get('by_probe') or {}).items():
            if isinstance(s, (int, float)):
                acc[pid].append(s)
    return {pid: statistics.mean(v) for pid, v in acc.items()}


def paired_probe_stats(arms, reps=2000, seed=0):
    """Each arm against the first, probe by probe: mean score difference over the probes both arms ran (each probe's
    score averaged over that arm's seeds), with a bootstrap 95% interval over probes and win/tie/loss counts."""
    names = list(arms)
    if len(names) < 2:
        return []
    ref, out = per_probe_means(arms[names[0]]), []
    for name in names[1:]:
        mine = per_probe_means(arms[name])
        d = [mine[p] - ref[p] for p in sorted(set(ref) & set(mine))]
        if not d:
            continue
        rng = random.Random(seed)
        boots = sorted(statistics.mean(rng.choices(d, k=len(d))) for _ in range(reps))
        out.append({'arm': name, 'ref': names[0], 'n': len(d), 'mean': statistics.mean(d),
                    'sd': statistics.stdev(d) if len(d) > 1 else 0.0,
                    'lo': boots[int(.025 * reps)], 'hi': boots[int(.975 * reps) - 1],
                    'wins': sum(x > 0 for x in d), 'ties': sum(x == 0 for x in d), 'losses': sum(x < 0 for x in d)})
    return out


def paired_probes(arms, reps=2000, seed=0):
    return [f"probe score {s['arm']} - {s['ref']}: {s['mean']:+.3f} (95% CI {s['lo']:+.3f} to {s['hi']:+.3f} over "
            f"{s['n']} probes; wins/ties/losses {s['wins']}/{s['ties']}/{s['losses']})" for s in paired_probe_stats(arms, reps, seed)]


def compare_arms(arms):
    """arms: {name: [metrics dicts]} -> a table of mean +- sd (n) per metric and arm."""
    import statistics as st
    def cell(vals):
        vals = [v for v in vals if isinstance(v, (int, float))]
        if not vals:
            return '-'
        mean = st.mean(vals)
        sd = st.stdev(vals) if len(vals) > 1 else 0.0
        return f"{mean:.3g} ± {sd:.2g} (n={len(vals)})"
    names = list(arms)
    width = max(len(n) for n, _ in ARM_METRICS)
    out = [f"{'metric'.ljust(width)}  " + '  '.join(n.rjust(22) for n in names)]
    for label, fn in ARM_METRICS:
        out.append(f"{label.ljust(width)}  " + '  '.join(cell([fn(m) for m in arms[n]]).rjust(22) for n in names))
    return '\n'.join(out + paired_probes(arms))
