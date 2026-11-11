"""lm-team-sim: simulate an enterprise team whose agents each have a private Living Memory store.

    python sim.py smoke   SCENARIO                 tiny harness check on a throwaway run
    python sim.py init    SCENARIO [--label L]     new run folder (repo, clones, stores, toolchain prime, seed CI)
    python sim.py sprint  N [--run RUN]            one sprint (resumable)
    python sim.py run     [--run RUN] [--through N] all sprints (resumable)
    python sim.py quiz    [--run RUN]              memory-only recall quiz for every agent
    python sim.py grade   [--run RUN]              grade quiz answers against ground truth
    python sim.py analyze [--run RUN]              write metrics.json and print a summary
    python sim.py compare RUN_A RUN_B              diff comparable metrics of two runs
    python sim.py verify-isolation [--run RUN]     no run session in the real store or another agent's store
    python sim.py status  [--run RUN]              steps done, sessions, spend

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
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('smoke'); s.add_argument('scenario')
    s = sub.add_parser('init'); s.add_argument('scenario'); s.add_argument('--label'); s.add_argument('--no-prime', action='store_true')
    s = sub.add_parser('sprint'); s.add_argument('n', type=int); s.add_argument('--run')
    s = sub.add_parser('run'); s.add_argument('--run'); s.add_argument('--through', type=int)
    for name in ('quiz', 'grade', 'analyze', 'verify-isolation', 'status', 'finish'):
        sub.add_parser(name).add_argument('--run')
    s = sub.add_parser('compare'); s.add_argument('a'); s.add_argument('b')
    a = p.parse_args(argv)
    get = lambda: resolve_run(a.run) if getattr(a, 'run', None) else latest_run()  # noqa: E731
    if a.cmd == 'smoke':
        print(json.dumps(engine.smoke(a.scenario), indent=2))
    elif a.cmd == 'init':
        run = engine.init(a.scenario, a.label, prime=not a.no_prime)
        print(run.dir)
    elif a.cmd in ('sprint', 'run'):
        run = get()
        try:
            engine.sprint(run, a.n) if a.cmd == 'sprint' else engine.run_all(run, a.through)
        except engine.SpendLimit as e:
            log(run, f'STOPPED: {e}')
            return 3
    elif a.cmd == 'quiz':
        engine.quiz(get())
    elif a.cmd == 'grade':
        engine.grade(get())
    elif a.cmd == 'analyze':
        print(analyze.summary(analyze.analyze(get())))
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
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
