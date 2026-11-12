"""Grading for work probes (sprint-4 tasks that silently need earlier knowledge) and an audit of the LLM grader."""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from .common import read_json, read_jsonl, write_json
from .gitops import git

EVIDENCE_CHARS = {'reply': 6000, 'diff': 14000, 'tracker': 6000}
GRADER = {'id': '_grader', 'tier': 'grader', 'name': 'grader'}
NO_TOOLS = ['Read', 'Grep', 'Glob', 'Edit', 'Write', 'NotebookEdit', 'WebFetch', 'WebSearch', 'Agent', 'Task', 'Bash', 'PowerShell']


def _ts(s):
    try:
        return datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return None


def evidence(run, probe):
    """{'reply', 'diff', 'tracker'} for the probe's session, or None when the session never ran."""
    from .engine import day_label
    from .replies import final_reply
    label = day_label(run, probe['sprint'], probe['day'])
    key = f"{label}/{probe['agent']}"
    row = run.state()['sessions'].get(key)
    if not row:
        return None, key, None
    tip = next((m.get('tip') for m in reversed(read_jsonl(run.dir / 'merges.jsonl'))
                if m.get('agent') == probe['agent'] and m.get('label') == label and m.get('tip')), None) or row.get('rev_after')
    diff = ''
    if row.get('rev_before') and tip:
        diff = git(run.ws / probe['agent'], 'diff', row['rev_before'], tip, '--', '.', ':(exclude)legacy/data', check=False).stdout
    t0, t1 = _ts(row.get('started')), _ts(row.get('ended'))
    tracker = []
    for d in ('tracker', 'wiki'):
        for p in sorted((run.workspace / d).rglob('*')):
            if p.is_file() and t0 and t1 and t0 <= p.stat().st_mtime <= t1 + 5:
                tracker.append(f"--- {d}/{p.relative_to(run.workspace / d).as_posix()}\n" + p.read_text(encoding='utf-8', errors='replace'))
    ev = {'reply': final_reply(run.transcripts / f'{key}.jsonl', row.get('final') or ''), 'diff': diff, 'tracker': '\n'.join(tracker)}
    return {k: v[:EVIDENCE_CHARS[k]] + ('\n[... truncated]' if len(v) > EVIDENCE_CHARS[k] else '') for k, v in ev.items()}, key, row


def grader_store(run):
    from . import stores
    store = run.stores / '_grader'
    if not (store / 'tag_taxonomy.json').exists():
        stores.bootstrap(store, '_grader', [], [])


def _select(ev, on):
    parts = on.split('+') if on != 'all' else list(EVIDENCE_CHARS)
    return '\n\n'.join(f'=== {p.upper()} ===\n{ev.get(p) or "(none)"}' for p in parts)


def grade_probes(run):
    from .engine import _last_json, _session
    grader_store(run)
    out_dir = run.dir / "probes"
    room = run.dir / 'quiz' / 'grader'
    room.mkdir(parents=True, exist_ok=True)
    results = []
    for probe in run.probes:
        ev, key, row = evidence(run, probe)
        if ev is None:
            results.append({'id': probe['id'], 'score': None, 'reason': f'session {key} did not run'})
            continue
        checks, judged = [], [c for c in probe['checks'] if c['type'] == 'judge']
        for c in probe['checks']:
            if c['type'] == 'regex':
                checks.append({**c, 'pass': bool(re.search(c['pattern'], _select(ev, c['on']), re.I | re.S))})
        verdicts = {}
        if judged:
            items = '\n'.join(f"- {c['id']} (look at: {c['on']}): {c['rubric']}" for c in judged)
            prompt = ('You are reviewing the work an engineer did on one task, for an engineering-quality study. For each '
                      'criterion decide pass or fail from the evidence only (the engineer\'s reply, the code diff they committed, '
                      'and tracker or wiki pages they changed). Pass only when the criterion is clearly met; vague or missing '
                      'evidence fails. Do not use tools.\n\nTASK THEY WERE GIVEN:\n' + probe['task'] + '\n\nCRITERIA:\n' + items +
                      '\n\nEVIDENCE:\n' + _select(ev, 'reply+diff+tracker') +
                      '\n\nReply with only a JSON object: {"items": [{"id": "...", "pass": true, "reason": "short"}, ...]}')
            # Keyed by the evidence graded, so corrected evidence is graded afresh rather than served a cached verdict.
            gkey = f"probe-grade/{probe['id']}@{hashlib.sha256(prompt.encode()).hexdigest()[:8]}"
            r = _session(run, gkey, GRADER, prompt, room, allow=[], deny=NO_TOOLS, settings={'disableAllHooks': True})
            from .engine import full_final
            verdicts = {i.get('id'): i for i in (_last_json(full_final(run, gkey, r)) or {}).get('items', [])
                        if isinstance(i, dict)}
        for c in judged:
            v = verdicts.get(c['id']) or {}
            checks.append({**c, 'pass': bool(v.get('pass')), 'reason': v.get('reason')})
        total = sum(c['weight'] for c in probe['checks'])
        score = round(sum(c['weight'] for c in checks if c['pass']) / total, 3) if total else None
        res = {'id': probe['id'], 'agent': probe['agent'], 'facts': probe['facts'], 'session': key, 'score': score,
               'checks': [{k: c.get(k) for k in ('id', 'type', 'weight', 'pass', 'reason')} for c in checks],
               'cost_usd': row.get('cost_usd'), 'turns': row.get('turns'), 'tool_calls': row.get('tool_calls'), 'seconds': row.get('seconds')}
        write_json(out_dir / f"{probe['id']}.json", res)
        results.append(res)
    run.mark('probes')
    return results


