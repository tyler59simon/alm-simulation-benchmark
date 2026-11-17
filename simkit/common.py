"""Shared paths, configuration and small helpers for the simulation engine (stdlib only)."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]          # alm-simulation-benchmark/
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
        value = os.environ.get('SIMKIT_' + key.upper(), cfg[key])
        cfg[key] = os.path.expandvars(value) if isinstance(value, str) else value
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


# Subcommands of the Living Memory CLI that the harness tells apart in transcripts and logs.
LM_SUBCOMMANDS = ('capture-finalize', 'capture', 'search', 'read', 'update', 'supersede', 'confirm', 'check', 'resolve',
                  'reopen', 'open', 'review', 'list', 'stats', 'apply', 'plan', 'undo', 'bind', 'timeline',
                  'history', 'links', 'doctor', 'export', 'import-plan', 'archive-plan', 'merge-plan', 'promote-plan',
                  'recap', 'ask', 'maintenance', 'changes', 'source-plan', 'source-sync', 'semantic', 'off', 'on',
                  'status', 'restore', 'log', 'help')
_LM_OPTIONS_WITH_VALUE = ('--domain', '--root', '--cwd', '--actor')
_PYTHON = re.compile(r'^(python(\d(\.\d+)?)?|pythonw|py)(\.exe)?$')


def _words(text):
    """Split shell text at unquoted ; | && || and newlines into segments of words (quotes removed; a backslash is
    literal, so Windows paths survive, except \\" inside double quotes). A PowerShell call operator & before a word
    is dropped."""
    segments, words, word, quote, i = [], [], None, None, 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
            elif quote == '"' and ch == '\\' and text[i + 1:i + 2] == '"':
                word += '"'
                i += 1
            else:
                word += ch
        elif ch in '\'"':
            quote, word = ch, word or ''
        elif ch in ';|\n' or text.startswith('&&', i):
            if word is not None:
                words.append(word)
            segments.append(words)
            words, word = [], None
            i += 1 if ch == '&' else 0   # && is two characters
        elif ch == '&' and word is None and not words:
            pass   # the call operator: & "path" args
        elif ch.isspace():
            if word is not None:
                words.append(word)
                word = None
        else:
            word = (word or '') + ch
        i += 1
    if word is not None:
        words.append(word)
    segments.append(words)
    return [w for w in segments if w]


def _base(word):
    return word.replace('\\', '/').rsplit('/', 1)[-1].lower()


_VARIABLE = re.compile(r'\$(?:env:)?\{?(\w+)\}?')


def _expand(word, variables):
    """Variables the command assigned earlier: a word that is only a variable ($X, ${X}, $env:X) becomes its value
    (split into words only when the value is itself a command line, that is, it holds quotes; a path with spaces stays
    one word), and a variable inside a longer word is replaced in place."""
    whole = _VARIABLE.fullmatch(word)
    if whole and whole[1].lower() in variables:
        value = variables[whole[1].lower()]
        return [w for seg in _words(value) for w in seg] if ' ' in value and re.search('[\'"]', value) else [value]
    return [_VARIABLE.sub(lambda m: variables.get(m[1].lower(), m[0]), word)]


def _subcommand(words):
    """Subcommand of `[interpreter [flags] script | alm] [global options] SUBCOMMAND ...`, else None when the words do not
    start a Living Memory call."""
    i = 0
    while i < len(words) and words[i] in ('&', 'eval', '{', 'do', 'then', 'else'):
        i += 1
    if i >= len(words):
        return None
    first = _base(words[i])
    if first in ('alm', 'alm.exe'):
        i += 1
    elif _PYTHON.match(first):
        i += 1
        while i < len(words) and words[i].startswith('-'):
            i += 2 if words[i] in ('-X', '-W') else 1   # interpreter flags: -I, -X utf8, -3.10
        if i >= len(words) or _base(words[i]) != 'living_memory.py':
            return None
        i += 1
    elif first == 'living_memory.py':
        i += 1
    else:
        return None
    while i < len(words):
        w = words[i]
        if w in _LM_OPTIONS_WITH_VALUE:
            i += 2
        elif w == '--json' or w.partition('=')[0] in _LM_OPTIONS_WITH_VALUE:
            i += 1
        else:
            return w if w in LM_SUBCOMMANDS else 'other'
    return 'other'


def lm_call(command):
    """The Living Memory subcommand a shell command runs, else None; 'other' for a Living Memory call without a known
    subcommand. Recognises `[&] "<python>" [flags] "<...>/living_memory.py" ...` and the bare or pathed `alm` / `alm.exe`
    launcher, in Bash or PowerShell, after optional global options (--json, --domain D, --root R, --cwd C, --actor A).
    Only the first word of a command (or of one stage of a chain, or of a { } block) counts, so `realm`, `palm`, or an
    `alm` inside a path or an argument never match. Variables and shell functions the command defines itself are
    followed (PY="..."; LM="..."; "$PY" "$LM" capture; lm() { python ...; }; lm capture)."""
    if not isinstance(command, str) or not command.strip():
        return None
    variables, functions = {}, {}
    for words in _words(command):
        if len(words) >= 3 and re.fullmatch(r'\$\w+', words[0]) and words[1] == '=':   # PowerShell: $py = "..."
            words = [words[0] + '=' + words[2]] + words[3:]
        if len(words) >= 2 and words[0].endswith('()') and words[1] == '{':   # Bash: lm() { python ... "$@"; }
            functions[words[0][:-2]] = [w for w in words[2:] if w != '"$@"' and w != '$@']
            continue
        i = 0
        while i < len(words) and re.match(r'^\$?[A-Za-z_][A-Za-z0-9_]*=', words[i]):   # VAR=value (Bash prefix or assignment)
            name, _, value = words[i].partition('=')
            variables[name.lstrip('$').lower()] = _VARIABLE.sub(lambda m: variables.get(m[1].lower(), m[0]), value)
            i += 1
        words = [x for w in words[i:] for x in _expand(w, variables)]
        if words and words[0] in functions:
            words = [x for w in functions[words[0]] for x in _expand(w, variables)] + words[1:]
        if words and (words[0] == 'eval' or words[:2] == ['cmd', '/c']):   # eval "$CMD read x": the string is a command line
            text = _VARIABLE.sub(lambda m: variables.get(m[1].lower(), m[0]), ' '.join(words[1 if words[0] == 'eval' else 2:]))
            words = (_words(text) or [[]])[0]
        for start in [0] + [j + 1 for j, w in enumerate(words) if w.endswith('{')]:   # also the body of foreach(...){ & $py ... }
            found = _subcommand(words[start:])
            if found:
                return found
    return None


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


def use_lm_src(src):
    """Point the harness's Living Memory CLI and source repo at a checkout (a path or git worktree), for this process:
    config() reads these SIMKIT_ variables, so stores, version stamps and the readout all use that checkout."""
    src = str(Path(src).resolve())
    os.environ['SIMKIT_LM_CLI'] = str(Path(src) / 'living_memory.py')
    os.environ['SIMKIT_LM_REPO'] = src


class Run:
    """A run folder: runs/<scenario>-<timestamp>/ with the frozen scenario copy it was started from."""

    def __init__(self, path):
        self.dir = Path(path).resolve()
        self.manifest = read_json(self.dir / 'manifest.json', {})
        self.options = {'memory': 'on', 'semantic': False, **(self.manifest.get('options') or {})}
        if self.options.get('lm_src'):
            use_lm_src(self.options['lm_src'])   # a resumed run keeps using the checkout it started with
        self.workspace = self.dir / 'workspace'   # the company's tools outside the repo: tracker, wiki, chat, hooks
        self.scenario_dir = self.dir / 'scenario'
        self.scenario = read_json(self.scenario_dir / 'scenario.json')
        self.events = read_json(self.scenario_dir / self.scenario.get('events', 'events.json'), {})
        self.truth = read_json(self.scenario_dir / self.scenario.get('ground_truth', 'ground_truth.json'), {})
        self.quiz = read_json(self.scenario_dir / self.scenario.get('quiz', 'quiz.json'), {})
        self.probes = (read_json(self.scenario_dir / self.scenario['probes'], {}) or {}).get('probes', []) if self.scenario.get('probes') else []
        self.origin, self.integration = self.dir / 'origin.git', self.dir / 'integration'
        self.ws, self.stores, self.transcripts = self.dir / 'ws', self.dir / 'stores', self.dir / 'transcripts'
        self.state_path = self.dir / 'state.json'
        self.workspace_enabled = bool(self.scenario.get('workspace'))
        self.days = int(self.scenario.get('days_per_sprint', 1))
        self.clock = self.manifest.get('clock') or {'enabled': False}   # simulated calendar, see simkit/clock.py

    # ---- roster ----
    def agents(self):
        return {a['id']: a for a in self.scenario['roster']}

    def active(self, sprint):
        return [a for a in self.scenario['roster']
                if a.get('joins', 1) <= sprint and sprint <= a.get('leaves_after', 10 ** 6)]

    def tier(self, agent):
        tier = self.scenario['tiers'][agent['tier']]
        model = self.options.get('work_model')
        if model and agent['tier'] != 'grader':   # one model for every agent; its tier's effort setting may not exist for it
            tier = {k: v for k, v in tier.items() if k != 'effort'} | {'model': model}
        return tier

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
        """Dollars spent; a session that ended without a result event counts at its budget cap (cost_bound_usd)."""
        return round(sum(r.get('cost_usd') if r.get('cost_usd') is not None else r.get('cost_bound_usd') or 0
                         for r in read_jsonl(self.dir / 'costs.jsonl')), 4)

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
