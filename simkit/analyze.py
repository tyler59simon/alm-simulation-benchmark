"""Turn a frozen run folder into metrics.json (fixed schema, so runs compare) plus a short text summary."""
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from .common import config, read_json, read_jsonl, write_json

SCHEMA = 1
LM_SUBCOMMANDS = ('capture-finalize', 'capture', 'search', 'read', 'update', 'supersede', 'confirm', 'check', 'resolve',
                  'reopen', 'open', 'review', 'list', 'stats', 'apply', 'plan', 'undo', 'bind', 'learn', 'timeline',
                  'history', 'links', 'doctor', 'export', 'import-plan', 'archive-plan', 'merge-plan', 'promote-plan')
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


def store_metrics(store, truth):
    notes = store_notes(store)
    active = [n for n in notes if is_active(n)]
    m = {'notes_total': len(notes), 'notes_active': len(active),
         'by_type': dict(Counter(n.get('type') for n in notes)), 'by_status': dict(Counter(n.get('status') for n in notes)),
         'by_domain': dict(Counter(n.get('domain') for n in notes)),
         'maps': sum(1 for n in active if n.get('type') == 'map'),
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
    m['commands'] = {'total': len(cmds), 'errors': sum(1 for r in cmds if r.get('exit') not in (0, None)),
                     'by_event': dict(Counter(r.get('event') for r in cmds)),
                     'error_reasons': dict(Counter(str(r.get('reason') or r.get('error') or '')[:80] for r in cmds if r.get('exit') not in (0, None)))}
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


def automemory_files(ws_path):
    """Claude Code's own auto-memory for the agent's clone (should stay empty where Living Memory applies)."""
    mangled = re.sub(r'[:\\/ ._]', '-', str(ws_path))
    d = Path.home() / '.claude' / 'projects' / mangled / 'memory'
    return len([p for p in d.rglob('*') if p.is_file()]) if d.exists() else 0


END_SNAPSHOT = 'stores-at-end.json'
END_KEYS = ('notes_total', 'notes_active', 'by_type', 'by_status', 'maps', 'active_chars', 'noise_notes', 'facts')


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
                if 'living_memory' in s:
                    cmd = c.get('input', {}).get('command', '')
                    after = cmd.split('living_memory.py', 1)[-1]
                    sub = next((w for w in re.findall(r'[a-z][a-z-]+', after) if w in LM_SUBCOMMANDS), 'other')
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
def app_checks(run):
    spec = read_json(run.scenario_dir / run.scenario.get('app_checks', 'app_checks.json'))
    if not spec:
        return None
    root = run.integration / spec.get('root', '.')
    files = list(root.glob(spec.get('glob', '**/*'))) if root.exists() else []
    corpus = '\n'.join(p.read_text(encoding='utf-8', errors='replace') for p in files if p.is_file() and 'target' not in p.parts)
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
    return {'files': len(files), 'lines': corpus.count('\n'), 'checks': out}


# ---------- quiz ----------
GRADE_SCORE = {'correct': 1.0, 'partial': 0.5}


def quiz_repo_reads(run):
    """Memory-only quiz commands that name the agent's clone, the integration repo or the workspace: a read that the
    deny rules did not catch would let the repo answer for memory."""
    marks = [str(run.ws), str(run.dir / 'integration'), str(run.workspace) if run.workspace_enabled else None]
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
    qs = {q['id']: q for q in run.quiz.get('questions', [])}
    facts = run.truth.get('facts', {})
    matrix, rows = {}, []
    grades_dir = (run.dir / 'quiz' if mode == 'memory' else run.dir / 'quiz' / mode) / 'grades'
    if not grades_dir.exists():
        return None
    for p in sorted(grades_dir.glob('*.json')):
        g = read_json(p, {})
        agent = g.get('agent', p.stem)
        matrix[agent] = {x['id']: x.get('grade') for x in g.get('grades', []) if isinstance(x, dict)}
    for agent, grades in matrix.items():
        for qid, grade in grades.items():
            q = qs.get(qid)
            if not q:
                continue
            f = q['fact']
            should = agent in facts.get(f, {}).get('should_know', [])
            in_store = (per_store.get(agent, {}).get('facts', {}).get(f, {}).get('current', 0) > 0)
            ok = grade in GRADE_SCORE
            kind = 'ok' if ok else ('stale' if grade == 'stale' else 'retrieval_miss' if in_store else 'capture_gap')
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
            'stale_answers': [f"{r['agent']}:{r['q']}" for r in rows if r['grade'] == 'stale']}


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


