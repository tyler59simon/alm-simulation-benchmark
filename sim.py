"""alm-simulation-benchmark: simulate an enterprise team whose agents each have a private Living Memory store.

    python sim.py smoke   SCENARIO                 tiny harness check on a throwaway run
    python sim.py init    SCENARIO [--label L] [--memory on|off] [--semantic] [--review-user]
                                                   new run folder (repo, clones, stores, toolchain prime, seed CI)
    python sim.py sprint  N [--run RUN]            one sprint (resumable)
    python sim.py run     [--run RUN] [--through N] all sprints (resumable)
    python sim.py quiz    [--run RUN] [--mode memory|repo]  recall quiz (memory only, or with the repo)
    python sim.py grade   [--run RUN] [--mode memory|repo]  grade quiz answers against ground truth
    python sim.py analyze [--run RUN]              write metrics.json and print a summary
    python sim.py compare RUN_A RUN_B              diff comparable metrics of two runs
    python sim.py verify-isolation [--run RUN]     no run session in the real store or another agent's store
    python sim.py status  [--run RUN]              steps done, sessions, spend
    python sim.py docs                             write the run log in docs/ (Markdown and HTML)

RUN defaults to the newest run folder under runs/. Nothing is ever deleted.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from simkit import analyze, engine  # noqa: E402
from simkit.common import latest_run, log, read_json, resolve_run  # noqa: E402


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')   # the Windows console defaults to cp1252
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('smoke'); s.add_argument('scenario')
    s = sub.add_parser('init'); s.add_argument('scenario'); s.add_argument('--label'); s.add_argument('--no-prime', action='store_true')
    s.add_argument('--memory', choices=['on', 'off', 'builtin'], default='on',
                   help="off: no memory at all (A0); builtin: Claude Code's own auto-memory only (A1); on: Living Memory")
    s.add_argument('--semantic', action='store_true', help='install the embedding model into every store')
    s.add_argument('--review-user', action='store_true', help='at each sprint end, archive the notes the review worklist proposes to archive')
    s = sub.add_parser('pipeline', help='init + all sprints + quizzes + grading + probes + grader audit + analysis, resumable')
    s.add_argument('scenario'); s.add_argument('--label'); s.add_argument('--memory', choices=['on', 'off', 'builtin'], default='on')
    s.add_argument('--semantic', action='store_true'); s.add_argument('--run', help='resume this run instead of creating one')
    s.add_argument('--review-user', action='store_true')
    for name in ('probes', 'grade-audit'):
        sub.add_parser(name).add_argument('--run')
    s = sub.add_parser('kb-quiz', help='arm D: a fresh agent answers the quiz from a knowledge base of the finished project')
    s.add_argument('--run'); s.add_argument('--digests-budget', type=float, help='also write digest notes (claude -p, USD cap)')
    s = sub.add_parser('compare-arms', help='mean ± sd per arm: NAME=RUN[,RUN...] ...'); s.add_argument('arms', nargs='+')
    s = sub.add_parser('sprint'); s.add_argument('n', type=int); s.add_argument('--run')
    s = sub.add_parser('run'); s.add_argument('--run'); s.add_argument('--through', type=int)
    for name in ('quiz', 'grade'):
        s = sub.add_parser(name); s.add_argument('--run'); s.add_argument('--mode', choices=['memory', 'repo'], default='memory')
    for name in ('analyze', 'verify-isolation', 'status', 'finish'):
        sub.add_parser(name).add_argument('--run')
    s = sub.add_parser('compare'); s.add_argument('a'); s.add_argument('b')
    sub.add_parser('docs', help='write the run log (docs/, Markdown and HTML) from runs/, docs/notes/ and the LM repo history')
    a = p.parse_args(argv)
    get = lambda: resolve_run(a.run) if getattr(a, 'run', None) else latest_run()  # noqa: E731
    if a.cmd == 'smoke':
        print(json.dumps(engine.smoke(a.scenario), indent=2))
    elif a.cmd == 'init':
        run = engine.init(a.scenario, a.label, prime=not a.no_prime, memory=a.memory, semantic=a.semantic, review_user=a.review_user)
        print(run.dir)
    elif a.cmd in ('sprint', 'run'):
        run = get()
        try:
            engine.sprint(run, a.n) if a.cmd == 'sprint' else engine.run_all(run, a.through)
        except engine.SpendLimit as e:
            log(run, f'STOPPED: {e}')
            return 3
    elif a.cmd == 'quiz':
        engine.quiz(get(), a.mode)
    elif a.cmd == 'grade':
        engine.grade(get(), a.mode)
    elif a.cmd == 'analyze':
        print(analyze.summary(analyze.analyze(get())))
    elif a.cmd == 'pipeline':
        from simkit import probes
        run = resolve_run(a.run) if a.run else engine.init(a.scenario, a.label, memory=a.memory, semantic=a.semantic, review_user=a.review_user)
        print(run.dir.name, flush=True)
        try:
            engine.run_all(run)
        except engine.SpendLimit as e:
            log(run, f'STOPPED: {e}')
            return 3
        for mode in engine.quiz_modes(run.options.get('memory')):
            engine.quiz(run, mode)
            engine.grade(run, mode)
        if run.probes:
            probes.grade_probes(run)
        probes.grade_audit(run)
        print(analyze.summary(analyze.analyze(run)))
        iso = engine.isolation(run)
        log(run, f"isolation: {'ok' if iso['ok'] else 'FAILED ' + json.dumps(iso)[:400]}")
        engine.finish(run)
    elif a.cmd == 'kb-quiz':
        run = get()
        engine.kb_quiz(run, a.digests_budget)
        print(analyze.summary(analyze.analyze(run)))
    elif a.cmd == 'probes':
        from simkit import probes
        print(json.dumps([{k: r.get(k) for k in ('id', 'score')} for r in probes.grade_probes(get())]))
    elif a.cmd == 'grade-audit':
        from simkit import probes
        print(json.dumps({k: v for k, v in (probes.grade_audit(get()) or {}).items() if k != 'rows'}, indent=2))
    elif a.cmd == 'compare-arms':
        arms = {}
        for spec in a.arms:
            name, _, runs = spec.partition('=')
            arms[name] = [read_json(resolve_run(r).dir / 'metrics.json') for r in runs.split(',') if r]
        print(analyze.compare_arms(arms))
    elif a.cmd == 'compare':
        text, diffs = analyze.compare(read_json(resolve_run(a.a).dir / 'metrics.json'), read_json(resolve_run(a.b).dir / 'metrics.json'))
        print(text)
        print(f'{diffs} differing metrics')
    elif a.cmd == 'verify-isolation':
        r = engine.isolation(get())
        print(json.dumps(r, indent=2))
        return 0 if r['ok'] else 1
    elif a.cmd == 'status':
        run = get()
        st = run.state()
        print(json.dumps({'run': run.dir.name, 'steps': st['steps'], 'sessions': len(st['sessions']),
                          'spent_usd': run.spent()}, indent=2))
    elif a.cmd == 'finish':
        engine.finish(get())
    elif a.cmd == 'docs':
        from simkit import docs
        print(docs.build())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
