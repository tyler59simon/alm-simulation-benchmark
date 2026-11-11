"""Bare origin, one persistent clone per agent, an integration clone that merges branches and runs CI."""
import shutil
import time
from pathlib import Path

from .common import append_jsonl, clean_env, now, run_cmd

GIT_ENV = {'GIT_TERMINAL_PROMPT': '0'}
# Git for Windows ships core.autocrlf=true system-wide: a clone checked out with CRLF and then switched to false
# shows every file modified, and the pre-sprint auto-commit would rewrite the whole repo (golden data included).
NO_EOL = ('-c', 'core.autocrlf=false')


def git(cwd, *args, check=True, timeout=300):
    return run_cmd(['git', *args], cwd=cwd, env=clean_env(GIT_ENV), timeout=timeout, check=check)


def _identity(repo, name, email):
    git(repo, 'config', 'user.name', name)
    git(repo, 'config', 'user.email', email)
    git(repo, 'config', 'core.autocrlf', 'false')
    git(repo, 'config', 'merge.conflictstyle', 'diff3')


def init_repo(run):
    """origin.git (bare) with the scenario seed as the first commit on main; integration clone for merges."""
    git(run.dir, 'init', '--bare', '-b', 'main', str(run.origin))
    git(run.dir, 'clone', *NO_EOL, str(run.origin), str(run.integration))
    _identity(run.integration, 'LIGHTHOUSE Release Bot', 'release-bot@harborpoint.example')
    git(run.integration, 'checkout', '-B', 'main')
    for src, dst in run.scenario['seed']:
        s, d = run.scenario_dir / src, run.integration / dst
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
    for keep in ('team/standup', 'docs/handoff'):
        (run.integration / keep).mkdir(parents=True, exist_ok=True)
        (run.integration / keep / '.gitkeep').touch()
    git(run.integration, 'add', '-A')
    git(run.integration, 'commit', '-q', '-m', 'Project LIGHTHOUSE seed: legacy COBOL, captured data, Spring Boot skeleton')
    git(run.integration, 'push', '-q', 'origin', 'main')


def clone_for(run, agent):
    path = run.ws / agent['id']
    if not path.exists():
        git(run.dir, 'clone', '-q', *NO_EOL, str(run.origin), str(path))
        _identity(path, agent.get('name', agent['id']), f"{agent['id']}@harborpoint.example")
    return path


def autocommit(repo, who):
    """Commit anything the agent left uncommitted; returns the number of files swept up (a metric)."""
    if git(repo, 'rev-parse', '-q', '--verify', 'MERGE_HEAD', check=False).returncode == 0:
        # A merge the agent resolved but did not commit is concluded; one still conflicted is abandoned.
        unmerged = git(repo, 'diff', '--name-only', '--diff-filter=U', check=False).stdout.split()
        if unmerged:
            git(repo, 'merge', '--abort', check=False)
        else:
            git(repo, 'add', '-A')
            git(repo, 'commit', '-q', '--no-edit', check=False)
    status = git(repo, 'status', '--porcelain', check=False).stdout.strip().splitlines()
    if status:
        git(repo, 'add', '-A')
        git(repo, 'commit', '-q', '-m', f'[sim] auto-commit of uncommitted work left by {who}', check=False)
    return len(status)


def start_branch(run, agent, sprint):
    """Agent's branch for this sprint: previous work plus latest main. Returns notes about what happened."""
    repo, aid = clone_for(run, agent), agent['id']
    info = {'swept': autocommit(repo, aid)}
    git(repo, 'fetch', '-q', 'origin')
    branch = f'{aid}/s{sprint}'
    git(repo, 'checkout', '-q', '-B', branch)
    m = git(repo, 'merge', '-q', '--no-edit', 'origin/main', check=False)
    if m.returncode:
        git(repo, 'merge', '--abort', check=False)
        git(repo, 'checkout', '-q', '-B', branch, 'origin/main')
        info['reset_to_main'] = True
    info['branch'] = branch
    return info


def merge_agent(run, agent, sprint):
    """Merge the agent's branch into main in the integration clone. Returns (ok, detail)."""
    repo, aid = run.ws / agent['id'], agent['id']
    swept = autocommit(repo, aid)
    branch = git(repo, 'rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()
    git(run.integration, 'checkout', '-q', 'main')
    git(run.integration, 'pull', '-q', '--ff-only', 'origin', 'main', check=False)
    git(run.integration, 'fetch', '-q', str(repo), f'+{branch}:refs/agents/{aid}')
    ahead = git(run.integration, 'rev-list', '--count', f'main..refs/agents/{aid}').stdout.strip()
    if ahead == '0':
        return True, {'swept': swept, 'commits': 0}
    m = git(run.integration, 'merge', '--no-ff', '--no-edit', '-m', f'Merge {branch} ({aid}, sprint {sprint})',
            f'refs/agents/{aid}', check=False)
    if m.returncode:
        files = git(run.integration, 'diff', '--name-only', '--diff-filter=U', check=False).stdout.split()
        git(run.integration, 'merge', '--abort', check=False)
        return False, {'swept': swept, 'commits': int(ahead), 'conflicts': files}
    git(run.integration, 'push', '-q', 'origin', 'main')
    return True, {'swept': swept, 'commits': int(ahead)}


def prepare_conflict(run, agent):
    """Leave the agent's clone mid-merge with origin/main so a resolve session can fix the conflicts."""
    repo = run.ws / agent['id']
    git(repo, 'fetch', '-q', 'origin')
    m = git(repo, 'merge', '--no-edit', 'origin/main', check=False)
    return m.returncode != 0


def run_ci(run, label):
    ci = run.scenario.get('ci')
    if not ci:
        return None
    env, path = run.toolchain_env()
    cwd = run.integration / ci.get('cwd', '.')
    t0 = time.time()
    if not cwd.exists():
        row = {'ts': now(), 'label': label, 'ok': False, 'reason': f'{ci.get("cwd")} missing'}
    else:
        try:
            r = run_cmd(ci['command'], cwd=cwd, env=clean_env(env, path), timeout=ci.get('timeout_min', 20) * 60)
            tail = (r.stdout + '\n' + r.stderr).strip().splitlines()[-ci.get('tail_lines', 40):]
            row = {'ts': now(), 'label': label, 'ok': r.returncode == 0, 'exit': r.returncode, 'tail': tail}
        except Exception as e:  # timeout
            row = {'ts': now(), 'label': label, 'ok': False, 'reason': repr(e)[:300]}
    row['seconds'] = round(time.time() - t0, 1)
    row['main'] = git(run.integration, 'rev-parse', '--short', 'HEAD').stdout.strip()
    append_jsonl(run.dir / 'ci.jsonl', row)
    return row


def prime(run):
    p = run.scenario.get('prime')
    if not p:
        return None
    env, path = run.toolchain_env()
    r = run_cmd(p['command'], cwd=run.integration / p.get('cwd', '.'), env=clean_env(env, path),
                timeout=p.get('timeout_min', 20) * 60)
    return {'ok': r.returncode == 0, 'tail': (r.stdout + r.stderr).strip().splitlines()[-15:]}