def lint_mistake(run, mk):
    """CI lint violations of one rule, by author (git blame). A violation an author introduces after the CI bot already
    showed them that rule is a repeat."""
    per = defaultdict(lambda: {'violations': 0, 'repeats': 0, 'told_at': None})
    seen = set()
    for i, row in enumerate(read_jsonl(run.dir / 'ci.jsonl')):
        authors_now = set()
        for v in row.get('lint') or []:
            if v.get('rule') != mk['rule']:
                continue
            k = (v.get('author'), v['file'], v['text'])
            authors_now.add(v.get('author'))
            if k in seen:
                continue
            seen.add(k)
            a = per[v.get('author') or '?']
            a['violations'] += 1
            if a['told_at'] is not None and a['told_at'] < i:
                a['repeats'] += 1
        for au in authors_now:
            if per[au or '?']['told_at'] is None:
                per[au or '?']['told_at'] = i
    return {'desc': mk['desc'], 'kind': 'lint', 'per_agent': dict(per), 'agents_hit': len(per),
            'repeats': sum(v['repeats'] for v in per.values()), 'total': sum(v['violations'] for v in per.values())}


def probe_metrics(run):
    rows = [read_json(p) for p in sorted((run.dir / 'probes').glob('*.json'))] if (run.dir / 'probes').exists() else []
    rows = [r for r in rows if r]
    scored = [r['score'] for r in rows if r.get('score') is not None]
    return {'probes': len(rows), 'mean_score': round(sum(scored) / len(scored), 3) if scored else None,
            'by_probe': {r['id']: r.get('score') for r in rows},
            'cost_usd': round(sum(r.get('cost_usd') or 0 for r in rows), 4),
            'mean_turns': round(sum(r.get('turns') or 0 for r in rows) / len(rows), 1) if rows else None,
            'mean_tool_calls': round(sum(r.get('tool_calls') or 0 for r in rows) / len(rows), 1) if rows else None,
            'mean_seconds': round(sum(r.get('seconds') or 0 for r in rows) / len(rows), 1) if rows else None}


def efficiency(run):
    """Mean cost, turns, tool calls and seconds per session, by kind of session."""
    kinds = {'work': WORK_KEY, 'quiz_memory': re.compile(r'^quiz/'), 'quiz_repo': re.compile(r'^quiz-repo/')}
    out = {}
    sess = list(run.state()['sessions'].values())
    for name, rx in kinds.items():
        rows = [r for r in sess if rx.match(r['key']) and not r['key'].endswith('.resolve')]
        if rows:
            out[name] = {k: round(sum((r.get(f) or 0) for r in rows) / len(rows), 4 if k == 'cost_usd' else 1)
                         for k, f in (('cost_usd', 'cost_usd'), ('turns', 'turns'), ('tool_calls', 'tool_calls'), ('seconds', 'seconds'))}
            out[name]['sessions'] = len(rows)
    chat = [r for r in read_jsonl(run.dir / 'costs.jsonl') if str(r.get('key', '')).startswith('chat/')]
    out['chat'] = {'messages': len(chat), 'cost_usd': round(sum(r.get('cost_usd') or 0 for r in chat), 4)}
    return out


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


