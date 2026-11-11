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


def quiz_metrics(run, per_store):
    qs = {q['id']: q for q in run.quiz.get('questions', [])}
    facts = run.truth.get('facts', {})
    matrix, rows = {}, []
    for p in sorted((run.dir / 'quiz' / 'grades').glob('*.json')):
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


# ---------- run ----------
def analyze(run):
    state = run.state()
    sess = list(state['sessions'].values())
    per_store = {p.name: store_metrics(p, run.truth) for p in sorted(run.stores.glob('*')) if not p.name.startswith('_')}
    for name, m in per_store.items():
        m['claude_automemory_files'] = automemory_files(run.ws / name)
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
    work = [r for r in sess if r['key'].startswith('s')]
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
        'handovers': read_jsonl(run.dir / 'handovers.jsonl'), 'app': app_checks(run), 'quiz': quiz_metrics(run, per_store)}
    write_json(run.dir / 'metrics.json', metrics)
    return metrics


def summary(m):
    t, q = m['totals'], m['quiz']
    lines = [f"run {m['run']}: {t['sessions']} sessions, ${t['cost_usd']}, failed {t['failed_sessions']}, timeouts {t['timeouts']}",
             f"memory: {t['notes_active']} active notes, {t['maps']} maps, {t['noise_notes']} noise-like, {t['lm_calls']} LM calls "
             f"({t['lm_calls_per_work_session']}/work session), {t['lm_cli_errors']} CLI errors, blocked-path attempts {t['leaks']}",
             f"CI: {m['ci']['green']}/{m['ci']['runs']} green, last {'green' if m['ci']['last_ok'] else 'RED'}; merges: "
             f"{m['merges']['conflicts_first_try']} conflicts, {m['merges']['failed_final']} unresolved",
             f"quiz: all {q['score_all']}, should-know {q['score_should_know']}, failures {q['failure_kinds_should_know']}"]
    for fid, f in m['facts'].items():
        lines.append(f"  {fid}: in {f['duplication']} stores, should-know coverage {f['should_know_coverage']}, "
                     f"stale-only in {f['stores_with_stale_only']}, quiz {q['by_fact_should_know'].get(fid)}")
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
