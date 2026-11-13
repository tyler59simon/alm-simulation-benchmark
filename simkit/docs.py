"""The run log: docs/ pages in Markdown and HTML, generated from runs/*/ (manifest, metrics, probes), hand-written notes
in docs/notes/ and the Living Memory repo's merge history. Numbers are never typed by hand; notes are never overwritten.

    python -I sim.py docs

Notes (all optional): docs/notes/index.md, docs/notes/runs/<run folder>.md, docs/notes/analysis/<version>.md and
docs/notes/living-memory-changes.md. Links inside notes are relative to the page they appear on and point at .md files;
the HTML pages get the same links with .html."""
import html
import math
import re
import statistics
import subprocess
from datetime import datetime
from pathlib import Path

from . import analyze
from .common import HOME, RUNS, Run, clean_env, config, read_json

DOCS = HOME / 'docs'
NOTES = DOCS / 'notes'
ARM = {'off': 'A0', 'builtin': 'A1', 'on': 'C'}
ARM_DESC = {'A0': 'memory off', 'A1': 'Claude Code auto-memory', 'C': 'Living Memory'}
DETECT = 0.10   # probe-score difference the power estimate is sized for
Z = 1.959964 + 0.841621   # alpha 0.05 two-sided, power 0.8


# ---------------- data ----------------
def _dt(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def version_of(scenario):
    m = re.search(r'-v(\d+)$', scenario or '')
    return f'v{m[1]}' if m else 'v1'


class RunInfo:
    def __init__(self, path):
        self.path, self.name = path, path.name
        self.man = read_json(path / 'manifest.json', {}) or {}
        self.met = read_json(path / 'metrics.json', {}) or {}
        self.created, self.finished = _dt(self.man.get('created')), _dt(self.man.get('finished'))
        self.scenario = self.man.get('scenario', '')
        self.version = version_of(self.scenario)
        self.memory = (self.man.get('options') or {}).get('memory', 'on')
        self.arm = ARM.get(self.memory, self.memory)
        seed = re.search(r'-s(\d+)$', self.man.get('label') or '')
        self.short = self.arm + (f' seed {seed[1]}' if seed else '')
        self.title = f'{self.version} {self.short}'
        self.slug = f'runs/{self.name}'
        try:
            self.run = Run(path)
        except (OSError, ValueError, KeyError, TypeError):
            self.run = None

    @property
    def truth(self):
        return (self.run.truth if self.run else {}) or {}


def load_runs(root=RUNS):
    runs = [RunInfo(p) for p in sorted(Path(root).glob('*')) if (p / 'manifest.json').exists() and (p / 'metrics.json').exists()]
    return sorted(runs, key=lambda r: r.created or datetime.min)


def lm_prs(repo):
    """Merges on the Living Memory repo's main: [{'sha', 'when', 'number', 'title'}], oldest first."""
    if not repo or not Path(repo).is_dir():
        return None
    r = subprocess.run(['git', 'log', '--first-parent', 'main', '--format=%h%x1f%cI%x1f%s%x1f%b%x1e'], cwd=repo,
                       env=clean_env({'GIT_TERMINAL_PROMPT': '0'}), capture_output=True, text=True, encoding='utf-8', errors='replace')
    out = []
    for rec in r.stdout.split('\x1e'):
        parts = rec.strip('\n').split('\x1f')
        if len(parts) < 4 or not parts[0]:
            continue
        sha, when, subject, body = parts
        m = re.match(r'Merge pull request #(\d+)', subject)
        if m:
            number, title = int(m[1]), (body.strip().splitlines() or [subject])[0]
        else:
            m = re.search(r'\(#(\d+)\)\s*$', subject)
            number, title = (int(m[1]) if m else None), re.sub(r'\s*\(#\d+\)\s*$', '', subject)
        out.append({'sha': sha.strip(), 'when': _dt(when), 'number': number, 'title': title.strip()})
    return sorted(out, key=lambda p: p['when'])


def pr_windows(runs, prs):
    """({run name: PRs merged after the previous run and before this one}, PRs after the last run). PRs before the
    first run are that run's window: the Living Memory it started from."""
    windows, i = {r.name: [] for r in runs}, 0
    for p in prs or []:
        while i < len(runs) and runs[i].created and runs[i].created <= p['when']:
            i += 1
        if i < len(runs):
            windows[runs[i].name].append(p)
        else:
            break
    later = [p for p in prs or [] if not runs or (runs[-1].created and p['when'] > runs[-1].created)]
    return windows, later


def pr_label(p):
    return (f"#{p['number']} " if p['number'] else '') + p['title']


# ---------------- formatting ----------------
def f(v, nd=3):
    if v is None or v == '':
        return '-'
    if isinstance(v, bool):
        return 'yes' if v else 'no'
    if isinstance(v, int):
        return f'{v:,}'
    if isinstance(v, float):
        return f'{v:,.{nd}f}'.rstrip('0').rstrip('.') if nd else f'{v:,.0f}'
    return str(v)


def money(v, nd=2):
    return '-' if v is None else f'${v:,.{nd}f}'


def when(d):
    return d.strftime('%Y-%m-%d %H:%M UTC') if d else '-'


def duration(a, b):
    if not (a and b):
        return '-'
    mins = int((b - a).total_seconds() // 60)
    return f'{mins // 60} h {mins % 60} min' if mins >= 60 else f'{mins} min'


def scrub(text):
    """No local paths or user names in the public log: the home folder becomes ~."""
    home = str(Path.home())
    for h in {home, home.replace('\\', '/'), home.replace('\\', '\\\\')}:
        text = re.sub(re.escape(h), '~', text, flags=re.I)
    return text


# ---------------- blocks: one model, two renderers ----------------
# A page is {'slug', 'title', 'eyebrow', 'sub', 'crumbs': [(label, slug|None)], 'nav', 'chips', 'sections', 'rail', 'strip'}.
# A section is {'title', 'id', 'blocks'}; blocks are tuples: ('p', md), ('table', headers, rows), ('list', [md]),
# ('tiles', [(label, value, sub)]), ('rows', [{'label', 'sub', 'slug', 'chip', 'meta'}]), ('note', md), ('kv', [(k, v)]),
# ('featured', {...}).

def md_table(headers, rows):
    esc = lambda c: f(c).replace('|', '\\|').replace('\n', ' ')   # noqa: E731
    return '\n'.join(['| ' + ' | '.join(esc(h) for h in headers) + ' |', '|' + '---|' * len(headers)]
                     + ['| ' + ' | '.join(esc(c) for c in row) + ' |' for row in rows])


def md_link(slug, page_slug):
    depth = page_slug.count('/')
    return '../' * depth + slug + '.md'


def render_md(page):
    out = [f"# {page['title']}", '', f"_{page['eyebrow']}_" if page.get('eyebrow') else '']
    if page.get('sub'):
        out += ['', page['sub']]
    for sec in page['sections'] + page.get('rail', []):
        out += ['', f"## {sec['title']}", '']
        for b in sec['blocks']:
            kind = b[0]
            if kind == 'p':
                out += [b[1], '']
            elif kind == 'note':
                out += [b[1].strip(), '']
            elif kind == 'table':
                out += [md_table(b[1], b[2]), '']
            elif kind == 'list':
                out += [f'- {x}' for x in b[1]] + ['']
            elif kind == 'tiles':
                out += [md_table([t[0] for t in b[1]], [[t[1] for t in b[1]]]), '']
            elif kind == 'kv':
                out += [f'- **{k}:** {v}' for k, v in b[1]] + ['']
            elif kind == 'rows':
                out += [f"- [{r['label']}]({md_link(r['slug'], page['slug'])})" + (f" ({r['chip']})" if r.get('chip') else '')
                        + (f": {r['sub']}" if r.get('sub') else '') + (f" ({r['meta']})" if r.get('meta') else '') for r in b[1]] + ['']
            elif kind == 'featured':
                ft = b[1]
                out += [f"**[{ft['title']}]({md_link(ft['slug'], page['slug'])})**: {ft['sub']}", '',
                        md_table([t[0] for t in ft['tiles']], [[t[1] for t in ft['tiles']]]), '']
    if page.get('strip'):
        out += ['', '_' + ' · '.join(page['strip']) + '_']
    return scrub('\n'.join(out).rstrip() + '\n')


ICONS = {
    'album': '<path d="M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z"/>',
    'runs': '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    'analysis': '<path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 5-6"/>',
    'lm': '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="8" r="2.5"/><path d="M6 8.5v7M18 10.5c0 4-6 3-11.5 5.5"/>',
    'arrow': '<path d="M5 12h14M13 6l6 6-6 6"/>',
    'run': '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z"/>',
    'mark': '<path d="M12 2 21 7v10l-9 5-9-5V7z"/><path d="m12 7 4.5 2.5v5L12 17l-4.5-2.5v-5z"/>',
}


def svg(name, size=20):
    return (f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


def inline(text, md_links=True):
    """Inline Markdown (code, bold, links) to HTML; relative .md links become .html."""
    t = html.escape(str(text), quote=False)
    t = re.sub(r'`([^`]+)`', r'<code>\1</code>', t)
    t = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', t)
    def link(m):
        href = m[2]
        if md_links and not re.match(r'[a-z]+:', href):
            href = re.sub(r'\.md(#|$)', r'.html\1', href)
        return f'<a href="{html.escape(href, quote=True)}">{m[1]}</a>'
    return re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)', link, t)


def note_blocks(text):
    """The Markdown subset hand-written notes use: headings, paragraphs, lists, tables and fenced code, as HTML."""
    out, lines, i = [], text.strip('\n').splitlines(), 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith('```'):
            j = i + 1
            while j < len(lines) and not lines[j].startswith('```'):
                j += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(lines[i + 1:j]))}</code></pre>")
            i = j + 1
        elif re.match(r'#{1,4} ', line):
            level = min(4, len(line) - len(line.lstrip('#')) + 1)
            out.append(f"<h{level}>{inline(line.lstrip('#').strip())}</h{level}>")
            i += 1
        elif line.lstrip().startswith(('- ', '* ')):
            items = []
            while i < len(lines) and lines[i].lstrip().startswith(('- ', '* ')):
                items.append(lines[i].lstrip()[2:])
                i += 1
                while i < len(lines) and lines[i].startswith('  ') and lines[i].strip() and not lines[i].lstrip().startswith(('- ', '* ')):
                    items[-1] += ' ' + lines[i].strip()
                    i += 1
            out.append('<ul>' + ''.join(f'<li>{inline(x)}</li>' for x in items) + '</ul>')
        elif line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].startswith('|'):
                cells = [c.strip() for c in re.split(r'(?<!\\)\|', lines[i].strip().strip('|'))]
                if not all(re.fullmatch(r':?-+:?', c) for c in cells):
                    rows.append([c.replace('\\|', '|') for c in cells])
                i += 1
            if rows:
                out.append(html_table(rows[0], rows[1:], raw=True))
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(r'(#{1,4} |```|\||\s*[-*] )', lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{inline(' '.join(para))}</p>")
    return '\n'.join(out)


def _numeric(cell):
    return bool(re.fullmatch(r'[-+]?\$?[\d,]*\.?\d+%?( ± .*)?|-', str(cell).strip()))


def html_table(headers, rows, raw=False):
    cell = (lambda c: inline(c)) if raw else (lambda c: inline(f(c)))
    head = ''.join(f'<th>{inline(h)}</th>' for h in headers)
    body = ''.join('<tr>' + ''.join(f'<td class="{"num" if _numeric(f(c)) else ""}">{cell(c)}</td>' for c in row) + '</tr>'
                   for row in rows)
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def chip(text, kind=''):
    return f'<span class="status-chip {kind}">{inline(text)}</span>' if text else ''


def arm_kind(arm):
    return {'C': 'arm-c', 'A1': 'arm-a1', 'A0': 'arm-a0'}.get(arm, '')


def html_block(b, root):
    kind = b[0]
    if kind == 'p':
        return f'<p>{inline(b[1])}</p>'
    if kind == 'note':
        return f'<div class="prose">{note_blocks(b[1])}</div>'
    if kind == 'table':
        return html_table(b[1], b[2])
    if kind == 'list':
        return '<ul class="plain">' + ''.join(f'<li>{inline(x)}</li>' for x in b[1]) + '</ul>'
    if kind == 'tiles':
        return '<div class="tiles">' + ''.join(
            f'<div class="tile"><div class="tile-label">{inline(t[0])}</div><div class="tile-value">{inline(t[1])}</div>'
            + (f'<div class="tile-sub">{inline(t[2])}</div>' if len(t) > 2 and t[2] else '') + '</div>' for t in b[1]) + '</div>'
    if kind == 'kv':
        return '<dl class="kv">' + ''.join(f'<dt>{inline(k)}</dt><dd>{inline(v)}</dd>' for k, v in b[1]) + '</dl>'
    if kind == 'rows':
        return ''.join(
            f'<a class="arrow-row" href="{root}{r["slug"]}.html"><span class="row-icon">{svg(r.get("icon", "run"))}</span>'
            f'<span class="row-label"><span class="row-title">{inline(r["label"])}</span>'
            + (f'<span class="row-sub">{inline(r["sub"])}</span>' if r.get('sub') else '') + '</span>'
            + chip(r.get('chip'), r.get('chip_kind', '')) + (f'<span class="row-meta">{inline(r["meta"])}</span>' if r.get('meta') else '')
            + f'<span class="row-arrow">{svg("arrow", 18)}</span></a>' for r in b[1])
    if kind == 'featured':
        ft = b[1]
        return (f'<div class="featured"><div class="eyebrow">{inline(ft["eyebrow"])}</div><h3><a href="{root}{ft["slug"]}.html">{inline(ft["title"])}</a></h3>'
                f'<div class="page-meta">{"".join(chip(c, k) for c, k in ft["chips"])}</div><p class="muted">{inline(ft["sub"])}</p>'
                + html_block(('tiles', ft['tiles']), root)
                + f'<a class="arrow-link" href="{root}{ft["slug"]}.html">Open the run {svg("arrow", 18)}</a></div>')
    raise ValueError(kind)


CSS_FONTS = ('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600'
             '&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap')


def render_html(page, nav):
    root = '../' * page['slug'].count('/')
    def section(sec):
        sid = f' id="{sec["id"]}"' if sec.get('id') else ''
        return (f'<section class="section"{sid}><div class="section-head"><h2>{inline(sec["title"])}</h2></div>'
                + '\n'.join(html_block(b, root) for b in sec['blocks']) + '</section>')
    nav_html = ''.join(
        f'<a class="nav-item{" on" if key == page["nav"] else ""}" href="{root}{href}">{svg(icon)}<span>{inline(label)}</span></a>'
        for key, label, href, icon in nav)
    crumbs = '<span class="crumb-sep">/</span>'.join(
        (f'<a class="crumb" href="{root}{slug}.html">{inline(label)}</a>' if slug else f'<span class="crumb here">{inline(label)}</span>')
        for label, slug in page['crumbs'])
    main = '\n'.join(section(s) for s in page['sections'])
    body = (f'<div class="split"><div class="split-main">{main}</div><aside class="split-rail">'
            + '\n'.join(section(s) for s in page['rail']) + '</aside></div>') if page.get('rail') else f'<div class="stack">{main}</div>'
    strip = ('<footer class="status-strip">' + ''.join(f'<span>{inline(s)}</span>' for s in page['strip']) + '</footer>') if page.get('strip') else ''
    doc = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(page["title"])} - ALM benchmark run log</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{CSS_FONTS.replace('&', '&amp;')}">
