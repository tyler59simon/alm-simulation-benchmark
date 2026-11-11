"""Shared paths, configuration and small helpers for the simulation engine (stdlib only)."""
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]          # lm-team-sim/
SCENARIOS, RUNS = HOME / 'scenarios', HOME / 'runs'
_lock = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def append_jsonl(path, row):
    with _lock:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')


def read_jsonl(path):
    rows = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        pass
    except FileNotFoundError:
        pass
    return rows


def log(run, msg):
    line = f'[{now()}] {msg}'
    print(line, flush=True)
    if run is not None:
        with _lock, open(run.dir / 'sim.log', 'a', encoding='utf-8') as f:
            f.write(line + '\n')


def config():
    """Machine configuration: simkit/config.json, overridable per key by SIMKIT_<KEY> environment variables."""
    cfg = read_json(HOME / 'simkit' / 'config.json', {})
    for key in list(cfg):
        cfg[key] = os.path.expandvars(os.environ.get('SIMKIT_' + key.upper(), cfg[key]))
    real = read_json(Path.home() / '.config' / 'agentic-living-memory' / 'config.json', {}) or {}
    cfg.setdefault('real_store', real.get('data_root', ''))
    cfg['claude'] = shutil.which(cfg.get('claude', 'claude')) or cfg.get('claude', 'claude')
    return cfg


def rule_path(path):
    """Absolute path in Claude Code permission-rule form: //c/Users/..."""
    p = Path(path).resolve().as_posix()
    if len(p) > 1 and p[1] == ':':
        p = '/' + p[0].lower() + p[2:]
    return '/' + p


def tree_hash(paths):
    h = hashlib.sha256()
    for base in paths:
        base = Path(base)
        files = [base] if base.is_file() else sorted(p for p in base.rglob('*') if p.is_file())
        for f in files:
            h.update(f.relative_to(base.parent).as_posix().encode())
            h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def session_hash(session_id):
    """Same digest Living Memory logs and stamps on notes (core/runtime.py session_hash)."""
    return hashlib.sha256(session_id.encode()).hexdigest()[:12]


def clean_env(extra=None, path_prepend=()):
    """Environment for a child process: no inherited Claude Code session or Living Memory variables."""
    env = {k: v for k, v in os.environ.items()
           if not (k.upper().startswith(('CLAUDE', 'LIVING_MEMORY')) or k.upper() == 'NODEFAULTCURRENTDIRECTORYINEXEPATH')}
    for k, v in (extra or {}).items():
        env[k] = v
    if path_prepend:
        env['PATH'] = os.pathsep.join(list(path_prepend) + [env.get('PATH', '')])
    return env


def run_cmd(args, cwd=None, env=None, timeout=None, input=None, check=False):
    r = subprocess.run(args, cwd=cwd, env=env, timeout=timeout, input=input, text=True, encoding='utf-8',
                       errors='replace', capture_output=True)
    if check and r.returncode:
        raise RuntimeError(f'{args[:4]} failed ({r.returncode}): {(r.stderr or r.stdout)[-1500:]}')
    return r


def kill_tree(pid):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(pid)], capture_output=True)
    else:
        try:
            os.killpg(pid, 9)
        except OSError:
            pass


class Run:
    """A run folder: runs/<scenario>-<timestamp>/ with the frozen scenario copy it was started from."""

    def __init__(self, path):
        self.dir = Path(path).resolve()
        self.manifest = read_json(self.dir / 'manifest.json', {})
        self.options = {'memory': 'on', 'semantic': False, **(self.manifest.get('options') or {})}
        self.scenario_dir = self.dir / 'scenario'
        self.scenario = read_json(self.scenario_dir / 'scenario.json')
        self.events = read_json(self.scenario_dir / self.scenario.get('events', 'events.json'), {})
        self.truth = read_json(self.scenario_dir / self.scenario.get('ground_truth', 'ground_truth.json'), {})
        self.quiz = read_json(self.scenario_dir / self.scenario.get('quiz', 'quiz.json'), {})
        self.origin, self.integration = self.dir / 'origin.git', self.dir / 'integration'
        self.ws, self.stores, self.transcripts = self.dir / 'ws', self.dir / 'stores', self.dir / 'transcripts'
        self.state_path = self.dir / 'state.json'

    # ---- roster ----
    def agents(self):
        return {a['id']: a for a in self.scenario['roster']}

    def active(self, sprint):
        return [a for a in self.scenario['roster']
                if a.get('joins', 1) <= sprint and sprint <= a.get('leaves_after', 10 ** 6)]

    def tier(self, agent):
        return self.scenario['tiers'][agent['tier']]

    # ---- state ----
    def state(self):
        return read_json(self.state_path, {'sessions': {}, 'steps': []})

    def update_state(self, fn):
        with _lock:
            s = self.state()
            fn(s)
            write_json(self.state_path, s)
            return s

    def done(self, step):
        return step in self.state()['steps']

    def mark(self, step):
        self.update_state(lambda s: s['steps'].append(step) if step not in s['steps'] else None)

    def spent(self):
        return round(sum(r.get('cost_usd') or 0 for r in read_jsonl(self.dir / 'costs.jsonl')), 4)

    def toolchain_env(self):
        tc = self.scenario.get('toolchain', {})
        return tc.get('env', {}), tc.get('path_prepend', [])


def resolve_run(name):
    p = Path(name)
    if not p.is_absolute():
        p = RUNS / name
    if not (p / 'manifest.json').exists():
        raise SystemExit(f'No run at {p}')
    return Run(p)


def latest_run(scenario=None):
    runs = sorted((p for p in RUNS.glob('*') if (p / 'manifest.json').exists()
                   and (not scenario or p.name.startswith(scenario + '-'))), key=lambda p: p.name)
    if not runs:
        raise SystemExit('No runs yet')
    return Run(runs[-1])


def wait_until(predicate, timeout, step=1.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(step)
    return False
