"""Run the CI server's ci-lint rules locally: py "{{WORKSPACE}}/bin/lint.py" PATH_TO_REPO"""
import json, re, sys
from pathlib import Path
rules = json.loads((Path(__file__).with_name('ci-rules.json')).read_text(encoding='utf-8'))['lint']
repo = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve(); bad = 0
for r in rules:
    rx = re.compile(r['pattern'])
    for f in repo.glob(r['glob']):
        if not f.is_file() or 'target' in f.relative_to(repo).parts: continue
        for i, line in enumerate(f.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
            if rx.search(line): bad += 1; print(f"{r['id']}: {f.relative_to(repo).as_posix()}:{i}: {line.strip()[:120]} ({r['desc']})")
print('ci-lint: OK' if not bad else f'ci-lint: {bad} violation(s)'); sys.exit(1 if bad else 0)
