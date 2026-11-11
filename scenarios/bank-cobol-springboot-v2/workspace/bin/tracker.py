"""Harbor Point tracker (Jira stand-in): unique LH keys, one Markdown file per ticket.

    py "{{WORKSPACE}}/bin/tracker.py" new "Title" [--owner "Name"]
    py "{{WORKSPACE}}/bin/tracker.py" list [--status STATUS] [--owner NAME]
    py "{{WORKSPACE}}/bin/tracker.py" show LH-12
Edit ticket files directly to change Status, Owner, Description, Acceptance criteria and Notes.
"""
import os, re, sys, time
from datetime import date
from pathlib import Path

HOME = Path(__file__).resolve().parents[1] / 'tracker'

def _key():
    lock = HOME / '.lock'
    for _ in range(200):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY); break
        except FileExistsError:
            time.sleep(0.05)
    else:
        sys.exit('tracker busy, try again')
    try:
        nums = [int(m[1]) for p in HOME.glob('LH-*.md') if (m := re.match(r'LH-(\d+)', p.name))]
        counter = HOME / '.next'
        n = max(nums + [int(counter.read_text() or 0) if counter.exists() else 0]) + 1
        counter.write_text(str(n))
        return f'LH-{n}'
    finally:
        os.close(fd); os.unlink(lock)

def slug(t): return re.sub(r'[^a-z0-9]+', '-', t.lower()).strip('-')[:50]

def main(a):
    HOME.mkdir(exist_ok=True)
    if not a or a[0] in ('-h', '--help'): print(__doc__); return 0
    if a[0] == 'new' and len(a) > 1:
        owner = a[a.index('--owner') + 1] if '--owner' in a else 'Unassigned'
        key = _key(); p = HOME / f'{key}-{slug(a[1])}.md'
        p.write_text(f"# {key} {a[1]}\n\nStatus: Todo\nOwner: {owner}\nCreated: {date.today()}\n\n## Description\n\n## Acceptance criteria\n\n## Notes\n", encoding='utf-8')
        print(f'{key} created: {p}'); return 0
    if a[0] == 'list':
        want_s = a[a.index('--status') + 1].lower() if '--status' in a else None
        want_o = a[a.index('--owner') + 1].lower() if '--owner' in a else None
        for p in sorted(HOME.glob('LH-*.md'), key=lambda p: int(re.match(r'LH-(\d+)', p.name)[1])):
            t = p.read_text(encoding='utf-8', errors='replace')
            s = (re.search(r'(?m)^Status:\s*(.+)$', t) or [None, '?'])[1].strip(); o = (re.search(r'(?m)^Owner:\s*(.+)$', t) or [None, '?'])[1].strip()
            if (want_s and want_s not in s.lower()) or (want_o and want_o not in o.lower()): continue
            print(f"{t.splitlines()[0].lstrip('# ')}  [{s}] {o}")
        return 0
    if a[0] == 'show' and len(a) > 1:
        hits = list(HOME.glob(f'{a[1]}-*.md')) + list(HOME.glob(f'{a[1]}.md'))
        if not hits: sys.exit(f'{a[1]} not found')
        print(hits[0].read_text(encoding='utf-8')); return 0
    print(__doc__); return 2

if __name__ == '__main__': raise SystemExit(main(sys.argv[1:]))
