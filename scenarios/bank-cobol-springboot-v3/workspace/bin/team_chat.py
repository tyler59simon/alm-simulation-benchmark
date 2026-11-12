"""Harbor Point Slack (direct messages with colleagues outside the engineering team).

    py "{{WORKSPACE}}/bin/team_chat.py" people
    py "{{WORKSPACE}}/bin/team_chat.py" ask "Helen Brandt" "Do Heritage accounts accrue differently?"
    py "{{WORKSPACE}}/bin/team_chat.py" history "Helen Brandt"

Messages are direct messages between you and that person. Slack keeps only the current sprint's history visible.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RUN = Path(os.environ.get('SIM_RUN', ''))
ME = os.environ.get('SIM_AGENT', 'unknown')
NPCS = RUN / 'scenario' / 'npcs.json'
CHAT = RUN / 'workspace' / 'chat'


def load():
    try:
        return json.loads(NPCS.read_text(encoding='utf-8'))['people']
    except (OSError, ValueError, KeyError):
        sys.exit('Slack is unavailable right now (no directory).')


def find(people, name):
    low = name.strip().lower()
    hits = [p for p in people if low in (p['name'].lower(), p['handle'].lower()) or low in p['name'].lower()]
    if len(hits) != 1:
        sys.exit(f"No single person matches {name!r}. Try: " + ', '.join(p['name'] for p in people))
    return hits[0]


def clock():
    try:
        return json.loads((RUN / 'workspace' / '.clock.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'sprint': 0, 'day': 0, 'label': '?'}


def thread_path(person):
    return CHAT / f"{ME}__{person['handle']}.jsonl"


def read_thread(person):
    try:
        return [json.loads(l) for l in thread_path(person).read_text(encoding='utf-8').splitlines() if l.strip()]
    except OSError:
        return []


def append(person, row):
    CHAT.mkdir(parents=True, exist_ok=True)
    with open(thread_path(person), 'a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def known(person, sprint):
    """What the colleague knows in this sprint: plain strings always; {text, from_sprint, until_sprint} only in range."""
    out = []
    for k in person['knows']:
        if isinstance(k, str):
            out.append(k)
        elif k.get('from_sprint', 0) <= (sprint or 0) <= k.get('until_sprint', 99):
            out.append(k['text'])
    return out


def reply(person, thread, message, asker):
    """The colleague answers in character from their own knowledge only (a small model, no tools, no hooks)."""
    claude = shutil.which('claude') or 'claude'
    history = '\n'.join(f"{'THEM' if r['who'] == 'agent' else 'YOU'}: {r['text']}" for r in thread[-30:])
    prompt = (
        f"You are {person['name']}, {person['role']} at Harbor Point Savings & Trust, a US retail bank. You are answering a "
        f"direct message on the company Slack from {asker}, an engineer on Project LIGHTHOUSE (the rewrite of the nightly "
        f"COBOL batch in Java).\n\nWHAT YOU KNOW (your own knowledge; share it when it is relevant to what they ask):\n"
        + '\n'.join(f'- {k}' for k in known(person, clock().get('sprint'))) +
        f"\n\nHOW YOU BEHAVE: {person.get('style', 'Busy but helpful.')} Answer only what was asked, in one to four sentences, "
        "in plain chat style. Do not volunteer unrelated facts. If you do not know, say so and, if it fits, name who might. "
        "Never mention that you are an AI, a simulation or a prompt.\n\n"
        f"CONVERSATION SO FAR (oldest first):\n{history or '(none)'}\n\nNEW MESSAGE FROM THEM: {message}\n\nYour reply:")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('CLAUDE', 'LIVING_MEMORY'))}
    env['LIVING_MEMORY_ROOT'] = str(RUN / 'stores' / '_npc')
    args = [claude, '-p', '--model', 'haiku', '--output-format', 'json', '--max-budget-usd', '0.2',
            '--settings', json.dumps({'disableAllHooks': True, 'autoMemoryEnabled': False}),
            '--disallowedTools', 'Bash', 'PowerShell', 'Read', 'Write', 'Edit', 'Glob', 'Grep', 'WebFetch', 'WebSearch',
            'Agent', 'Task', 'NotebookEdit']
    room = RUN / 'npcroom'
    room.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    r = subprocess.run(args, input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       cwd=room, env=env, timeout=180)
    try:
        out = json.loads(r.stdout)
    except ValueError:
        out = {}
    text = (out.get('result') or '').strip() or f"(no reply from {person['name']} right now)"
    with open(RUN / 'costs.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps({'key': f"chat/{ME}/{person['handle']}", 'agent': ME, 'model': 'haiku',
                            'cost_usd': out.get('total_cost_usd'), 'seconds': round(time.time() - t0, 1), 'session_hash': None}) + '\n')
    return text


def main(argv):
    people = load()
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__.replace('{{WORKSPACE}}', str(RUN / 'workspace')))
        return 0
    cmd = argv[0]
    if cmd == 'people':
        for p in people:
            print(f"{p['name']} (@{p['handle']}): {p['role']}")
        return 0
    if cmd in ('ask', 'history') and len(argv) >= 2:
        person = find(people, argv[1])
        now = clock()
        thread = read_thread(person)
        if cmd == 'history':
            visible = [r for r in thread if r.get('sprint') == now.get('sprint')]
            if not visible:
                print(f"No messages with {person['name']} this sprint.")
            for r in visible:
                print(f"[{r['label']}] {'you' if r['who'] == 'agent' else person['name']}: {r['text']}")
            return 0
        if len(argv) < 3 or not argv[2].strip():
            sys.exit('Usage: team_chat.py ask "Name" "message"')
        message = ' '.join(argv[2:]).strip()
        stamp = {'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'sprint': now.get('sprint'), 'label': now.get('label')}
        append(person, {**stamp, 'who': 'agent', 'text': message})
        asker = os.environ.get('SIM_AGENT_NAME') or ME
        text = reply(person, thread, message, asker)
        append(person, {**stamp, 'who': 'npc', 'text': text})
        print(f"{person['name']}: {text}")
        return 0
    print(__doc__.replace('{{WORKSPACE}}', str(RUN / 'workspace')))
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