<link rel="stylesheet" href="{root}album.css">
</head>
<body>
<div class="shell">
<aside class="sidebar">
<a class="brand-block" href="{root}index.html"><span class="brand-mark">{svg("mark", 34)}</span><span><span class="brand-name">ALM Benchmark</span><span class="brand-sub">Run log</span></span></a>
<nav class="nav">{nav_html}</nav>
<div class="sidebar-foot muted small">Generated by <code>sim.py docs</code></div>
</aside>
<div class="main">
<header class="topbar"><div class="crumbs">{crumbs}</div></header>
<main class="page">
<div class="page-head"><div class="page-title">
{f'<div class="eyebrow">{inline(page["eyebrow"])}</div>' if page.get("eyebrow") else ''}
<h1>{inline(page["title"])}</h1>
{f'<p class="page-sub">{inline(page["sub"])}</p>' if page.get("sub") else ''}
{('<div class="page-meta">' + ''.join(chip(c, k) for c, k in page.get("chips", [])) + '</div>') if page.get("chips") else ''}
</div></div>
{body}
{strip}
</main>
</div>
</div>
</body>
</html>
'''
    return scrub(doc)


# ---------------- pages ----------------
def note(path):
    p = NOTES / path
    return p.read_text(encoding='utf-8') if p.exists() else None


def headline(r):
    m = r.met
    q, qr, pr, t = m.get('quiz') or {}, m.get('quiz_repo') or {}, m.get('probes') or {}, m.get('totals') or {}
    work = (m.get('efficiency') or {}).get('work') or {}
    return [('Probe score', f(pr.get('mean_score')), f"{pr.get('probes') or 0} probes" if pr.get('probes') else 'no probes'),
            ('Quiz with repo', f(qr.get('score_should_know')), 'should-know'),
            ('Quiz memory only', f(q.get('score_should_know')), 'should-know'),
            ('Work cost', money(t.get('work_cost_usd')), f"{money(work.get('cost_usd'), 3)} per session" if work else ''),
            ('Sessions', f(t.get('sessions')), f"{f(t.get('work_sessions'))} work")]


def run_chips(r):
    return [(r.arm + ' ' + ARM_DESC.get(r.arm, ''), arm_kind(r.arm)), (r.scenario, ''),
            ('finished' if r.finished else 'unfinished', 'succeeded' if r.finished else 'waiting')]


def run_page(r, prev, window):
    m, run = r.met, r.run
    t, eff = m.get('totals') or {}, m.get('efficiency') or {}
    secs = [{'title': 'Headline', 'blocks': [('tiles', headline(r))]}]
    n = note(f'runs/{r.name}.md')
    if n:
        secs.append({'title': 'Log entry', 'blocks': [('note', n)]})
    secs.append({'title': 'Cost', 'blocks': [('table', ['Who spent it', 'Dollars'], [
        ['Work sessions (team, merge resolves)', money(t.get('work_cost_usd'))],
        ['Simulated colleagues (chat)', money(t.get('chat_cost_usd'))],
        ['Harness (quizzes, grading, probe judging)', money(t.get('harness_cost_usd'))],
        ['Run total', money(t.get('cost_usd'))], ['Sessions without a recorded cost', f(t.get('cost_unknown_sessions'))]])]})
    eff_rows = [[k.replace('_', ' '), e.get('sessions'), money(e.get('cost_usd'), 3), e.get('turns'), e.get('tool_calls'), e.get('seconds'),
                 (e.get('tokens') or {}).get('cache_read_input_tokens'), (e.get('tokens') or {}).get('output_tokens')]
                for k, e in eff.items() if k != 'chat' and isinstance(e, dict)]
    if eff_rows:
        secs.append({'title': 'Efficiency per session', 'blocks': [('table', ['Kind', 'Sessions', '$/session', 'Turns', 'Tool calls',
                                                                               'Seconds', 'Cache-read tokens', 'Output tokens'], eff_rows)]})
    facts, truth = m.get('facts') or {}, (r.truth.get('facts') or {})
    q, qr = m.get('quiz') or {}, m.get('quiz_repo') or {}
    if q or qr:
        rows = [[fid, (truth.get(fid) or {}).get('summary', ''), (q.get('by_fact_should_know') or {}).get(fid),
                 (qr.get('by_fact_should_know') or {}).get(fid), len(fc.get('stores_with_fact') or []), fc.get('should_know_coverage'),
                 ', '.join(fc.get('stores_with_stale_only') or []) or '-'] for fid, fc in facts.items()]
        blocks = [('p', 'Should-know scores per fact (1 = every agent who should know it answered correctly). Memory only: '
                        'answered from memory with the repo denied. With repo: the agent\'s clone and tools available.'),
                  ('table', ['Fact', 'What it is', 'Memory only', 'With repo', 'Stores holding it', 'Should-know coverage', 'Stale-only stores'], rows)]
        extra = []
        for label, qq in (('Memory only', q), ('With repo', qr)):
            if qq:
                extra.append(f"{label}: all {f(qq.get('score_all'))}, should-know {f(qq.get('score_should_know'))}, failure kinds "
                             + (', '.join(f'{k} {v}' for k, v in (qq.get('failure_kinds_should_know') or {}).items()) or '-')
                             + f", stale answers {len(qq.get('stale_answers') or [])}, missing {f(qq.get('missing'))}")
        blocks.append(('list', extra))
        secs.append({'title': 'Quizzes', 'blocks': blocks})
    prow = []
    for p in sorted((r.path / 'probes').glob('*.json')) if (r.path / 'probes').exists() else []:
        d = read_json(p, {}) or {}
        checks = d.get('checks') or []
        prow.append([d.get('id'), d.get('agent'), ', '.join(d.get('facts') or []), d.get('score'),
                     f"{sum(1 for c in checks if c.get('pass'))}/{len(checks)}",
                     'missing' if d.get('missing') else 'judge error' if d.get('judge_error') else '-'])
    if prow:
        secs.append({'title': 'Work probes', 'blocks': [
            ('p', 'Ordinary sprint-4 requests that silently need earlier knowledge; score is the passed share of weighted checks.'),
            ('table', ['Probe', 'Agent', 'Facts', 'Score', 'Checks passed', 'Flag'], prow)]})
    rd, rf, sa, ru, ah = (m.get(k) or {} for k in ('rediscovery', 'repeat_failures', 'stale_actions', 'ramp_up', 'app_history'))
    if rd or rf:
        secs.append({'title': 'Work metrics', 'blocks': [('table', ['Measure', 'Value', 'What it counts'], [
            ['Re-reads per work session', rd.get('mean_rereads'), 'files and searches the agent had read in an earlier session'],
            ['Re-read share', rd.get('reread_share'), 're-reads over all reads'],
            ['Tool calls before the first change', rd.get('mean_calls_before_change'), 'exploration before the first edit or commit'],
            ['Own repeated failures', rf.get('own_repeat_sessions'), 'an error the agent already hit in an earlier session'],
            ['Team repeated failures', rf.get('team_repeat_sessions'), 'an error a teammate hit earlier'],
            ['Repeated failed Living Memory calls', (rf.get('lm_own_repeat_sessions') or 0) + (rf.get('lm_team_repeat_sessions') or 0) if rf else None,
             'memory-tool friction, kept apart from work mistakes'],
            ['Stale code lines', sa.get('stale_lines'), 'added code matching an outdated decision (heuristic)'],
            ['Joiner cost ratio', ru.get('mean_cost_ratio'), "joiners' first sessions vs the team median (1 = same)"],
            ['App-check regressions', ah.get('regression_count'), 'a check on main that passed and later failed']])]})
    mk = m.get('mistakes') or {}
    if mk:
        rows = []
        for mid, x in mk.items():
            repeats = x.get('repeat_sessions') if x.get('kind') == 'result' else x.get('repeats') if x.get('kind') == 'lint' else x.get('repeats_after_capture')
            rows.append([mid, x.get('desc', ''), x.get('total'), repeats])
        secs.append({'title': 'Planted mistakes', 'blocks': [('table', ['Trap', 'What it is', 'Hits', 'Repeats'], rows)]})
    if (t.get('notes_active') or t.get('lm_calls')) and r.memory == 'on':
        cur, ptr, hl = m.get('currency') or {}, m.get('pointers') or {}, m.get('hook_latency') or {}
        rows = [['Active notes', t.get('notes_active')], ['Maps', t.get('maps')], ['Noise-like notes', t.get('noise_notes')],
                ['Status snapshot notes', t.get('status_snapshots')],
                ['Living Memory calls', t.get('lm_calls')], ['Calls per work session', t.get('lm_calls_per_work_session')],
                ['CLI errors', t.get('lm_cli_errors')], ['Note updates', cur.get('updates')], ['Superseded notes', cur.get('supersedes')],
                ['Decision docs with a pointer note', f"{f(ptr.get('with_pointer'))} of {f(ptr.get('docs'))}"]]
        rv = m.get('review')
        if rv:
            rows += [['Review worklist precision', f"{f(rv.get('worklist_precision'))} ({f(rv.get('judged'))} judged, {f(rv.get('unjudged'))} unjudged)"],
                     ['Review plans applied', rv.get('plans_applied')]]
        rows += [[f'Hook {e} p50 / p95 ms', f"{f(v.get('p50'))} / {f(v.get('p95'))} (n={f(v.get('n'))})"] for e, v in hl.items()]
        secs.append({'title': 'Memory stores', 'blocks': [('table', ['Measure', 'Value'], rows)]})
    ci, mg, app = m.get('ci') or {}, m.get('merges') or {}, m.get('app') or {}
    rows = [['CI runs green', f"{f(ci.get('green'))} of {f(ci.get('runs'))}"], ['Last CI', 'green' if ci.get('last_ok') else 'red'],
            ['Merge attempts', mg.get('attempts')], ['Conflicts on first try', mg.get('conflicts_first_try')],
            ['Unresolved merges', mg.get('failed_final')], ['Files swept up uncommitted', mg.get('files_swept_uncommitted')]]
    blocks = [('table', ['Measure', 'Value'], rows)]
    if app.get('checks'):
        blocks.append(('table', ['Fact', 'Final code check', 'Result'], [[c['fact'], c['desc'], 'ok' if c['pass'] else 'missing'] for c in app['checks']]))
    secs.append({'title': 'CI, merges and final code', 'blocks': blocks})

    man, lm = r.man, r.man.get('living_memory') or {}
    facts_kv = [('Scenario', f'`{r.scenario}` ({r.version})'), ('Arm', f'{r.arm}: {ARM_DESC.get(r.arm, r.memory)}'),
                ('Label', man.get('label') or '-'), ('Semantic search', f((man.get('options') or {}).get('semantic', False))),
                ('Started', when(r.created)), ('Finished', when(r.finished)), ('Duration', duration(r.created, r.finished)),
                ('Claude Code', man.get('claude_code', '-').replace(' (Claude Code)', '')), ('Living Memory tree', f"`{lm.get('tree_sha256', '-')}`"),
                ('Harness', f"`{man.get('harness_sha256', '-')}`"), ('Scenario files', f"`{man.get('scenario_sha256', '-')}`")]
    rail = [{'title': 'Run facts', 'blocks': [('kv', facts_kv)]}]
    if window is not None:
        if prev is None:
            items = [f"Main at {pr_label(window[-1])} ({len(window)} merges before this first run)"] if window else ['No merges before this run']
        else:
            items = [pr_label(p) for p in window] or ['No merges since the previous run']
        if r.memory != 'on':
            items.append('Living Memory was installed but switched off in this arm.')
        rail.append({'title': 'Living Memory before this run', 'blocks': [('list', items)]})
    rail.append({'title': 'Compare', 'blocks': [('rows', [{'label': f'Scenario {r.version} analysis', 'slug': f'analysis/{r.version}', 'icon': 'analysis'}]
                                                 + ([{'label': f'Previous run: {prev.title}', 'slug': prev.slug}] if prev else []))]})
    return {'slug': r.slug, 'title': r.title, 'eyebrow': f'{r.scenario} · {when(r.created)}',
            'sub': f"Run `{r.name}`", 'crumbs': [('Album', 'index'), ('Runs', None), (r.title, None)], 'nav': 'runs',
            'chips': run_chips(r), 'sections': secs, 'rail': rail,
            'strip': [man.get('claude_code', ''), f"Living Memory tree {lm.get('tree_sha256', '-')}", f"harness {man.get('harness_sha256', '-')}"]}


def cell(vals):
    vals = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not vals:
        return '-'
    if len(vals) == 1:
        return f(float(vals[0]))
    return f'{statistics.mean(vals):.3g} ± {statistics.stdev(vals):.2g} (n={len(vals)})'


def analysis_page(version, runs):
    arms = {}
    for r in runs:
        arms.setdefault(r.arm, []).append(r)
    names = [a for a in ('A0', 'A1', 'C') if a in arms] + [a for a in arms if a not in ('A0', 'A1', 'C')]
    secs = [{'title': 'Runs in this comparison', 'blocks': [('rows', [
        {'label': r.title, 'slug': r.slug, 'sub': f"{when(r.created)} · {ARM_DESC.get(r.arm, r.memory)}", 'chip': r.arm,
         'chip_kind': arm_kind(r.arm), 'meta': f"work {money((r.met.get('totals') or {}).get('work_cost_usd'))}"} for r in runs])]}]
    n = note(f'analysis/{version}.md')
    if n:
        secs.append({'title': 'Reading', 'blocks': [('note', n)]})
    diffs = [label for label, key in (('scenario files', 'scenario_sha256'), ('harness', 'harness_sha256'), ('Claude Code', 'claude_code'))
             if len({r.man.get(key) for r in runs}) > 1]
    secs.append({'title': 'Comparability', 'blocks': [
        ('p', ('These runs differ in: **' + ', '.join(diffs) + '**. Differences between them can come from those changes, not only from the arm.')
         if diffs else 'Same scenario files, harness and Claude Code version in every run: the arm is the only planned difference.'),
        ('table', ['Run', 'Scenario files', 'Harness', 'Claude Code', 'Living Memory tree'],
         [[r.title, f"`{r.man.get('scenario_sha256')}`", f"`{r.man.get('harness_sha256')}`", (r.man.get('claude_code') or '').replace(' (Claude Code)', ''),
           f"`{(r.man.get('living_memory') or {}).get('tree_sha256')}`"] for r in runs])]})
    by_arm = {a: [r.met for r in arms[a]] for a in names}
    rows = []
    for label, fn in analyze.ARM_METRICS:
        vals = [cell([fn(m) for m in by_arm[a]]) for a in names]
        if any(v != '-' for v in vals):
            rows.append([label] + vals)
    seeds = max(len(v) for v in by_arm.values())
    secs.append({'title': 'Arms side by side', 'blocks': [
        ('p', f"One value per arm when an arm has one run; mean ± sd (n) once it has more seeds. Runs per arm: "
              + ', '.join(f'{a} {len(by_arm[a])}' for a in names) + '.'),
        ('table', ['Metric'] + [f'{a} ({ARM_DESC.get(a, a)})' for a in names], rows)]})
    probe_ids = sorted({pid for ms in by_arm.values() for m in ms for pid in ((m.get('probes') or {}).get('by_probe') or {})},
                       key=lambda s: int(re.sub(r'\D', '', s) or 0))
    if probe_ids:
        means = {a: analyze.per_probe_means(by_arm[a]) for a in names}
        secs.append({'title': 'Probes by arm', 'blocks': [('table', ['Probe'] + names, [[pid] + [means[a].get(pid) for a in names] for pid in probe_ids])]})
        stats = analyze.paired_probe_stats(by_arm)
        if stats:
            rows = [[f"{s['arm']} - {s['ref']}", f"{s['mean']:+.3f}", f"{s['lo']:+.3f} to {s['hi']:+.3f}",
                     f"{s['wins']}/{s['ties']}/{s['losses']}", f"{s['sd']:.3f}",
                     f(math.ceil(Z ** 2 * s['sd'] ** 2 / DETECT ** 2)) if s['sd'] else '-'] for s in stats]
            excl = [f"{s['arm']} vs {s['ref']}" for s in stats if s['lo'] > 0 or s['hi'] < 0]
            secs.append({'title': 'Paired probe differences', 'blocks': [
                ('p', 'Each arm against the first, probe by probe (a probe\'s score averaged over its seeds). The interval is a bootstrap '
                      f'95% interval over probes. Probes needed: how many paired probes would detect a {DETECT:.2f} difference with '
                      'alpha 0.05 and power 0.8, given the spread of the differences seen here.'),
                ('table', ['Comparison', 'Mean difference', '95% interval', 'Wins/ties/losses', 'SD of differences', 'Probes needed'], rows),
                ('p', ('Intervals that exclude zero: ' + ', '.join(excl) + '.') if excl else
                      f'No interval excludes zero: with {len(probe_ids)} probes and {seeds} seed(s) per arm, no arm is shown better or worse.')]})
    fids = list(((runs[0].truth or {}).get('facts') or {}).keys()) or sorted({k for r in runs for k in (r.met.get('facts') or {})})
    qrows = []
    for fid in fids:
        row = [fid]
        for a in names:
            rep = [((m.get('quiz_repo') or {}).get('by_fact_should_know') or {}).get(fid) for m in by_arm[a]]
            mem = [((m.get('quiz') or {}).get('by_fact_should_know') or {}).get(fid) for m in by_arm[a]]
            row += [cell(rep), cell(mem)]
        qrows.append(row)
    secs.append({'title': 'Quiz by fact', 'blocks': [('table', ['Fact'] + [h for a in names for h in (f'{a} with repo', f'{a} memory only')], qrows)]})
    return {'slug': f'analysis/{version}', 'title': f'Scenario {version}', 'eyebrow': f'Analysis · {runs[0].scenario}',
            'sub': f"{len(runs)} runs, arms {', '.join(names)}, from {when(runs[0].created)} to {when(runs[-1].created)}.",
            'crumbs': [('Album', 'index'), ('Analysis', None), (f'Scenario {version}', None)], 'nav': f'analysis-{version}',
            'sections': secs, 'strip': [f'{len(runs)} runs', f'up to {seeds} seed(s) per arm', 'bootstrap seed 0, 2,000 resamples']}


def lm_page(runs, prs):
    windows, later = pr_windows(runs, prs)
    rows, prev = [], None
    for r in runs:
        tree = (r.man.get('living_memory') or {}).get('tree_sha256')
        ptree = (prev.man.get('living_memory') or {}).get('tree_sha256') if prev else None
        w = windows.get(r.name) or []
        if prev is None:
            merged = f"main at {pr_label(w[-1])}" if w else '-'
            flag = 'first run'
        else:
            merged = '; '.join(pr_label(p) for p in w) or 'none'
            flag = ('changed with no merged PR (redeploy or local build)' if tree != ptree and not w else
                    'merged but tree unchanged (not deployed yet)' if w and tree == ptree else 'changed' if tree != ptree else 'same')
        rows.append([f'[{r.title}](runs/{r.name}.md)', when(r.created), 'on' if r.memory == 'on' else 'off', f'`{tree}`', flag, merged])
        prev = r
    secs = []
    n = note('living-memory-changes.md')
    if n:
        secs.append({'title': 'Reading', 'blocks': [('note', n)]})
    secs.append({'title': 'Timeline', 'blocks': [
        ('p', 'Each run with the Living Memory pull requests merged on main since the previous run. Merge time is not deploy time: '
              'the installed tree hash in the run manifest is the evidence of what ran, and it also covers compiled `__pycache__` '
              'files, so a hash can change with no code change.'),
        ('table', ['Run', 'Started', 'LM hooks', 'Installed tree', 'Tree vs previous run', 'PRs merged since the previous run'], rows)]})
    secs.append({'title': 'Merged since the last run (not yet measured)', 'blocks': [
        ('list', [f"{pr_label(p)} ({p['when'].strftime('%Y-%m-%d')})" for p in later] or ['Nothing: the last run measured the current main.'])]})
    return {'slug': 'living-memory-changes', 'title': 'Living Memory changes', 'eyebrow': 'agentic-living-memory main',
            'sub': f"{len(prs)} merges on main; {len(later)} not yet measured by any run.",
            'crumbs': [('Album', 'index'), ('Living Memory changes', None)], 'nav': 'lm', 'sections': secs,
            'strip': [f'{len(prs)} merges', f'{len(runs)} runs']}


def index_page(runs, versions, prs):
    secs = []
    n = note('index.md')
    if n:
        secs.append({'title': 'About this log', 'blocks': [('note', n)]})
    if runs:
        last = runs[-1]
        secs.append({'title': 'Latest run', 'blocks': [('featured', {'title': last.title, 'slug': last.slug, 'chips': run_chips(last),
                                                                     'eyebrow': f'Scenario {last.version} · arm {last.arm}',
                                                                 'sub': f"{last.scenario} · {when(last.created)} · {duration(last.created, last.finished)}",
                                                                 'tiles': headline(last)})]})
    row = lambda r: {'label': r.title, 'slug': r.slug, 'chip': r.arm, 'chip_kind': arm_kind(r.arm),   # noqa: E731
                     'sub': f"{when(r.created)} · {f((r.met.get('totals') or {}).get('sessions'))} sessions · work {money((r.met.get('totals') or {}).get('work_cost_usd'))}",
                     'meta': f"probes {f((r.met.get('probes') or {}).get('mean_score'))}" if (r.met.get('probes') or {}).get('probes') else
                             f"quiz {f(((r.met.get('quiz') or r.met.get('quiz_repo') or {})).get('score_should_know'))}"}
    for v in sorted(versions, reverse=True):
        secs.append({'title': f'Runs: scenario {v}', 'id': f'runs-{v}', 'blocks': [('rows', [row(r) for r in reversed(versions[v])])]})
    secs.append({'title': 'Analysis', 'id': 'analysis', 'blocks': [('rows', [
        {'label': f'Scenario {v}', 'slug': f'analysis/{v}', 'icon': 'analysis', 'sub': f"{len(versions[v])} runs: "
         + ', '.join(sorted({r.arm for r in versions[v]}))} for v in sorted(versions)])]})
    if prs is not None:
        _, later = pr_windows(runs, prs)
        secs.append({'title': 'Living Memory changes', 'blocks': [('rows', [
            {'label': 'Pull requests on the run timeline', 'slug': 'living-memory-changes', 'icon': 'lm',
             'sub': f'{len(prs)} merges on main', 'meta': f'{len(later)} not yet measured'}])]})
    return {'slug': 'index', 'title': 'Run log', 'eyebrow': 'alm-simulation-benchmark',
            'sub': 'Every simulation run, its statistics, the analyses across runs and the Living Memory changes each run measured.',
            'crumbs': [('Album', None)], 'nav': 'index', 'sections': secs,
            'strip': [f'{len(runs)} runs', f'{len(versions)} scenario versions', 'generated from runs/ by sim.py docs']}


def build(root=RUNS, out=DOCS):
    runs = load_runs(root)
    versions = {}
    for r in runs:
        versions.setdefault(r.version, []).append(r)
    repo = config().get('lm_repo')
    prs = lm_prs(repo)
    windows, _ = pr_windows(runs, prs) if prs is not None else ({}, [])
    nav = [('index', 'Album', 'index.html', 'album'),
           ('runs', 'Runs', f'index.html#runs-{max(versions)}' if versions else 'index.html', 'runs')]
    nav += [(f'analysis-{v}', f'Analysis {v}', f'analysis/{v}.html', 'analysis') for v in sorted(versions)]
    if prs is not None:
        nav.append(('lm', 'Living Memory changes', 'living-memory-changes.html', 'lm'))
    pages = [index_page(runs, versions, prs)]
    for i, r in enumerate(runs):
        pages.append(run_page(r, runs[i - 1] if i else None, windows.get(r.name) if prs is not None else None))
    pages += [analysis_page(v, rs) for v, rs in sorted(versions.items())]
    if prs is not None:
        pages.append(lm_page(runs, prs))
    out.mkdir(parents=True, exist_ok=True)
    (out / 'album.css').write_text(CSS, encoding='utf-8', newline='\n')
    written = []
    for page in pages:
        base = out / page['slug']
        base.parent.mkdir(parents=True, exist_ok=True)
        md_name = 'README' if page['slug'] == 'index' else base.name
        (base.parent / f'{md_name}.md').write_text(render_md(page), encoding='utf-8', newline='\n')
        base.with_suffix('.html').write_text(render_html(page, nav), encoding='utf-8', newline='\n')
        written.append(page['slug'])
    skipped = '' if prs is not None else ' (no lm_repo in simkit/config.json: Living Memory changes page skipped)'
    return f"{len(written)} pages ({len(runs)} runs, {len(versions)} analyses) written to {out}{skipped}"


CSS = r"""/* Run log album: the look of the Hivemind app (agentic-hivemind-app/src/App.css), dark only. Generated by sim.py docs. */
:root {
  color-scheme: dark;
  --bg: #1b0626; --bg-alt: #251332; --bg-hover: #341848; --bg-sidebar: #190621; --bg-topbar: #1b0727;
  --bg-code: #170d24; --bg-active: #4c2d64; --fg: #f6f1fa; --fg-soft: #e9def2; --muted: #b7a6c6;
  --border: #3a224c; --border-soft: #291738; --border-strong: #6d5188;
  --accent: #c884f4; --accent-soft: #442558; --primary: #019871; --teal: #01dca4;
  --success: #04cf8a; --warn: #f7ae3a; --warn-fg: #fde329; --warn-bg: #44281c; --warn-border: #b99a2a; --error: #ff7a90;
  --font-sans: "Plus Jakarta Sans", "Segoe UI", system-ui, -apple-system, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, "Cascadia Code", Consolas, monospace;
  font-family: var(--font-sans); font-size: 16px; line-height: 1.5; color: var(--fg); background: var(--bg);
}
* { box-sizing: border-box; scrollbar-width: thin; scrollbar-color: #4c2d64 transparent; }
body { margin: 0; background: var(--bg); }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
code { font-family: var(--font-mono); font-size: .86em; background: var(--bg-code); border: 1px solid var(--border-soft); border-radius: .3rem; padding: 0 .3rem; overflow-wrap: anywhere; }
pre { background: var(--bg-code); border: 1px solid var(--border); border-radius: .5rem; padding: .8rem 1rem; overflow-x: auto; }
pre code { border: none; padding: 0; background: none; }
.muted { color: var(--muted); }
.small { font-size: .86rem; }

.shell { display: grid; grid-template-columns: 15.4rem minmax(0, 1fr); min-height: 100vh; }
.sidebar { position: sticky; top: 0; height: 100vh; background: var(--bg-sidebar); border-right: 1px solid var(--border-soft);
  display: flex; flex-direction: column; gap: .5rem; padding: 1rem .7rem .9rem; }
.brand-block { display: flex; align-items: center; gap: .7rem; padding: 0 .6rem 1.3rem; color: var(--fg); }
.brand-block:hover { text-decoration: none; }
.brand-mark { color: var(--accent); display: inline-flex; }
.brand-name { display: block; font-size: 1.25rem; font-weight: 700; letter-spacing: -.01em; line-height: 1.1; }
.brand-sub { display: block; color: var(--muted); font-size: .9rem; }
.nav { display: flex; flex-direction: column; gap: .15rem; }
.nav-item { display: flex; align-items: center; gap: .9rem; border-radius: .55rem; min-height: 2.7rem; padding: 0 .95rem; color: var(--fg); font-size: 1rem; }
.nav-item:hover { background: var(--bg-hover); text-decoration: none; }
.nav-item.on { background: linear-gradient(90deg, var(--bg-active), #523168); }
.sidebar-foot { margin-top: auto; border-top: 1px solid var(--border); padding: .7rem .6rem 0; }

.main { display: flex; flex-direction: column; min-width: 0; }
.topbar { position: sticky; top: 0; z-index: 2; display: flex; align-items: center; height: 3.55rem; padding: 0 1.6rem;
  background: var(--bg-topbar); border-bottom: 1px solid var(--border); }
.crumbs { display: flex; align-items: center; gap: .75rem; font-size: 1rem; white-space: nowrap; overflow: hidden; min-width: 0; }
.crumb { color: #dccbe8; }
.crumb.here { color: var(--fg); font-weight: 700; overflow: hidden; text-overflow: ellipsis; }
.crumb-sep { color: var(--muted); }
.page { padding: 1.6rem 1.6rem 3rem; display: flex; flex-direction: column; gap: 1.4rem; min-width: 0; max-width: 92rem; }
.page-head h1 { margin: 0; font-size: 2.55rem; font-weight: 700; letter-spacing: -.015em; line-height: 1.1; }
.page-sub { margin: .45rem 0 0; font-size: 1.1rem; color: var(--fg-soft); }
.page-meta { display: flex; align-items: center; flex-wrap: wrap; gap: .5rem; margin-top: .7rem; }
.eyebrow { text-transform: uppercase; letter-spacing: .06em; color: var(--accent); font-size: .85rem; font-weight: 600; margin-bottom: .35rem; }

.split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(16rem, 24rem); min-width: 0; }
.split-main { padding-right: 1.7rem; min-width: 0; display: flex; flex-direction: column; gap: 1.4rem; }
.split-rail { border-left: 1px solid var(--border-strong); padding-left: 1.6rem; min-width: 0; display: flex; flex-direction: column; gap: 1.3rem; }
.stack { display: flex; flex-direction: column; gap: 1.4rem; min-width: 0; }
.split-main > * + .section, .split-rail > * + .section, .stack > * + .section { border-top: 1px solid var(--border); padding-top: 1.3rem; }
.section { display: flex; flex-direction: column; gap: .75rem; min-width: 0; }
.section-head h2 { margin: 0; font-size: 1.45rem; font-weight: 700; }
.section p { margin: 0; }
.split-rail .section-head h2 { font-size: 1.2rem; }

.status-chip { display: inline-flex; align-items: center; gap: .35rem; padding: .08rem .6rem; border-radius: .4rem;
  border: 1px solid var(--border-strong); background: #2b2136; font-size: .86rem; white-space: nowrap; }
.status-chip.succeeded { background: #192b30; border-color: #165848; color: #7df3c6; }
.status-chip.waiting { background: var(--warn-bg); border-color: var(--warn-border); color: var(--warn-fg); }
.status-chip.arm-c { background: #3a1f55; border-color: #8a5bc0; color: #e0c2fb; }
.status-chip.arm-a1 { background: #1c2340; border-color: #4a5fa8; color: #c2cffb; }
.status-chip.arm-a0 { background: #2b2136; border-color: var(--border-strong); color: var(--fg-soft); }

.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(8.8rem, 1fr)); gap: .7rem; }
.tile { border: 1px solid var(--border-strong); border-radius: .6rem; background: var(--bg-alt); padding: .8rem 1rem; }
.tile-label { color: var(--muted); font-size: .86rem; }
.tile-value { font-size: 1.75rem; font-weight: 700; letter-spacing: -.01em; font-variant-numeric: tabular-nums; }
.tile-sub { color: var(--muted); font-size: .8rem; }
.featured { border-left: 4px solid var(--teal); padding: .2rem 0 .2rem 1.4rem; display: flex; flex-direction: column; gap: .6rem; }
.featured h3 { margin: 0; font-size: 1.9rem; letter-spacing: -.01em; }
.featured h3 a { color: var(--fg); }
.arrow-link { display: inline-flex; align-items: center; gap: .6rem; font-size: 1.02rem; align-self: flex-start; }

.arrow-row { display: flex; align-items: center; gap: .9rem; padding: .75rem .3rem; border-bottom: 1px solid var(--border); color: var(--fg); min-width: 0; }
.arrow-row:hover { background: var(--bg-alt); text-decoration: none; }
.arrow-row:last-child { border-bottom: none; }
.row-icon { display: inline-flex; color: var(--fg-soft); flex: none; }
.row-label { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.row-title { font-weight: 600; font-size: 1.05rem; }
.row-sub { color: var(--muted); font-size: .9rem; }
.row-meta { color: var(--fg-soft); white-space: nowrap; font-size: .92rem; }
.row-arrow { color: var(--accent); display: inline-flex; flex: none; }

.table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: .55rem; background: var(--bg-alt); }
table { border-collapse: collapse; width: 100%; font-size: .93rem; }
th, td { text-align: left; padding: .5rem .75rem; border-bottom: 1px solid var(--border); vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: .82rem; text-transform: uppercase; letter-spacing: .03em; background: #21102e; }
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover td { background: #2c1739; }
td.num { font-family: var(--font-mono); font-size: .86rem; white-space: nowrap; font-variant-numeric: tabular-nums; }
dl.kv { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: .35rem .9rem; margin: 0; font-size: .93rem; }
dl.kv dt { color: var(--muted); }
dl.kv dd { margin: 0; overflow-wrap: anywhere; }
ul.plain { margin: 0; padding-left: 1.1rem; display: flex; flex-direction: column; gap: .35rem; }
.prose { color: var(--fg-soft); display: flex; flex-direction: column; gap: .7rem; }
.prose p, .prose ul { margin: 0; }
.prose ul { padding-left: 1.2rem; display: flex; flex-direction: column; gap: .3rem; }
.prose h3, .prose h4 { margin: .4rem 0 0; color: var(--fg); }
.prose strong { color: var(--fg); }

.status-strip { display: flex; align-items: center; flex-wrap: wrap; gap: .9rem; border-top: 1px solid var(--border); padding-top: 1.1rem; margin-top: .6rem; color: var(--fg-soft); font-size: .92rem; }
.status-strip > span + span::before { content: "\00b7"; margin-right: .9rem; color: var(--muted); }

@media (max-width: 900px) {
  .shell { display: block; }
  .sidebar { position: static; height: auto; border-right: none; border-bottom: 1px solid var(--border-soft); padding: .8rem 1rem; }
  .brand-block { padding: 0 0 .6rem; }
  .nav { flex-direction: row; flex-wrap: wrap; gap: .3rem; }
  .nav-item { min-height: 2.2rem; padding: 0 .7rem; font-size: .92rem; gap: .5rem; }
  .sidebar-foot { display: none; }
  .topbar { padding: 0 1rem; }
  .page { padding: 1.2rem 1rem 2.5rem; }
  .page-head h1 { font-size: 2rem; }
  .split { display: block; }
  .split-main { padding-right: 0; }
  .split-rail { border-left: none; padding-left: 0; border-top: 1px solid var(--border-strong); padding-top: 1.3rem; margin-top: 1.4rem; }
  .row-meta { display: none; }
}
"""