# ---------- run ----------
def analyze(run):
    state = run.state()
    sess = list(state['sessions'].values())
    per_store = {p.name: store_metrics(p, run.truth) for p in sorted(run.stores.glob('*')) if not p.name.startswith('_')}
    for name, m in per_store.items():
        m['claude_automemory_files'] = automemory_files(run.ws / name)
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
        'totals': {'sessions': len(sess), 'work_sessions': len(work), 'cost_usd': run.spent(),
                   'failed_sessions': sum(1 for r in sess if r.get('subtype') != 'success'),
                   'timeouts': sum(1 for r in sess if r.get('timed_out')),
                   'lm_calls': sum(r.get('lm_calls') or 0 for r in sess),
                   'lm_calls_per_work_session': round(sum(r.get('lm_calls') or 0 for r in work) / len(work), 2) if work else None,
                   'tool_calls': sum(r.get('tool_calls') or 0 for r in sess),
                   'notes_active': sum(m['notes_active'] for m in per_store.values()),
                   'maps': sum(m['maps'] for m in per_store.values()),
                   'noise_notes': sum(m['noise_notes'] for m in per_store.values()),
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
        'quiz_repo_reads': quiz_repo_reads(run), 'mistakes': mistake_metrics(run), 'pointers': pointer_coverage(run), 'hook_latency': hook_latency(run),
        'probes': probe_metrics(run), 'efficiency': efficiency(run),
        'grader_audit': {k: v for k, v in (read_json(run.dir / 'quiz' / 'grader-audit.json') or {}).items() if k != 'rows'} or None,
        'currency': {'updates': sum(s['usage'].get('update', 0) for s in per_store.values()),
                     'supersedes': sum(s['by_status'].get('superseded', 0) for s in per_store.values())}}
    write_json(run.dir / 'metrics.json', metrics)
    return metrics


def summary(m):
    t, q, qr = m['totals'], m.get('quiz') or {}, m.get('quiz_repo') or {}
    opts = m.get('options') or {}
    lines = [f"run {m['run']} (memory {opts.get('memory', 'on')}, semantic {opts.get('semantic', False)}): {t['sessions']} sessions, "
             f"${t['cost_usd']}, failed {t['failed_sessions']}, timeouts {t['timeouts']}",
             f"memory: {t['notes_active']} active notes, {t['maps']} maps, {t['noise_notes']} noise-like, {t['lm_calls']} LM calls "
             f"({t['lm_calls_per_work_session']}/work session), {t['lm_cli_errors']} CLI errors, blocked-path attempts {t['leaks']}",
             f"currency: {(m.get('currency') or {}).get('updates')} updates, {(m.get('currency') or {}).get('supersedes')} superseded; "
             f"pointers: {(m.get('pointers') or {}).get('with_pointer')}/{(m.get('pointers') or {}).get('docs')} decision docs",
             f"CI: {m['ci']['green']}/{m['ci']['runs']} green, last {'green' if m['ci']['last_ok'] else 'RED'}; merges: "
             f"{m['merges']['conflicts_first_try']} conflicts, {m['merges']['failed_final']} unresolved"]
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
    keep = ('totals.', 'ci.', 'merges.', 'quiz.score', 'quiz.by_fact', 'quiz.by_agent', 'quiz.failure', 'by_tier.')
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
    ('run total $', lambda m: (m.get('totals') or {}).get('cost_usd')),
    ('CI green share', lambda m: round(m['ci']['green'] / m['ci']['runs'], 3) if (m.get('ci') or {}).get('runs') else None),
    ('commit-policy repeat sessions', lambda m: ((m.get('mistakes') or {}).get('M1') or {}).get('repeat_sessions')),
    ('lint repeats (L1+L2)', lambda m: sum(((m.get('mistakes') or {}).get(k) or {}).get('repeats') or 0 for k in ('M2', 'M3'))),
    ('stale notes (D1)', lambda m: len(((m.get('facts') or {}).get('D1') or {}).get('stores_with_stale_only') or [])),
)


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
    return '\n'.join(out)