def grade_audit(run):
    """Run the quiz grader on known answers; report how often it accepts wrong or stale answers and rejects right ones."""
    from .engine import _last_json, _session, full_final
    cal = read_json(run.scenario_dir / run.scenario.get('grader_calibration', 'grader_calibration.json'), {}) or {}
    items = cal.get('items', [])
    if not items:
        return None
    grader_store(run)
    facts, qs = run.truth['facts'], {q['id']: q for q in run.quiz['questions']}
    used = sorted({i['q'] for i in items})
    key_text = '\n'.join(f"{q} (fact {qs[q]['fact']}): {qs[q]['text']}\n   ground truth: {facts[qs[q]['fact']]['answer']}"
                         + (f"\n   stale (outdated) answer: {facts[qs[q]['fact']]['stale_answer']}" if facts[qs[q]['fact']].get('stale_answer') else '')
                         for q in used)
    answers = [{'id': f"a{n}", 'question': i['q'], 'answer': i['answer']} for n, i in enumerate(items)]
    prompt = ('You are grading a knowledge quiz for a software project. For each answer compare it with the ground truth of its '
              'question. Grades: "correct" (all key points right), "partial" (some key points, nothing wrong), "stale" (gives '
              'the outdated answer where one is listed), "wrong" (contradicts the ground truth), "unknown" (answered unknown or '
              f'no answer). Do not use any tools.\n\nQUESTIONS AND GROUND TRUTH\n{key_text}\n\nANSWERS\n{json.dumps(answers, indent=1)}\n\n'
              'Reply with only a JSON object: {"grades": [{"id": "a0", "grade": "...", "note": "short reason"}, ...]}')
    room = run.dir / 'quiz' / 'grader'
    room.mkdir(parents=True, exist_ok=True)
    r = _session(run, 'grade-audit/calibration', GRADER, prompt, room, allow=[], deny=NO_TOOLS, settings={'disableAllHooks': True})
    got = {g.get('id'): g.get('grade') for g in (_last_json(full_final(run, 'grade-audit/calibration', r)) or {}).get('grades', [])
           if isinstance(g, dict)}
    ok_grades = {'correct', 'partial'}
    rows = [{'q': i['q'], 'expect': i['expect'], 'got': got.get(f'a{n}')} for n, i in enumerate(items)]
    neg = [x for x in rows if x['expect'] in ('wrong', 'stale', 'unknown')]
    pos = [x for x in rows if x['expect'] == 'correct']
    report = {'items': len(rows), 'agreement': round(sum(x['got'] == x['expect'] for x in rows) / len(rows), 3),
              'false_accept_rate': round(sum(x['got'] in ok_grades for x in neg) / len(neg), 3) if neg else None,
              'false_reject_rate': round(sum(x['got'] not in ok_grades for x in pos) / len(pos), 3) if pos else None,
              'stale_detected': round(sum(x['got'] == 'stale' for x in rows if x['expect'] == 'stale') /
                                      max(1, sum(x['expect'] == 'stale' for x in rows)), 3),
              'rows': rows}
    write_json(run.dir / 'quiz' / 'grader-audit.json', report)
    return report
