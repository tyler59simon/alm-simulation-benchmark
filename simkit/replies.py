"""What an agent actually replied, read from its stream-json transcript.

Two things make the transcript's last `result` the wrong place to look:
- Living Memory's Stop reminder can make the agent do memory housekeeping after it has answered, so the last message
  becomes "I saved a note; my answers are above".
- An agent that left a background command running gets a second, one-turn `result` when that command times out.
The reply is therefore read from the first `result`, and when the agent's last steps were only Living Memory calls,
the text from before that housekeeping is included."""
import json
from pathlib import Path

from .common import lm_call


def events(path):
    try:
        lines = Path(path).read_text(encoding='utf-8', errors='replace').splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            out.append(ev)
    return out


def _until_first_result(evs):
    for i, ev in enumerate(evs):
        if ev.get('type') == 'result':
            return evs[:i], ev
    return evs, None


def _items(evs):
    """Assistant output in order: ('text', str) or ('tool', is_living_memory_call)."""
    items = []
    for ev in evs:
        if ev.get('type') != 'assistant':
            continue
        content = (ev.get('message') or {}).get('content') or []
        for c in content if isinstance(content, list) else []:
            if c.get('type') == 'text' and (c.get('text') or '').strip():
                items.append(('text', c['text']))
            elif c.get('type') == 'tool_use':
                items.append(('tool', bool(lm_call((c.get('input') or {}).get('command')))))
    return items


def final_reply(path, default=''):
    """The reply to the task: the first result's text, or, when the agent's last tool calls were all Living Memory
    calls, every text it wrote after its last other tool call."""
    before, res = _until_first_result(events(path))
    items = _items(before)
    last_work = max((i for i, (kind, lm) in enumerate(items) if kind == 'tool' and not lm), default=-1)
    tail = items[last_work + 1:]
    if any(kind == 'tool' for kind, _ in tail):
        texts = [v for kind, v in tail if kind == 'text']
        if texts:
            return '\n\n'.join(texts)
    return ((res or {}).get('result') or '') or default


def _json_objects(text):
    dec, i = json.JSONDecoder(), 0
    while True:
        i = text.find('{', i)
        if i < 0:
            return
        try:
            v, end = dec.raw_decode(text, i)
            if isinstance(v, dict):
                yield v
            i = end
        except ValueError:
            i += 1


def json_reply(path, field):
    """The last JSON object holding `field` anywhere in the agent's texts or results (latest first), else None."""
    texts = []
    for ev in events(path):
        if ev.get('type') == 'result' and isinstance(ev.get('result'), str):
            texts.append(ev['result'])
        texts += [v for kind, v in _items([ev]) if kind == 'text']
    for text in reversed(texts):
        found = [o for o in _json_objects(text) if field in o]
        if found:
            return found[-1]
    return None
