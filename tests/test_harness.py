"""Offline tests for the simulator: no agents run, no model is called. Run: py -3.10 -m unittest discover -s tests"""
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOME))

from simkit import analyze, clock, engine, gitops, lmsource, probes, replies, sessions, stores  # noqa: E402
from simkit.common import Run, lm_call  # noqa: E402

V3 = HOME / 'scenarios' / 'bank-cobol-springboot-v3'


def jsonl(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(json.dumps(e) for e in events) + '\n', encoding='utf-8')
    return path


def text(t):
    return {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': t}]}}


def tool(command):
    return {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'input': {'command': command}}]}}


def tool_result(content):
    return {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': content}]}}


def result(t):
    return {'type': 'result', 'subtype': 'success', 'result': t}


LM = '"python.exe" "C:/app/living_memory.py" --domain d'


class FakeRun:
    """The parts of simkit.common.Run the helpers under test touch."""

    def __init__(self, root):
        self.dir = Path(root)
        self.transcripts = self.dir / 'transcripts'
        self.ws = self.dir / 'ws'
        self.workspace = self.dir / 'workspace'
        self.workspace_enabled = True
        self._state = {'sessions': {}, 'steps': []}

    def state(self):
        return self._state

    def update_state(self, fn):
        fn(self._state)
        return self._state


class Replies(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_plain_reply_is_the_first_result(self):
        t = jsonl(self.tmp / 'a.jsonl', [tool('ls'), text('Done: all green.'), result('Done: all green.')])
        self.assertEqual(replies.final_reply(t), 'Done: all green.')

    def test_memory_housekeeping_after_the_answer_keeps_the_answer(self):
        t = jsonl(self.tmp / 'b.jsonl', [tool('git status'), text('{"answers": [{"id": "q1", "answer": "x"}]}'),
                                         tool(LM + ' capture --type map'), text('I saved a codebase map note.'),
                                         result('I saved a codebase map note.')])
        reply = replies.final_reply(t)
        self.assertIn('"answers"', reply)
        self.assertIn('codebase map', reply)

    def test_second_result_from_a_background_task_is_ignored(self):
        t = jsonl(self.tmp / 'c.jsonl', [text('The fix is merged.'), result('The fix is merged.'),
                                         text('That notification was an old wait loop.'), result('That notification was an old wait loop.')])
        self.assertEqual(replies.final_reply(t), 'The fix is merged.')

    def test_json_answers_found_before_housekeeping(self):
        t = jsonl(self.tmp / 'd.jsonl', [text('{"answers": [{"id": "q1", "answer": "x"}]}'), tool(LM + ' capture-finalize'),
                                         text('Saved. My answers are above.'), result('Saved. My answers are above.')])
        self.assertEqual(replies.json_reply(t, 'answers'), {'answers': [{'id': 'q1', 'answer': 'x'}]})

    def test_missing_transcript_falls_back(self):
        self.assertEqual(replies.final_reply(self.tmp / 'none.jsonl', 'tail'), 'tail')


class EarlyExit(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'uses a .cmd fake agent')
    def test_session_ends_soon_after_its_result(self):
        tmp = Path(tempfile.mkdtemp())
        fake = tmp / 'fakeclaude.py'
        fake.write_text('import sys,json,time,subprocess\nsys.stdin.read()\n'
                        'print(json.dumps({"type":"system","subtype":"init","session_id":"s","model":"m"}),flush=True)\n'
                        'subprocess.Popen([sys.executable,"-c","import time;time.sleep(120)"])\n'
                        'print(json.dumps({"type":"result","subtype":"success","result":"done","num_turns":1,"total_cost_usd":0.0,"session_id":"s"}),flush=True)\n'
                        'time.sleep(120)\n', encoding='utf-8')
        cmd = tmp / 'fakeclaude.cmd'
        cmd.write_text(f'@"{sys.executable}" -I "{fake}"\r\n', encoding='utf-8')
        saved = (sessions.LINGER_S, sessions.config, sessions.run_rev)
        sessions.LINGER_S, sessions.config, sessions.run_rev = 2, (lambda: {'claude': str(cmd)}), (lambda cwd: None)
        try:
            class R:
                transcripts = dir = tmp
                options = {'memory': 'on'}
                workspace_enabled = False
                def toolchain_env(self): return {}, None
                def update_state(self, fn): pass
            t0 = time.time()
            row = sessions.launch(R(), 'k', {'id': 'a'}, 'hi', str(tmp), tmp, {'model': 'm'})
        finally:
            sessions.LINGER_S, sessions.config, sessions.run_rev = saved
        self.assertLess(time.time() - t0, 40)
        self.assertEqual(row['final'], 'done')
        self.assertIsNotNone(row['ended_after_result'])


class Analysis(unittest.TestCase):
    def test_compare_arms_cells(self):
        table = analyze.compare_arms({'A': [{'probes': {'mean_score': 0.5}}], 'B': [{'probes': {'mean_score': 0.4}}, {'probes': {'mean_score': 0.6}}]})
        self.assertIn('±', table)
        self.assertIn('0.5 ± 0.14 (n=2)', table)

    def test_result_mistake_counts_repeats(self):
        run = FakeRun(tempfile.mkdtemp())
        msg = 'tracker: --owner takes a user handle (for example pokonkwo)'
        jsonl(run.transcripts / 's1d1' / 'po.jsonl', [tool_result(msg)])
        jsonl(run.transcripts / 's1d2' / 'po.jsonl', [tool_result('ok')])
        jsonl(run.transcripts / 's2d1' / 'po.jsonl', [tool_result(msg)])
        sess = [{'key': 's1d1/po', 'agent': 'po'}, {'key': 's1d2/po', 'agent': 'po'}, {'key': 's2d1/po', 'agent': 'po'}]
        m = analyze.result_mistake(run, {'desc': 'x', 'pattern': 'tracker: --owner takes a user handle'}, sess)
        self.assertEqual(m['total'], 2)
        self.assertEqual(m['repeat_sessions'], 1)

    def test_quiz_repo_reads_flags_a_clone_path(self):
        run = FakeRun(tempfile.mkdtemp())
        jsonl(run.transcripts / 'quiz' / 'po.jsonl', [tool(f'type "{run.ws}\\po\\docs\\x.md"'), tool(LM + ' search fee')])
        jsonl(run.transcripts / 'quiz' / 'qa.jsonl', [tool(LM + ' search parity')])
        found = analyze.quiz_repo_reads(run)
        self.assertEqual(list(found), ['po'])

    def test_quiz_order_puts_memory_first(self):
        self.assertEqual(engine.quiz_modes('on'), ['memory', 'repo'])
        self.assertEqual(engine.quiz_modes('off'), ['repo'])
        self.assertEqual(engine.quiz_modes('builtin'), ['repo'])

    def test_memory_quiz_lets_search_output_be_piped(self):
        denied = {r.split('(')[1].split(' ')[0] for r in engine.QUIZ_SHELL_DENY}
        self.assertTrue({'head', 'tail'}.isdisjoint(denied))
        self.assertIn('cat', denied)


class ProbeVerdictReuse(unittest.TestCase):
    def test_unchanged_evidence_reuses_the_old_verdict(self):
        run = FakeRun(tempfile.mkdtemp())
        (run.transcripts / 'probe-grade').mkdir(parents=True)
        (run.transcripts / 'probe-grade' / 'PR1.prompt.md').write_text('PROMPT', encoding='utf-8')
        jsonl(run.transcripts / 'probe-grade' / 'PR1.jsonl', [result('{"items": []}')])
        run._state['sessions']['probe-grade/PR1'] = {'key': 'probe-grade/PR1', 'ended': 'now'}
        self.assertFalse(probes.reuse_verdict(run, 'probe-grade/PR1', 'probe-grade/PR1@new', 'OTHER'))
        self.assertTrue(probes.reuse_verdict(run, 'probe-grade/PR1', 'probe-grade/PR1@same', 'PROMPT'))
        self.assertEqual(run._state['sessions']['probe-grade/PR1@same']['aliased_from'], 'probe-grade/PR1')
        self.assertTrue((run.transcripts / 'probe-grade' / 'PR1@same.jsonl').exists())


def git(cwd, *args):
    import subprocess
    return subprocess.run(['git', '-c', 'core.autocrlf=false', *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


class Accounting(unittest.TestCase):
    def test_session_without_result_counts_at_its_budget(self):
        from simkit.common import Run, append_jsonl
        root = Path(tempfile.mkdtemp())
        (root / 'scenario').mkdir()
        (root / 'scenario' / 'scenario.json').write_text('{}', encoding='utf-8')
        append_jsonl(root / 'costs.jsonl', {'key': 's1d1/po', 'cost_usd': 0.25})
        append_jsonl(root / 'costs.jsonl', {'key': 's1d1/qa', 'cost_usd': None, 'cost_bound_usd': 3.0})
        append_jsonl(root / 'costs.jsonl', {'key': 'quiz/po', 'cost_usd': 0.5})
        append_jsonl(root / 'costs.jsonl', {'key': 'chat/po-1', 'cost_usd': 0.01})
        run = Run(root)
        self.assertEqual(run.spent(), 3.76)
        split = analyze.cost_split(run)
        self.assertEqual((split['work_cost_usd'], split['harness_cost_usd'], split['chat_cost_usd']), (0.25, 0.5, 0.01))
        self.assertEqual(split['cost_unknown_sessions'], 1)

    def test_usage_is_summed_once_per_message(self):
        tmp = Path(tempfile.mkdtemp())
        u = {'input_tokens': 2, 'output_tokens': 10, 'cache_read_input_tokens': 100, 'cache_creation_input_tokens': 5}
        t = jsonl(tmp / 'a.jsonl', [{'type': 'assistant', 'message': {'id': 'm1', 'usage': u, 'content': [{'type': 'text', 'text': 'a'}]}},
                                    {'type': 'assistant', 'message': {'id': 'm1', 'usage': u, 'content': [{'type': 'tool_use', 'input': {}}]}},
                                    {'type': 'assistant', 'message': {'id': 'm2', 'usage': u, 'content': []}}])
        self.assertEqual(sessions.parse_transcript(t)['assistant_usage']['cache_read_input_tokens'], 200)


class QuizDenominator(unittest.TestCase):
    def test_missing_answers_and_unparsed_grades_score_zero(self):
        run = FakeRun(tempfile.mkdtemp())
        run.quiz = {'questions': [{'id': 'q1', 'fact': 'F1'}, {'id': 'q2', 'fact': 'F2'}]}
        run.truth = {'facts': {'F1': {'should_know': ['po', 'qa']}, 'F2': {'should_know': ['po', 'qa']}}}
        for a in ('po', 'qa'):
            jsonl(run.dir / 'quiz' / 'answers' / f'{a}.json', [{}])
        (run.dir / 'quiz' / 'grades').mkdir(parents=True)
        (run.dir / 'quiz' / 'grades' / 'po.json').write_text(json.dumps({'agent': 'po', 'grades': [{'id': 'q1', 'grade': 'correct'}]}), encoding='utf-8')
        (run.dir / 'quiz' / 'grades' / 'qa.json').write_text(json.dumps({'agent': 'qa', 'error': 'unparsed'}), encoding='utf-8')
        q = analyze.quiz_metrics(run, {})
        self.assertEqual(q['score_should_know'], 0.25)   # 1 correct of 4, not 1 of 1
        self.assertEqual(q['missing'], 3)
        self.assertEqual(q['unparsed'], ['qa'])


class ProbeEvidence(unittest.TestCase):
    def test_tracker_file_counts_only_when_the_session_named_or_created_it(self):
        listed = ('"py tracker.py list"', '"LH-7 Fee cap  [Todo]  pokonkwo"')
        self.assertFalse(probes.touched_by('tracker/LH-7-fee-cap.md', listed))
        self.assertTrue(probes.touched_by('tracker/LH-7-fee-cap.md', ('{"file_path": "c:/ws/tracker/lh-7-fee-cap.md"}', '')))
        self.assertTrue(probes.touched_by('tracker/LH-12-faq.md', ('"py tracker.py new faq"', '"lh-12 created: c:/x"')))
        self.assertFalse(probes.touched_by('tracker/LH-1-x.md', ('"py tracker.py show lh-12"', '')))

    def test_diff_puts_source_before_documents_and_caps_each_file(self):
        doc = 'diff --git a/docs/a.md b/docs/a.md\n' + 'x' * 9000
        src = 'diff --git a/modern/A.java b/modern/A.java\n+class A {}'
        out = probes.ordered_diff(doc + '\n' + src)
        self.assertTrue(out.startswith('diff --git a/modern/A.java'))
        self.assertIn('[... file diff truncated]', out)
        self.assertLess(len(out), 5000)


class WorkMetrics(unittest.TestCase):
    def test_error_signature_masks_paths_numbers_and_exit_lines(self):
        a = analyze.error_signature('Exit code 2\n/usr/bin/bash: eval: line 12: syntax error near unexpected token `&\'')
        b = analyze.error_signature('Exit code 2\n/usr/bin/bash: eval: line 7: syntax error near unexpected token `&\'')
        self.assertEqual(a, b)
        self.assertIn('syntax error', a)

    def test_repeat_failures_own_and_team(self):
        run = FakeRun(tempfile.mkdtemp())
        err = {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't', 'is_error': True,
                                                        'content': 'Exit code 1\nerror: pathspec x did not match'}]}}
        for key in ('s1d1/po', 's1d2/po', 's1d3/qa'):
            jsonl(run.transcripts / f'{key}.jsonl', [err])
        run._state['sessions'] = {k: {'key': k, 'agent': k.split('/')[1], 'started': f'2026-11-1{i}T00:00:00+00:00'}
                                  for i, k in enumerate(('s1d1/po', 's1d2/po', 's1d3/qa'))}
        rf = analyze.repeat_failures(run)
        self.assertEqual((rf['own_repeat_sessions'], rf['team_repeat_sessions']), (1, 1))

    def test_rereads_and_calls_before_first_change(self):
        run = FakeRun(tempfile.mkdtemp())
        clone = str(run.ws / 'po')
        read = lambda p: {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read', 'input': {'file_path': p}}]}}  # noqa: E731
        edit = {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': 'x'}}]}}
        jsonl(run.transcripts / 's1d1' / 'po.jsonl', [read(clone + '\\README.md'), edit])
        jsonl(run.transcripts / 's1d2' / 'po.jsonl', [read(clone.replace('\\', '/') + '/README.md'), read('docs/new.md'), edit])
        run._state['sessions'] = {'s1d1/po': {'key': 's1d1/po', 'agent': 'po', 'started': '1'},
                                  's1d2/po': {'key': 's1d2/po', 'agent': 'po', 'started': '2'}}
        rd = analyze.rediscovery(run)
        self.assertEqual(rd['mean_rereads'], 0.5)
        self.assertEqual(rd['mean_calls_before_change'], 1.5)

    def test_stale_window_starts_at_the_first_message_with_the_current_answer(self):
        run = FakeRun(tempfile.mkdtemp())
        run.events = {'sprints': {'1': {'arch': {'slack': [{'day': 1, 'text': 'Use long cents for money.'}]}},
                                  '3': {'arch': {'slack': [{'day': 1, 'text': 'All money is BigDecimal with scale 4.'}]}}}}
        self.assertEqual(analyze.stale_from(run, {'patterns': {'current': ['bigdecimal']}}), (3, 1))

    def test_lint_repeat_needs_the_rule_in_the_authors_prompt(self):
        run = FakeRun(tempfile.mkdtemp())
        (run.transcripts / 's1d2').mkdir(parents=True)
        (run.transcripts / 's1d2' / 'dev.prompt.md').write_text('#ci-bot: main is red\nci-lint L1: A.java:3: System.out', encoding='utf-8')
        (run.transcripts / 's1d2' / 'ops.prompt.md').write_text('#ci-bot: main is red\n(tail without the rule)', encoding='utf-8')
        run._state['sessions'] = {'s1d2/dev': {'key': 's1d2/dev', 'agent': 'dev', 'started': '2026-11-11T10:00:00+00:00'},
                                  's1d2/ops': {'key': 's1d2/ops', 'agent': 'ops', 'started': '2026-11-11T10:00:00+00:00'}}
        v = lambda a, t: {'rule': 'L1', 'author': a, 'file': 'A.java', 'text': t}   # noqa: E731
        rows = [{'ts': '2026-11-11T09:00:00+00:00', 'lint': [v('dev', 'a'), v('ops', 'b')]},
                {'ts': '2026-11-11T11:00:00+00:00', 'lint': [v('dev', 'a'), v('ops', 'b'), v('dev', 'c'), v('ops', 'd')]}]
        jsonl(run.dir / 'ci.jsonl', rows)
        m = analyze.lint_mistake(run, {'desc': 'x', 'rule': 'L1'})
        self.assertEqual(m['per_agent']['dev']['repeats'], 1)
        self.assertEqual(m['per_agent']['ops']['repeats'], 0)   # red CI, but the rule never reached their prompt

    def test_app_check_history_finds_a_regression(self):
        repo = Path(tempfile.mkdtemp())
        git(repo, 'init', '-q', '-b', 'main')
        git(repo, 'config', 'user.email', 't@x')
        git(repo, 'config', 'user.name', 't')
        (repo / 'modern').mkdir()
        shas = []
        for text in ('RoundingMode.HALF_EVEN', 'RoundingMode.HALF_UP'):
            (repo / 'modern' / 'A.java').write_text(text, encoding='utf-8')
            git(repo, 'add', '-A')
            git(repo, 'commit', '-q', '-m', 'x')
            shas.append(git(repo, 'rev-parse', '--short', 'HEAD').strip())
        self.assertIn('HALF_EVEN', analyze._corpus_at(repo, shas[0], 'modern', '**/*.java'))
        spec = {'root': 'modern', 'glob': '**/*.java', 'checks': [{'fact': 'T2', 'desc': 'half-even', 'any': ['HALF_EVEN']},
                                                                  {'fact': 'D1', 'desc': 'no long', 'none': ['HALF_UP']}]}
        run = FakeRun(tempfile.mkdtemp())
        run.integration, run.scenario_dir, run.scenario = repo, run.dir, {}
        (run.dir / 'app_checks.json').write_text(json.dumps(spec), encoding='utf-8')
        jsonl(run.dir / 'ci.jsonl', [{'label': 'a', 'main': shas[0]}, {'label': 'b', 'main': shas[1]}])
        h = analyze.app_check_history(run)
        self.assertEqual([r['fact'] for r in h['regressions']], ['T2'])   # 'none' checks pass vacuously first

    def test_paired_probes_interval(self):
        arms = {'A0': [{'probes': {'by_probe': {'P1': 0.0, 'P2': 0.5}}}], 'C': [{'probes': {'by_probe': {'P1': 1.0, 'P2': 0.5}}}]}
        line = analyze.paired_probes(arms)[0]
        self.assertIn('C - A0: +0.500', line)
        self.assertIn('1/1/0', line)


class RunLog(unittest.TestCase):
    def test_notes_markdown_to_html(self):
        from simkit import docs
        out = docs.note_blocks('## Head\n\nA **bold** `x` [v2](../analysis/v2.md).\n\n- one\n- two\n  more\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```\nraw <x>\n```')
        self.assertIn('<h3>Head</h3>', out)
        self.assertIn('<strong>bold</strong> <code>x</code> <a href="../analysis/v2.html">v2</a>', out)
        self.assertIn('<li>two more</li>', out)
        self.assertIn('<th>a</th>', out)
        self.assertIn('raw &lt;x&gt;', out)

    def test_prs_land_in_the_window_before_the_next_run(self):
        from datetime import datetime, timezone
        from simkit import docs
        t = lambda h: datetime(2026, 11, 11, h, tzinfo=timezone.utc)   # noqa: E731
        class R:
            def __init__(self, name, h):
                self.name, self.created = name, t(h)
        runs = [R('r1', 10), R('r2', 14)]
        prs = [{'when': t(h), 'number': n, 'title': str(n)} for h, n in ((8, 1), (9, 2), (12, 3), (16, 4))]
        windows, later = docs.pr_windows(runs, prs)
        self.assertEqual([p['number'] for p in windows['r1']], [1, 2])
        self.assertEqual([p['number'] for p in windows['r2']], [3])
        self.assertEqual([p['number'] for p in later], [4])

    def test_home_folder_is_scrubbed(self):
        from simkit import docs
        home = str(Path.home())
        self.assertNotIn(home, docs.scrub(f'path {home}\\x and {home.replace(chr(92), "/")}/y'))


def write_note(store, domain, nid, title, body, ntype='knowledge', folder='notes', status='active'):
    """A note file as the store writes it: JSON-valued frontmatter, then the body."""
    meta = {'title': title, 'type': ntype, 'status': status, 'id': nid, 'domain': domain}
    d = Path(store) / 'domains' / domain / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / f'{title}-{nid[:8]}.md').write_text('---\n' + ''.join(f'{k}: {json.dumps(v)}\n' for k, v in meta.items()) + '---\n\n' + body + '\n', encoding='utf-8')


TRUTH = {'facts': {'F1': {'patterns': {'current': ['30 ?/ ?360'], 'stale': ['actual ?/ ?365']}}}}


class ReviewMetrics(unittest.TestCase):
    def setUp(self):
        self.run = FakeRun(tempfile.mkdtemp())
        self.run.truth = TRUTH
        self.run.stores = self.run.dir / 'stores'
        store = self.run.stores / 'po'
        write_note(store, 'd', 'aaaaaaaa-1', 'Old basis', 'Interest uses actual/365 for the day count.')
        write_note(store, 'd', 'bbbbbbbb-2', 'Basis', 'Interest uses 30/360 for savings.')
        write_note(store, 'd', 'cccccccc-3', 'Basis again', 'SV1 accrues on 30/360.')
        write_note(store, 'd', 'dddddddd-4', 'Other', 'Unrelated reminder about lunch.')
        write_note(store, 'd', 'eeeeeeee-5', 'Where we are', 'Sprint 2 is half done.', ntype='status')
        write_note(store, 'd', 'ffffffff-6', 'Daily', 'Standup said we are on track.')
        self.store = store

    def row(self, kind, nid, **extra):
        return {'ref': f'd:{nid[:8]}', 'title': 't', 'type': 'knowledge', 'kinds': [kind], 'action': 'confirm', **extra}

    def test_precision_by_kind(self):
        pair = lambda nid: {'ref': f'd:{nid[:8]}', 'title': 'p', 'score': 0.9}   # noqa: E731
        items = [self.row('stale', 'aaaaaaaa'), self.row('stale', 'bbbbbbbb'), self.row('stale', 'dddddddd'),
                 self.row('due', 'eeeeeeee', type='status'), self.row('due', 'cccccccc'),
                 self.row('duplicate', 'bbbbbbbb', pair=pair('cccccccc')), self.row('duplicate', 'bbbbbbbb', pair=pair('dddddddd')),
                 self.row('warned', 'ffffffff'), self.row('warned', 'bbbbbbbb'), self.row('warned', 'dddddddd'),
                 self.row('noisy', 'ffffffff'), self.row('noisy', 'bbbbbbbb'),
                 self.row('noisy', '99999999', title='Sprint 3 status')]   # archived and gone: judged by its title
        items[0]['kinds'] = ['stale', 'duplicate']   # judged under the first kind only
        jsonl(self.run.dir / 'reviews.jsonl', [
            {'sprint': 1, 'agent': 'po', 'counts': {'stale': 3, 'due': 2}, 'items': items[:5], 'applied': [{'ref': 'd:aaaaaaaa', 'plan_id': 'p1'}]},
            {'sprint': 2, 'agent': 'po', 'counts': {'duplicate': 2, 'warned': 3, 'noisy': 3}, 'items': items[5:]},
            {'sprint': 2, 'agent': 'qa', 'error': 'boom'}])
        m = analyze.review_metrics(self.run)
        self.assertEqual((m['judged'], m['unjudged']), (11, 2))
        self.assertEqual(m['worklist_precision'], round(6 / 11, 3))
        self.assertEqual(m['by_kind']['stale'], {'rows': 3, 'judged': 2, 'real': 1})
        self.assertEqual(m['by_kind']['due'], {'rows': 2, 'judged': 2, 'real': 1})
        self.assertEqual(m['by_kind']['duplicate'], {'rows': 2, 'judged': 2, 'real': 1})
        self.assertEqual(m['by_kind']['warned'], {'rows': 3, 'judged': 2, 'real': 1})
        self.assertEqual(m['by_kind']['noisy'], {'rows': 3, 'judged': 3, 'real': 2})
        self.assertEqual(m['review_rows'], {'1': {'stale': 3, 'due': 2}, '2': {'duplicate': 2, 'warned': 3, 'noisy': 3}})
        self.assertEqual(m['review_archives'], 1)

    def test_nothing_judged_gives_no_precision(self):
        jsonl(self.run.dir / 'reviews.jsonl', [{'sprint': 1, 'agent': 'po', 'counts': {'interim': 1}, 'items': [self.row('interim', 'dddddddd')]}])
        m = analyze.review_metrics(self.run)
        self.assertEqual((m['worklist_precision'], m['judged'], m['unjudged']), (None, 0, 1))

    def test_no_reviews_file_means_no_metrics(self):
        self.assertIsNone(analyze.review_metrics(self.run))

    def test_status_snapshots_count_active_status_notes(self):
        write_note(self.store, 'd', 'abababab-7', 'Old status', 'Sprint 1.', ntype='status', folder='archive', status='archived')
        m = analyze.store_metrics(self.store, TRUTH)
        self.assertEqual(m['status_snapshots'], 1)
        self.assertEqual(m['notes_active'], 6)

    def test_analyze_leaves_review_out_without_reviews(self):
        from simkit.common import Run
        root = Path(tempfile.mkdtemp())
        (root / 'scenario').mkdir()
        (root / 'scenario' / 'scenario.json').write_text('{"roster": []}', encoding='utf-8')
        write_note(root / 'stores' / 'po', 'd', 'aaaaaaaa-1', 'Status', 'Now.', ntype='status')
        m = analyze.analyze(Run(root))
        self.assertEqual(m['schema'], 4)
        self.assertEqual(m['totals']['status_snapshots'], 1)
        self.assertNotIn('review', m)
        self.assertNotIn('review', json.loads((root / 'metrics.json').read_text(encoding='utf-8')))


class SprintReview(unittest.TestCase):
    def make_run(self, memory='on', review_user=False):
        run = FakeRun(tempfile.mkdtemp())
        run.options = {'memory': memory, 'review_user': review_user}
        run.scenario = {'domain': 'd', 'roster': [{'id': 'po'}, {'id': 'qa'}, {'id': 'late'}]}
        run.stores = run.dir / 'stores'
        for a in ('po', 'qa'):
            (run.stores / a).mkdir(parents=True)
        run.agents = lambda: {a['id']: a for a in run.scenario['roster']}
        run.done = lambda step: step in run._state['steps']
        run.mark = lambda step: run._state['steps'].append(step)
        return run

    def stub(self):
        calls = []
        rows = [{'ref': 'd:11111111', 'kinds': ['duplicate'], 'action': 'archive'},
                {'ref': 'd:22222222', 'kinds': ['stale'], 'action': 'update'},
                {'ref': 'd:33333333', 'kinds': ['duplicate'], 'action': 'merge'}]

        def lm(store, args, payload=None, actor=None, cwd=None):
            calls.append((Path(store).name, list(args)))
            if 'review' in args:
                if Path(store).name == 'po':
                    raise RuntimeError('review failed')
                return {'ok': True, 'due': 3, 'stale_digests': 1, 'counts': {'duplicate': 2, 'stale': 1}, 'notes': rows}   # the CLI's review shape
            return {'ok': True, 'operation_id': 'd-op1'}

        applied = []
        saved = engine.stores.lm
        engine.stores.lm = lm
        self.addCleanup(lambda: setattr(engine.stores, 'lm', saved))
        return calls, applied

    def test_review_logs_rows_and_survives_a_failing_store(self):
        run = self.make_run()
        calls, applied = self.stub()
        engine.review(run, 2)
        rows = [json.loads(x) for x in (run.dir / 'reviews.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([(r['sprint'], r['agent']) for r in rows], [(2, 'po'), (2, 'qa')])
        self.assertIn('review failed', rows[0]['error'])
        self.assertEqual((rows[1]['counts'], len(rows[1]['items'])), ({'duplicate': 2, 'stale': 1}, 3))
        self.assertNotIn('applied', rows[1])
        self.assertEqual(calls[-1], ('qa', ['--domain', 'd', 'review', '--limit', '100']))
        self.assertEqual(applied, [])
        self.assertIn('s2/review', run._state['steps'])
        engine.review(run, 2)   # resumed: nothing is asked twice
        self.assertEqual(len((run.dir / 'reviews.jsonl').read_text(encoding='utf-8').splitlines()), 2)

    def test_review_user_archives_only_archive_rows(self):
        run = self.make_run(review_user=True)
        calls, applied = self.stub()
        engine.review(run, 1)
        rows = [json.loads(x) for x in (run.dir / 'reviews.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(rows[1]['applied'], [{'ref': 'd:11111111', 'operation_id': 'd-op1'}])
        self.assertEqual(applied, [])   # a direct write: nothing to apply
        self.assertEqual([a for _, a in calls if 'archive' in a], [['--domain', 'd', 'archive', 'd:11111111']])

    def test_no_review_without_living_memory(self):
        run = self.make_run(memory='builtin')
        calls, _ = self.stub()
        engine.review(run, 1)
        self.assertEqual(calls, [])
        self.assertFalse((run.dir / 'reviews.jsonl').exists())
        self.assertNotIn('s1/review', run._state['steps'])


class LmCall(unittest.TestCase):
    def test_script_form_in_bash_and_powershell(self):
        self.assertEqual(lm_call('"C:/Python310/python.exe" "C:/Users/a/app/living_memory.py" --domain d search "fee rule"'), 'search')
        self.assertEqual(lm_call(r'& "C:\Python310\python.exe" "C:\Users\a\app\living_memory.py" --domain d capture --type map'), 'capture')
        self.assertEqual(lm_call(r"& 'C:\Python310\python.exe' 'C:\Users\a\app\living_memory.py' --json read d:abc"), 'read')
        self.assertEqual(lm_call('python -I /app/living_memory.py review --limit 100'), 'review')

    def test_alm_launcher_with_global_options(self):
        self.assertEqual(lm_call('alm --json search "x"'), 'search')
        self.assertEqual(lm_call('& alm --json --domain bankmod capture --type decision --title "T"'), 'capture')
        self.assertEqual(lm_call(r'& "C:\Users\a\.local\bin\alm.exe" --json --root "C:\runs\r\stores\po" --domain d recap --days 7'), 'recap')
        self.assertEqual(lm_call('alm --domain=d --json maintenance history'), 'maintenance')
        self.assertEqual(lm_call('LIVING_MEMORY_ROOT=/s alm --json capture-finalize --session abc'), 'capture-finalize')

    def test_chains_pipes_and_cd(self):
        self.assertEqual(lm_call('cd /repo && alm --json search foo | head -20'), 'search')
        self.assertEqual(lm_call("cd C:\\repo; & alm --json ask 'what is the fee?'"), 'ask')

    def test_variables_functions_and_eval_the_command_defines(self):
        self.assertEqual(lm_call('PY="C:/Python/python.exe"; LM="C:/app/living_memory.py"; "$PY" "$LM" --root "$R" --domain d capture --type map'), 'capture')
        self.assertEqual(lm_call(r'$py = "C:\Python\python.exe"; $lm = "C:\app\living_memory.py"; & $py $lm --domain d read abc'), 'read')
        self.assertEqual(lm_call('lm() { python "C:/app/living_memory.py" --domain d "$@"; }\nS=abc\nlm update d:1 --session $S'), 'update')
        self.assertEqual(lm_call('''CMD='"python.exe" "living_memory.py" --domain d'; eval "$CMD read d:1 --max-chars 3000"'''), 'read')
        self.assertEqual(lm_call('PY=python; LM=/a/living_memory.py; for c in "confirm d:1" "capture-finalize"; do "$PY" "$LM" --domain d $c; done'), 'other')
        self.assertIsNone(lm_call('cd /repo && cat "living_memory.py" >/dev/null; echo done'))

    def test_unknown_subcommand_is_other(self):
        self.assertEqual(lm_call('alm --json frobnicate'), 'other')
        self.assertEqual(lm_call('alm'), 'other')

    def test_lookalikes_do_not_match(self):
        for cmd in ('realm search', 'palm --json search x', 'ls /home/alm/notes', 'cat C:/tools/alm/README.md', 'echo alm search',
                    'git commit -m "x; alm search"', 'python script.py living_memory', 'grep -r alm src', '', None):
            self.assertIsNone(lm_call(cmd), cmd)

    def test_new_subcommands_are_known(self):
        for sub in ('recap', 'ask', 'maintenance', 'changes', 'source', 'archive', 'taxonomy', 'source-sync', 'semantic', 'off', 'on', 'status', 'restore', 'log',
                    'history', 'stats'):
            self.assertEqual(lm_call(f'alm --json {sub}'), sub)

    def test_transcript_metrics_counts_both_forms(self):
        tmp = Path(tempfile.mkdtemp())
        t = jsonl(tmp / 'a.jsonl', [tool('alm --json search x'), tool(LM + ' capture --type map'), tool('ls realm'), tool_result('ok')])
        m = analyze.transcript_metrics(t, tmp, 'po')
        self.assertEqual(m['lm_subcommands'], {'search': 1, 'capture': 1})
        self.assertEqual(sessions.parse_transcript(t)['lm_calls'], 2)


def clock_run(days=3, sprints=4, enabled=True, per_sprint=14):
    run = FakeRun(tempfile.mkdtemp())
    run.days, run.scenario = days, {'sprints': sprints}
    run.clock = clock.settings(enabled, '2026-11-14T12:00:00+00:00', {'clock_days_per_sprint': per_sprint})
    return run


class SimulatedCalendar(unittest.TestCase):
    def setUp(self):
        self.addCleanup(lambda: clock._current.update(at=None))

    def iso(self, moment):
        return moment.isoformat(timespec='seconds')

    def test_day_mapping(self):
        run = clock_run()   # 14 days per sprint, 3 working days: days start 4 days apart
        self.assertEqual(self.iso(clock.day_time(run, 1, 1)), '2026-11-14T12:00:00+00:00')
        self.assertEqual(self.iso(clock.day_time(run, 1, 3)), '2026-11-22T12:00:00+00:00')
        self.assertEqual(self.iso(clock.day_time(run, 2, 1)), '2026-11-28T12:00:00+00:00')
        self.assertEqual(self.iso(clock.day_time(run, 4, 2)), '2026-12-30T12:00:00+00:00')

    def test_one_working_day_per_sprint(self):
        run = clock_run(days=1)
        self.assertEqual(self.iso(clock.day_time(run, 2, 1)), '2026-11-28T12:00:00+00:00')

    def test_review_and_final_phase(self):
        run = clock_run()
        self.assertEqual(self.iso(clock.review_time(run, 1)), '2026-11-27T12:00:00+00:00')   # the day before sprint 2 starts
        self.assertEqual(self.iso(clock.final_time(run)), '2027-01-23T12:00:00+00:00')   # start + (4 + 1) * 14 days

    def test_session_key_maps_to_its_phase(self):
        run = clock_run()
        self.assertEqual(clock.session_time(run, 's2d3/po'), clock.day_time(run, 2, 3))
        self.assertEqual(clock.session_time(run, 's2d3/po.resolve'), clock.day_time(run, 2, 3))
        self.assertEqual(clock.session_time(run, 's1/po'), clock.day_time(run, 1, 1))
        for key in ('quiz/po', 'quiz-repo/po', 'quiz-kb/_kb', 'grade/po@abc', 'grade-audit/calibration'):
            self.assertEqual(clock.session_time(run, key), clock.final_time(run))

    def test_off_gives_nothing(self):
        run = clock_run(enabled=False)
        self.assertIsNone(clock.day_time(run, 1, 1))
        self.assertIsNone(clock.session_time(run, 's1/po'))
        self.assertEqual(clock.session_env(None), {})
        clock.enter(run, clock.final_time(run))
        self.assertEqual((clock.lm_env(), clock.git_env()), ({}, {}))

    def test_env_for_a_session(self):
        from datetime import datetime, timedelta, timezone
        real = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)
        env = clock.session_env(real + timedelta(days=14), real)
        self.assertEqual(env['LIVING_MEMORY_CLOCK_OFFSET_SECONDS'], '1209600.000')
        self.assertEqual(env['LIVING_MEMORY_HEADLESS'], '1')
        self.assertEqual(env['GIT_AUTHOR_DATE'], '2026-11-28T12:00:00+00:00')
        self.assertEqual(env['GIT_COMMITTER_DATE'], env['GIT_AUTHOR_DATE'])

    def launch_env(self, run, key):
        seen = {}

        class Proc:
            returncode = 0

            def __init__(self, args, **kw):
                seen['env'] = kw['env']
                self.stdin = type('In', (), {'write': lambda s, x: None, 'close': lambda s: None})()

            def poll(self):
                return 0

        tmp = Path(tempfile.mkdtemp())
        run.transcripts, run.options, run.workspace_enabled = tmp, {'memory': 'on'}, False
        run.toolchain_env = lambda: ({}, ())
        run.update_state = lambda fn: None
        run.dir = tmp
        saved = (sessions.subprocess.Popen, sessions.config, sessions.run_rev)
        sessions.subprocess.Popen, sessions.config, sessions.run_rev = Proc, (lambda: {'claude': 'claude'}), (lambda cwd: None)
        os.environ['LIVING_MEMORY_CLOCK_OFFSET_SECONDS'] = '5'   # a stale inherited value must never leak into a child
        try:
            row = sessions.launch(run, key, {'id': 'po'}, 'hi', str(tmp), tmp, {'model': 'm'})
        finally:
            del os.environ['LIVING_MEMORY_CLOCK_OFFSET_SECONDS']
            sessions.subprocess.Popen, sessions.config, sessions.run_rev = saved
        return seen['env'], row

    def test_session_env_with_the_clock_on(self):
        from datetime import datetime, timezone
        run = clock_run()
        env, row = self.launch_env(run, 's2d1/po')
        want = clock.day_time(run, 2, 1)
        self.assertLess(abs(float(env['LIVING_MEMORY_CLOCK_OFFSET_SECONDS']) - (want - datetime.now(timezone.utc)).total_seconds()), 60)
        self.assertEqual(env['GIT_AUTHOR_DATE'], '2026-11-28T12:00:00+00:00')
        self.assertEqual(env['GIT_COMMITTER_DATE'], '2026-11-28T12:00:00+00:00')
        self.assertEqual(env['LIVING_MEMORY_HEADLESS'], '1')
        self.assertEqual(row['sim_time'], '2026-11-28T12:00:00+00:00')

    def test_session_env_with_the_clock_off(self):
        env, row = self.launch_env(clock_run(enabled=False), 's2d1/po')
        self.assertNotIn('LIVING_MEMORY_CLOCK_OFFSET_SECONDS', env)   # the stale inherited value was stripped
        self.assertNotIn('GIT_AUTHOR_DATE', env)
        self.assertNotIn('sim_time', row)

    def test_harness_calls_use_the_phase_time(self):
        run = clock_run()
        calls = []
        saved = (stores.run_cmd, gitops.run_cmd)
        done = lambda *a, **k: type('R', (), {'stdout': '{}', 'stderr': '', 'returncode': 0})()   # noqa: E731
        stores.run_cmd = lambda args, **kw: calls.append(('lm', kw['env'])) or done()
        gitops.run_cmd = lambda args, **kw: calls.append(('git', kw['env'])) or done()
        self.addCleanup(lambda: (setattr(stores, 'run_cmd', saved[0]), setattr(gitops, 'run_cmd', saved[1])))
        clock.enter(run, clock.day_time(run, 3, 2))
        stores.lm(Path(tempfile.mkdtemp()), ['doctor'])
        gitops.git('.', 'status')
        lm_env, git_env = calls[0][1], calls[1][1]
        self.assertIn('LIVING_MEMORY_CLOCK_OFFSET_SECONDS', lm_env)
        self.assertEqual(lm_env['LIVING_MEMORY_HEADLESS'], '1')
        self.assertEqual(git_env['GIT_AUTHOR_DATE'], '2026-12-16T12:00:00+00:00')
        clock.enter(clock_run(enabled=False), None)
        calls.clear()
        stores.lm(Path(tempfile.mkdtemp()), ['doctor'])
        gitops.git('.', 'status')
        self.assertNotIn('LIVING_MEMORY_CLOCK_OFFSET_SECONDS', calls[0][1])
        self.assertNotIn('GIT_AUTHOR_DATE', calls[1][1])

    def test_set_clock_records_the_simulated_time_without_a_workspace_flag(self):
        run = clock_run()
        run.workspace_enabled = False
        engine.set_clock(run, 2, 3)
        row = json.loads((run.workspace / '.clock.json').read_text(encoding='utf-8'))
        self.assertEqual((row['sprint'], row['day'], row['label'], row['time']), (2, 3, 's2d3', '2026-12-06T12:00:00+00:00'))
        off = clock_run(enabled=False)
        engine.set_clock(off, 1, 1)
        self.assertNotIn('time', json.loads((off.workspace / '.clock.json').read_text(encoding='utf-8')))


class Manifest(unittest.TestCase):
    def test_repo_commit_and_cli_version_are_null_on_failure(self):
        self.assertIsNone(engine.lm_repo_commit({'lm_repo': str(Path(tempfile.mkdtemp()) / 'nope')}))
        self.assertIsNone(engine.lm_cli_version({'python': 'no-such-python-xyz', 'lm_cli': 'x.py'}))
        self.assertIsNone(engine.lm_cli_version({}))

    def test_cli_version_parses_the_last_json_line(self):
        saved = engine.run_cmd
        engine.run_cmd = lambda *a, **k: type('R', (), {'stdout': 'noise\n{"ok": true, "api": 2}\n', 'returncode': 0})()
        self.addCleanup(lambda: setattr(engine, 'run_cmd', saved))
        self.assertEqual(engine.lm_cli_version({'python': 'p', 'lm_cli': 'c'}), {'ok': True, 'api': 2})


REAL_REVIEW = {   # `alm --json --domain D review --limit 100` on a store with a due note and a duplicate pair (ALM main at #54)
    'ok': True, 'domain': 'lighthouse', 'due': 2, 'stale_digests': 0, 'kinds': ['stale', 'due', 'interim', 'duplicate', 'warned', 'noisy'],
    'counts': {'stale': 0, 'due': 1, 'interim': 0, 'duplicate': 1, 'warned': 0, 'noisy': 0},
    'notes': [{'ref': 'lighthouse:92acd811-39fc-4970-99c4-4790d3f3c38e', 'title': 'Old fee rule', 'type': 'knowledge', 'updated': '2026-11-15',
               'review_by': '2026-01-01', 'confirmed': None, 'pinned': False, 'domain': 'lighthouse', 'kinds': ['due'],
               'reason': 'review date 2026-01-01 has passed', 'action': 'confirm', 'maintenance': {'permitted': ['keep'], 'protected': None}},
              {'ref': 'lighthouse:81aabcbe-0d41-47e9-bd54-9216df4e584b', 'title': 'Old fee rule copy', 'type': 'knowledge', 'kinds': ['duplicate'],
               'reason': 'title 1.00 like lighthouse:92acd811-39fc-4970-99c4-4790d3f3c38e Old fee rule', 'action': 'supersede',
               'pair': {'ref': 'lighthouse:92acd811-39fc-4970-99c4-4790d3f3c38e', 'title': 'Old fee rule', 'score': 1.0}}],
    'hint': '...'}


class RealShapes(unittest.TestCase):
    def stub_lm(self, handler):
        saved = engine.stores.lm
        engine.stores.lm = handler
        self.addCleanup(lambda: setattr(engine.stores, 'lm', saved))

    def test_fetch_review_reads_the_real_worklist_shape(self):
        self.stub_lm(lambda store, args, **kw: REAL_REVIEW)
        got = engine.fetch_review('s', 'lighthouse')
        self.assertEqual((got['total'], got['counts']['duplicate'], len(got['items'])), (2, 1, 2))
        self.assertEqual([analyze.row_kind(r) for r in got['items']], ['due', 'duplicate'])
        self.assertEqual(got['items'][1]['pair']['ref'], 'lighthouse:92acd811-39fc-4970-99c4-4790d3f3c38e')

    def test_review_metrics_on_the_real_shape(self):
        run = FakeRun(tempfile.mkdtemp())
        run.truth, run.stores = TRUTH, run.dir / 'stores'
        write_note(run.stores / 'po', 'lighthouse', '92acd811-39fc-4970-99c4-4790d3f3c38e', 'Old fee rule', 'Interest uses actual/365 for savings.')
        write_note(run.stores / 'po', 'lighthouse', '81aabcbe-0d41-47e9-bd54-9216df4e584b', 'Old fee rule copy', 'Interest uses actual/365 for savings.')
        jsonl(run.dir / 'reviews.jsonl', [{'sprint': 1, 'agent': 'po', 'counts': REAL_REVIEW['counts'], 'total': REAL_REVIEW['due'],
                                           'items': REAL_REVIEW['notes']}])
        m = analyze.review_metrics(run)
        self.assertEqual(m['review_rows'], {'1': {'stale': 0, 'due': 1, 'interim': 0, 'duplicate': 1, 'warned': 0, 'noisy': 0}})
        self.assertEqual(m['by_kind']['due'], {'rows': 1, 'judged': 1, 'real': 1})
        self.assertEqual(m['by_kind']['duplicate'], {'rows': 1, 'judged': 1, 'real': 1})


REAL_STATS = {'ok': True, 'days': 30, 'domains': ['lighthouse', '_global'], 'events': 40, 'sessions_with_injections': 3, 'notes': 5, 'noisy': [],
              'used': [], 'reminders': {'fix': 2, 'decision': 1}, 'signal_captures': {},
              'capture_coverage': {'days': 30, 'mutating': 4, 'covered': 3, 'ratio': 0.75}}
REAL_LOG = {'ok': True, 'count': 3, 'rows': [
    {'time': 't1', 'event': 'created', 'ref': 'd:1', 'title': 'a', 'type': 'plan', 'domain': 'd', 'projects': [], 'op': 'o1', 'summary': 's', 'actor': 'agent:po'},
    {'time': 't2', 'event': 'resolved', 'ref': 'd:1', 'title': 'a', 'type': 'plan', 'domain': 'd', 'projects': [], 'op': 'o2', 'summary': 's', 'actor': 'auto_resolve'},
    {'time': 't3', 'event': 'archived', 'ref': 'd:2', 'title': 'b', 'type': 'knowledge', 'domain': 'd', 'projects': [], 'op': 'o3', 'summary': 's', 'actor': 'maintenance'}]}
REAL_RECAP = {'ok': True, 'days': 90, 'counts': {'created': 5}, 'maintenance': {'runs': 0, 'charged_usd': '0.00'}, 'sessions': {'count': 0},
              'open_work': {'notes': 1}, 'review': {'due': 1, 'by_kind': {'due': 1}}, 'markdown': '# Recap'}


class Readout(unittest.TestCase):
    def make_run(self, memory='on'):
        run = FakeRun(tempfile.mkdtemp())
        run.options = {'memory': memory}
        run.scenario = {'domain': 'd', 'roster': [{'id': 'po'}, {'id': 'qa'}]}
        run.stores = run.dir / 'stores'
        for a in ('po', 'qa'):
            (run.stores / a).mkdir(parents=True)
        run.agents = lambda: {a['id']: a for a in run.scenario['roster']}
        run.done = lambda step: step in run._state['steps']
        run.mark = lambda step: run._state['steps'].append(step)
        run.truth = TRUTH
        return run

    def stub(self):
        calls = []

        def lm(store, args, payload=None, actor=None, cwd=None):
            name = Path(store).name
            sub = next(a for a in args[2:] if a in ('stats', 'log', 'recap', 'maintenance', 'review'))
            calls.append((name, list(args)))
            if sub == 'recap' and '120' in args:
                raise RuntimeError('living_memory recap failed: {"ok":false,"error":{"message":"--days must be 1 to 90"}}')
            if name == 'qa' and sub == 'maintenance':
                raise RuntimeError('living_memory maintenance failed: unknown command')
            return {'stats': REAL_STATS, 'log': dict(REAL_LOG), 'recap': dict(REAL_RECAP), 'maintenance': {'ok': True, 'runs': []},
                    'review': REAL_REVIEW}[sub]
        saved = engine.stores.lm
        engine.stores.lm = lm
        self.addCleanup(lambda: setattr(engine.stores, 'lm', saved))
        return calls

    def test_readout_writes_every_command_and_records_errors(self):
        run = self.make_run()
        calls = self.stub()
        engine.review_at_quiz(run)
        engine.readout(run)
        data = json.loads((run.dir / 'stores-readout.json').read_text(encoding='utf-8'))
        po, qa = data['stores']['po'], data['stores']['qa']
        self.assertEqual(po['stats']['capture_coverage']['ratio'], 0.75)
        self.assertEqual(len(po['log']['rows']), 3)
        self.assertNotIn('markdown', po['recap'])
        self.assertEqual(po['days_used'], {'stats': 120, 'recap': 90})   # recap is capped at 90 days: retried
        self.assertEqual(po['review_at_quiz']['total'], 2)
        self.assertEqual(po['errors'], {})
        self.assertIn('maintenance_history', qa['errors'])
        self.assertIsNone(qa['maintenance_history'])
        self.assertIn(('po', ['--domain', 'd', 'stats', '--days', '120', '--json']), calls)
        self.assertIn(('po', ['--domain', 'd', 'maintenance', 'history', '--limit', '1000', '--json']), calls)
        self.assertIn('readout', run._state['steps'])
        n = len(calls)
        engine.readout(run)   # resumed: nothing is asked twice
        self.assertEqual(len(calls), n)

    def test_no_readout_without_living_memory(self):
        run = self.make_run(memory='builtin')
        calls = self.stub()
        engine.readout(run)
        engine.review_at_quiz(run)
        self.assertEqual(calls, [])
        self.assertFalse((run.dir / 'stores-readout.json').exists())

    def test_schema_4_metrics(self):
        run = self.make_run()
        self.stub()
        engine.review_at_quiz(run)
        engine.readout(run)
        # po: a fix reminder then a capture in the same session, and a denied call operator;
        # qa: a fix reminder with only an earlier capture, and a reminder of another kind
        jsonl(run.stores / 'po' / 'logs' / 'log-1.jsonl', [
            {'kind': 'hook', 'event': 'stop', 'session': 's1', 'ts': '2026-11-11T10:00:00', 'detail': {'reason': 'reminded:fix'}},
            {'kind': 'command', 'event': 'capture', 'session': 's1', 'ts': '2026-11-11T10:01:00', 'exit_code': 0},
            {'kind': 'hook', 'event': 'pre-tool-use', 'session': 's1', 'ts': '2026-11-11T09:00:00', 'detail': {'decision': 'deny:call-operator'}}])
        jsonl(run.stores / 'qa' / 'logs' / 'log-1.jsonl', [
            {'kind': 'command', 'event': 'capture', 'session': 's2', 'ts': '2026-11-11T09:00:00', 'exit_code': 0},
            {'kind': 'hook', 'event': 'stop', 'session': 's2', 'ts': '2026-11-11T10:00:00', 'detail': {'reason': 'reminded:fix'}},
            {'kind': 'hook', 'event': 'stop', 'session': 's3', 'ts': '2026-11-11T10:00:00', 'detail': {'reason': 'reminded:doc'}}])
        r = analyze.readout_metrics(run)
        self.assertEqual(r['capture_coverage']['mean_ratio'], 0.75)
        self.assertEqual(r['capture_coverage']['per_store']['po'], {'days': 30, 'mutating': 4, 'covered': 3, 'ratio': 0.75})
        self.assertEqual(r['reminders_by_kind'], {'fix': 4, 'decision': 2})
        self.assertEqual(r['actors'], {'agent:po': 2, 'auto_resolve': 2, 'maintenance': 2})
        self.assertEqual(r['auto_resolved'], 2)
        self.assertEqual(r['due_at_quiz'], {'per_store': {'po': 2, 'qa': 2}, 'total': 4})
        self.assertEqual(r['fix_reminder_followthrough'], {'reminded_sessions': 2, 'followed': 1, 'rate': 0.5})
        self.assertEqual(r['call_operator_denies'], 1)

    def test_absent_readout_is_empty_not_a_crash(self):
        run = self.make_run()
        r = analyze.readout_metrics(run)
        self.assertEqual((r['capture_coverage'], r['reminders_by_kind'], r['actors'], r['auto_resolved'], r['due_at_quiz']),
                         (None, {}, {}, None, None))
        self.assertEqual(r['fix_reminder_followthrough'], {'reminded_sessions': 0, 'followed': 0, 'rate': None})
        self.assertEqual(r['call_operator_denies'], 0)
        for _, fn in analyze.ARM_METRICS:
            fn({'readout': r})
            fn({})

    def test_compare_arms_lists_the_new_metrics(self):
        r = {'capture_coverage': {'mean_ratio': 0.5}, 'reminders_by_kind': {'fix': 2}, 'fix_reminder_followthrough': {'rate': 1.0},
             'auto_resolved': 3, 'due_at_quiz': {'total': 7}, 'call_operator_denies': 1}
        table = analyze.compare_arms({'C': [{'readout': r}]})
        for label in ('capture coverage (mean ratio)', 'fix reminder follow-through', 'auto-resolved notes', 'review worklist at quiz',
                      'call-operator denies'):
            self.assertIn(label, table)


class SprintStats(unittest.TestCase):
    def test_window_starts_on_the_first_day_and_does_not_overlap(self):
        from datetime import timedelta
        run = clock_run()
        self.assertEqual(engine.stats_window(run), 13)
        for s in (1, 2, 3):   # the snapshot at review time s covers (review_time(s) - 13 days, review_time(s)]
            begin = clock.review_time(run, s) - timedelta(days=13)
            self.assertEqual(begin, clock.day_time(run, s, 1))
            if s > 1:
                self.assertGreaterEqual(begin, clock.review_time(run, s - 1))
        self.assertEqual(engine.stats_window(clock_run(per_sprint=60)), 30)

    def test_review_takes_a_stats_snapshot_only_with_the_clock(self):
        for enabled, want in ((True, 2), (False, 0)):
            run = SprintReview.make_run(SprintReview(), memory='on')
            run.clock = clock.settings(enabled, '2026-11-14T12:00:00+00:00', {'clock_days_per_sprint': 14})
            run.days, run.scenario['sprints'] = 3, 4
            seen = []

            def lm(store, args, payload=None, actor=None, cwd=None):
                seen.append(args)
                return {'ok': True, 'due': 0, 'counts': {}, 'notes': [], 'reminders': {'fix': 1}, 'capture_coverage': {'mutating': 2, 'covered': 1}}
            saved = engine.stores.lm
            engine.stores.lm = lm
            try:
                engine.review(run, 1)
            finally:
                engine.stores.lm = saved
            path = run.dir / 'stats.jsonl'
            rows = [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []
            self.assertEqual(len(rows), want)
            if want:
                self.assertIn(['--domain', 'd', 'stats', '--days', '13', '--json'], seen)

    def test_metrics_sum_the_sprint_snapshots_and_fall_back(self):
        run = Readout().make_run()
        (run.dir / 'stores-readout.json').write_text(json.dumps({'recap_days_needed': 70, 'recap_truncated': False, 'stores': {
            'po': {'stats': REAL_STATS, 'log': {'rows': []}}, 'qa': {'stats': REAL_STATS, 'log': {'rows': []}}}}), encoding='utf-8')
        snap = lambda m, c, r: {'capture_coverage': {'days': 13, 'mutating': m, 'covered': c}, 'reminders': r}   # noqa: E731
        jsonl(run.dir / 'stats.jsonl', [{'sprint': 1, 'agent': 'po', 'days': 13, 'stats': snap(4, 2, {'fix': 1})},
                                        {'sprint': 2, 'agent': 'po', 'days': 13, 'stats': snap(2, 2, {'fix': 2, 'doc': 1})},
                                        {'sprint': 1, 'agent': 'qa', 'error': 'boom'}])
        r = analyze.readout_metrics(run)
        self.assertEqual(r['capture_coverage']['per_store']['po'], {'days': 26, 'mutating': 6, 'covered': 4, 'ratio': 0.67, 'source': 'sprints'})
        self.assertEqual(r['capture_coverage']['per_store']['qa']['ratio'], 0.75)   # no usable snapshot: the end-of-run stats
        self.assertEqual(r['reminders_by_kind'], {'fix': 5, 'doc': 1, 'decision': 1})
        self.assertEqual((r['recap_days_needed'], r['recap_truncated']), (70, False))

    def test_recap_window_covers_a_clocked_run(self):
        run = Readout().make_run()
        run.clock = clock.settings(True, '2026-11-14T12:00:00+00:00', {'clock_days_per_sprint': 20})
        run.scenario['sprints'] = 4   # 100 simulated days: longer than recap's 90
        asked = []
        saved = engine.stores.lm
        engine.stores.lm = lambda store, args, **kw: asked.append(args) or {'ok': True}
        try:
            engine.readout(run)
        finally:
            engine.stores.lm = saved
        self.assertIn(['--domain', 'd', 'recap', '--days', '90', '--json'], asked)
        data = json.loads((run.dir / 'stores-readout.json').read_text(encoding='utf-8'))
        self.assertEqual((data['recap_days_needed'], data['recap_truncated']), (101, True))


class CodexFindings(unittest.TestCase):
    def test_function_body_is_expanded_at_the_call(self):
        self.assertEqual(lm_call('PY=python; LM=/app/living_memory.py; lm() { "$PY" "$LM" "$@"; }; lm capture --type map'), 'capture')

    def test_a_path_with_spaces_stays_one_word(self):
        self.assertEqual(lm_call('PY="C:/Program Files/Python/python.exe"; LM=/app/living_memory.py; "$PY" "$LM" capture'), 'capture')
        self.assertEqual(lm_call('CMD=\'"C:/Program Files/Python/python.exe" "/app/living_memory.py" --domain d\'; $CMD read x'), 'read')

    def test_readout_runs_after_the_final_phase(self):
        from datetime import timedelta
        run = clock_run()
        self.assertEqual(clock.readout_time(run), clock.final_time(run) + timedelta(days=1))
        self.assertIsNone(clock.readout_time(clock_run(enabled=False)))
        seen = []
        run = Readout().make_run()
        run.clock = clock.settings(True, '2026-11-14T12:00:00+00:00', {'clock_days_per_sprint': 14})
        run.scenario['sprints'] = 4
        saved = engine.stores.lm
        engine.stores.lm = lambda store, args, **kw: seen.append(clock.current()) or {'ok': True}
        self.addCleanup(lambda: (setattr(engine.stores, 'lm', saved), clock._current.update(at=None)))
        engine.readout(run)
        self.assertEqual(set(seen), {clock.readout_time(run)})

    def test_a_resumed_review_counts_one_snapshot_per_store_and_sprint(self):
        run = Readout().make_run()
        (run.dir / 'stores-readout.json').write_text(json.dumps({'stores': {'po': {'stats': REAL_STATS, 'log': {'rows': []}}}}), encoding='utf-8')
        snap = lambda m, c: {'capture_coverage': {'days': 13, 'mutating': m, 'covered': c}, 'reminders': {'fix': 1}}   # noqa: E731
        jsonl(run.dir / 'stats.jsonl', [{'sprint': 1, 'agent': 'po', 'stats': snap(4, 2)}, {'sprint': 1, 'agent': 'po', 'stats': snap(5, 3)},
                                        {'sprint': 1, 'agent': 'po', 'error': 'boom'}, {'sprint': 2, 'agent': 'po', 'stats': snap(1, 1)}])
        r = analyze.readout_metrics(run)
        self.assertEqual((r['capture_coverage']['per_store']['po']['mutating'], r['capture_coverage']['per_store']['po']['covered']), (6, 4))
        self.assertEqual(r['reminders_by_kind'], {'fix': 2})

    def test_digest_step_gets_the_phase_clock(self):
        run = clock_run()
        calls = []
        tmp = Path(tempfile.mkdtemp())
        app = tmp / 'app'
        (app / 'scripts').mkdir(parents=True)
        (app / 'scripts' / 'ingest_run.py').write_text('', encoding='utf-8')
        run.dir, run.stores, run.origin = tmp, tmp / 'stores', tmp / 'origin'
        run.workspace_enabled, run.quiz = False, {'intro': 'i', 'questions': []}
        run.scenario.update(domain='d')
        done = set()
        run.done, run.mark = (lambda s: s in done), done.add
        saved = (engine.config, engine.run_cmd, engine.gitops.git, engine.stores.bootstrap, engine.stores.lm, engine.stores.bind,
                 engine._session, engine.quiz_answers, engine.grade)
        engine.config = lambda: {'python': 'p', 'lm_cli': str(app / 'living_memory.py')}
        engine.run_cmd = lambda args, **kw: calls.append(kw.get('env')) or type('R', (), {'stdout': '', 'stderr': '', 'returncode': 0})()
        engine.gitops.git = lambda *a, **k: None
        engine.stores.bootstrap = lambda *a, **k: None
        engine.stores.lm = lambda *a, **k: {}
        engine.stores.bind = lambda *a, **k: None
        engine._session = lambda *a, **k: {}
        engine.quiz_answers = lambda *a, **k: {}
        engine.grade = lambda *a, **k: None
        deny_saved, engine.sessions.deny_rules = engine.sessions.deny_rules, (lambda *a: [])
        self.addCleanup(lambda: setattr(engine.sessions, 'deny_rules', deny_saved))
        (tmp / 'kb' / 'repo').mkdir(parents=True)
        self.addCleanup(lambda: (engine.__dict__.update(config=saved[0], run_cmd=saved[1], _session=saved[6], quiz_answers=saved[7], grade=saved[8]),
                                 setattr(engine.gitops, 'git', saved[2]), setattr(engine.stores, 'bootstrap', saved[3]),
                                 setattr(engine.stores, 'lm', saved[4]), setattr(engine.stores, 'bind', saved[5]), clock._current.update(at=None)))
        engine.kb_quiz(run, 1.0)
        self.assertIn('LIVING_MEMORY_CLOCK_OFFSET_SECONDS', calls[0])


class CommandErrors(unittest.TestCase):
    def test_exit_code_and_legacy_exit_both_count(self):
        store = Path(tempfile.mkdtemp())
        jsonl(store / 'logs' / 'l.jsonl', [{'kind': 'command', 'event': 'capture', 'exit_code': 0},
                                           {'kind': 'command', 'event': 'read', 'exit_code': 2, 'reason': 'x'},
                                           {'kind': 'command', 'event': 'read', 'exit': 1}, {'kind': 'command', 'event': 'read'}])
        m = analyze.store_metrics(store, {})
        self.assertEqual((m['commands']['total'], m['commands']['errors']), (4, 2))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ScenarioV3(unittest.TestCase):
    def test_colleagues_do_not_know_decisions_before_they_are_made(self):
        chat = load(V3 / 'workspace' / 'bin' / 'team_chat.py', 'team_chat_v3')
        owen = next(p for p in json.loads((V3 / 'npcs.json').read_text(encoding='utf-8'))['people'] if p['handle'] == 'oachterberg')
        self.assertFalse(any('PC-2025-21' in k for k in chat.known(owen, 2)))
        self.assertTrue(any('PC-2025-21' in k for k in chat.known(owen, 4)))
        self.assertTrue(any('PC-2025-14' in k for k in chat.known(owen, 2)))

    def test_tracker_owner_filter_wants_a_handle(self):
        run = Path(tempfile.mkdtemp())
        (run / 'scenario').mkdir()
        (run / 'scenario' / 'scenario.json').write_text(json.dumps({'roster': [{'name': 'Priya Okonkwo'}]}), encoding='utf-8')
        (run / 'workspace' / 'bin').mkdir(parents=True)
        src = (V3 / 'workspace' / 'bin' / 'tracker.py').read_text(encoding='utf-8')
        (run / 'workspace' / 'bin' / 'tracker.py').write_text(src, encoding='utf-8')
        tracker = load(run / 'workspace' / 'bin' / 'tracker.py', 'tracker_v3')
        (run / 'workspace' / 'tracker').mkdir()
        (run / 'workspace' / 'tracker' / 'LH-1-x.md').write_text('# LH-1 X\n\nStatus: Todo\nOwner: Priya Okonkwo\n', encoding='utf-8')
        with self.assertRaises(SystemExit) as e:
            tracker.main(['list', '--owner', 'Priya Okonkwo'])
        self.assertIn('tracker: --owner takes a user handle', str(e.exception))
        self.assertEqual(tracker.main(['list', '--owner', 'pokonkwo']), 0)

    def test_v3_mistakes_include_the_tracker_trap(self):
        ids = [m['id'] for m in json.loads((V3 / 'mistakes.json').read_text(encoding='utf-8'))['mistakes']]
        self.assertIn('M4', ids)


class SmokeNoteTest(unittest.TestCase):
    def test_finds_the_created_time_of_the_titled_note(self):
        store = Path(tempfile.mkdtemp())
        notes = store / 'domains' / 'team' / 'notes'
        notes.mkdir(parents=True)
        (notes / 'other.md').write_text('---\ntitle: "Other"\ncreated: "2026-01-01T00:00:00+00:00"\n---\n', encoding='utf-8')
        (notes / 'smoke.md').write_text(f'---\ntitle: "{engine.SMOKE_NOTE}"\ncreated: "2027-01-24T10:00:00.123456+00:00"\n---\n',
                                        encoding='utf-8')
        self.assertEqual(engine._note_created(store, engine.SMOKE_NOTE), '2027-01-24T10:00:00.123456+00:00')
        self.assertIsNone(engine._note_created(store, 'Missing'))


class FakeCheckout:
    """A minimal Living Memory source tree: the two functions simkit.lmsource reads from a checkout."""

    BLOCK = '<!-- agentic-living-memory:begin -->\nshort block\n<!-- agentic-living-memory:end -->'

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / 'living_memory.py').write_text('', encoding='utf-8')
        (self.dir / 'core').mkdir()
        (self.dir / 'core' / '__init__.py').write_text('', encoding='utf-8')
        (self.dir / 'core' / 'instructions.py').write_text(
            f'def instruction_block(harness):\n    return {self.BLOCK!r}\n', encoding='utf-8')
        (self.dir / 'integrations').mkdir()
        (self.dir / 'integrations' / '__init__.py').write_text('', encoding='utf-8')
        (self.dir / 'integrations' / 'setup.py').write_text(
            "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n"
            "def hooks(harness):\n    return {'SessionStart': [{'hooks': [{'type': 'command', 'command': 'py', "
            "'args': [str(ROOT / 'hooks' / 'claude_hooks.py'), 'session-start']}]}]}\n", encoding='utf-8')


class LmSource(unittest.TestCase):
    def setUp(self):
        self.src = FakeCheckout()
        self.run_dir = Path(tempfile.mkdtemp())
        self.saved = {k: os.environ.get(k) for k in ('SIMKIT_LM_CLI', 'SIMKIT_LM_REPO')}
        self.addCleanup(self.restore)

    def restore(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_prepare_writes_the_checkouts_block_and_hooks_and_leaves_the_real_config_alone(self):
        real = Path(tempfile.mkdtemp())
        (real / '.credentials.json').write_text('{"claudeAiOauth": {}}', encoding='utf-8')
        home = lmsource.prepare(self.run_dir, self.src.dir, real_claude=real)
        self.assertEqual(home, self.run_dir / 'claude-home')
        self.assertEqual((home / 'CLAUDE.md').read_text(encoding='utf-8'), FakeCheckout.BLOCK + '\n')
        hook = json.loads((home / 'settings.json').read_text(encoding='utf-8'))['hooks']['SessionStart'][0]['hooks'][0]
        self.assertEqual(Path(hook['args'][0]), self.src.dir.resolve() / 'hooks' / 'claude_hooks.py')
        self.assertEqual((home / '.credentials.json').read_text(encoding='utf-8'), '{"claudeAiOauth": {}}')
        self.assertEqual(sorted(p.name for p in real.iterdir()), ['.credentials.json'])   # the source folder is only read

    def test_a_folder_without_the_script_is_refused(self):
        with self.assertRaises(SystemExit):
            lmsource.prepare(self.run_dir, tempfile.mkdtemp())

    def test_env_names_both_variables(self):
        self.assertEqual(lmsource.env(Path('/x/home')), {'CLAUDE_CONFIG_DIR': str(Path('/x/home')), 'CLAUDE_HOME': str(Path('/x/home'))})

    def test_use_lm_src_points_the_harness_cli_at_the_checkout(self):
        from simkit.common import config, use_lm_src
        use_lm_src(self.src.dir)
        self.assertEqual(Path(config()['lm_cli']), self.src.dir.resolve() / 'living_memory.py')
        self.assertEqual(Path(config()['lm_repo']), self.src.dir.resolve())

    def run_with(self, options):
        d = Path(tempfile.mkdtemp())
        scenario = {'tiers': {'haiku': {'model': 'haiku', 'budget_usd': 1.5}, 'sonnet-low': {'model': 'sonnet', 'effort': 'low'},
                              'grader': {'model': 'sonnet'}}, 'roster': [], 'domain': 'd'}
        (d / 'scenario').mkdir()
        (d / 'scenario' / 'scenario.json').write_text(json.dumps(scenario), encoding='utf-8')
        (d / 'manifest.json').write_text(json.dumps({'options': options}), encoding='utf-8')
        return Run(d)

    def test_work_model_replaces_every_work_tier_but_not_the_grader(self):
        run = self.run_with({'work_model': 'haiku'})
        self.assertEqual(run.tier({'tier': 'sonnet-low'}), {'model': 'haiku'})   # effort dropped: not every model takes it
        self.assertEqual(run.tier({'tier': 'haiku'}), {'model': 'haiku', 'budget_usd': 1.5})
        self.assertEqual(run.tier({'tier': 'grader'}), {'model': 'sonnet'})
        self.assertIsNone(lmsource.home_of(run))

    def test_without_options_nothing_changes(self):
        run = self.run_with({})
        self.assertEqual(run.tier({'tier': 'sonnet-low'}), {'model': 'sonnet', 'effort': 'low'})

    def test_a_run_with_lm_src_has_a_private_claude_home_and_keeps_its_checkout_when_resumed(self):
        run = self.run_with({'lm_src': str(self.src.dir)})
        self.assertEqual(lmsource.home_of(run), run.dir / 'claude-home')
        self.assertEqual(Path(os.environ['SIMKIT_LM_CLI']), self.src.dir.resolve() / 'living_memory.py')


def ab_transcript(path):
    def use(i, command):
        return {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': i, 'name': 'Bash', 'input': {'command': command}}]}}

    def res(i, content, error=False):
        return {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': i, 'content': content, 'is_error': error}]}}
    warned = json.dumps({'ok': True, 'status': 'created', 'id': 'd:1', 'quality_warnings': ['summary is a list', 'title has a date']})
    return jsonl(path, [
        use('1', 'alm --json help capture'), res('1', '{"ok": true, "topic": "capture", "markdown": "Capture usage ..."}'),
        use('2', 'alm --json capture --type context --title T'), res('2', [{'type': 'text', 'text': warned}]),
        use('3', 'alm --json capture --type context --title U'), res('3', '{"ok": true, "status": "created", "id": "d:2"}'),
        use('4', 'alm --json capture --bogus'), res('4', 'usage: alm capture\nalm: error: unrecognized arguments: --bogus', True),
        use('5', 'alm --json read missing'), res('5', 'No note matches', True),
        use('6', 'ls'), res('6', 'x'),
        result('done')])


class BlockAB(unittest.TestCase):
    def test_session_counts_captures_warnings_malformed_and_help(self):
        t = ab_transcript(Path(tempfile.mkdtemp()) / 's1.jsonl')
        s = analyze.block_session(t)
        self.assertEqual((s['captures'], s['writes'], s['warned_results'], s['calls']), (2, 2, 1, 5))
        self.assertEqual(s['warnings'], ['summary is a list', 'title has a date'])
        self.assertEqual((len(s['errors']), s['malformed']), (2, 1))
        self.assertEqual(s['help'], ['capture'])

    def test_a_failed_call_hidden_by_a_compound_command_still_counts(self):
        # Block A/B 2026-11-17: most failed calls ran as `alm ... ; echo` or `| head`, so the tool saw exit code 0.
        bad = json.dumps({'ok': False, 'error': {'code': 'invalid', 'message': "bad_arguments: argument --type: invalid choice: 'constraint'"}})
        t = jsonl(Path(tempfile.mkdtemp()) / 's1.jsonl', [
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': '1', 'name': 'Bash', 'input': {'command': 'alm --json capture --type constraint --title T; echo done'}}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': '1', 'content': bad + '\ndone', 'is_error': False}]}},
            result('done')])
        s = analyze.block_session(t)
        self.assertEqual((s['errors'], s['malformed'], s['captures']), (['bad_arguments'], 1, 0))
        # One call failed and another in the same command succeeded: the error and the write both count.
        good = json.dumps({'ok': True, 'id': 'n1', 'status': 'created', 'quality_warnings': ['title has a date']})
        t = jsonl(Path(tempfile.mkdtemp()) / 's2.jsonl', [
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': '1', 'name': 'Bash', 'input': {'command': 'alm --json capture --title A --why x; alm --json capture --title B'}}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': '1', 'content': bad + '\n' + good, 'is_error': False}]}},
            result('done')])
        s = analyze.block_session(t)
        self.assertEqual((len(s['errors']), s['malformed'], s['captures'], s['warned_results']), (1, 1, 1, 1))

    def test_each_call_in_a_compound_command_counts_and_unfinished_calls_do_not(self):
        def use(i, command):
            return {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': i, 'name': 'Bash', 'input': {'command': command}}]}}

        def res(i, content):
            return {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': i, 'content': content, 'is_error': False}]}}
        ok = json.dumps({'ok': True, 'id': 'n', 'status': 'created'})
        warned = json.dumps({'ok': True, 'id': 'n', 'status': 'created', 'quality_warnings': ['title has a date']})
        t = jsonl(Path(tempfile.mkdtemp()) / 's1.jsonl', [
            use('1', 'alm --json capture --title A; alm --json capture --title B; alm --json capture --title C'), res('1', '\n'.join([ok, warned, ok])),
            use('2', 'alm --json search x; alm --json capture --title D'), res('2', json.dumps({'ok': True, 'results': []}) + '\n' + ok),
            # a wrapper the command parser cannot follow: the results still say what ran
            use('3', 'CMD=("python" "C:/lm/living_memory.py" --json); "${CMD[@]}" capture --title F; "${CMD[@]}" capture --title G'),
            res('3', ok + '\n' + ok),
            use('5', 'alm --json capture --title H 2>&1 | tail -c 40'), res('5', 'ests/Account.java"],"inferred_tags":[]}'),   # cut off: unknown
            use('6', 'alm --json capture --title I 2>&1 | tail -3'), res('6', 'Traceback (most recent call last):\n  File "x"'),   # crashed
            # a search that worked, then a capture that crashed before printing JSON
            use('7', 'alm --json search x; alm --json capture --title J'),
            res('7', json.dumps({'ok': True, 'results': []}) + "\npython.exe: can't open file 'C:/lm/living_memory.py'"),
            # pretty-printed (`| jq .`) and a saved finalize receipt
            use('8', 'alm --json capture --title K | jq .; alm --json capture-finalize --session S --note d:1'),
            res('8', json.dumps({'ok': True, 'status': 'created', 'id': 'k'}, indent=2) + '\n' + json.dumps({'ok': True, 'status': 'saved'})),
            use('4', 'alm --json capture --title E')])   # the session ended before this call's result
        s = analyze.block_session(t)
        self.assertEqual((s['calls'], s['captures'], s['writes'], s['warned_results']), (12, 7, 8, 1))
        self.assertEqual(s['errors'], ['Traceback (most recent call last):', "python.exe: can't open file 'C:/lm/living_memory.py'"])
        self.assertEqual(analyze.lm_calls('alm --json search x && alm --json capture --title D'), ['search', 'capture'])

    def test_automemory_is_read_from_the_runs_private_config_folder(self):
        home, ws = Path(tempfile.mkdtemp()), Path('C:/runs/r1/ws/dev')
        mem = home / 'projects' / str(ws).replace(':', '-').replace('\\', '-').replace('/', '-') / 'memory'
        mem.mkdir(parents=True)
        (mem / 'MEMORY.md').write_text('x')
        self.assertEqual(analyze.automemory_files(ws, home), 1)

    def test_help_is_a_known_subcommand(self):
        self.assertEqual(lm_call('alm --json help capture'), 'help')

    def make_run(self, with_brief):
        run = FakeRun(tempfile.mkdtemp())
        run.stores = run.dir / 'stores'
        key, quiz_key = 's1d1/dev', 'quiz/dev'
        ab_transcript(run.transcripts / f'{key}.jsonl')
        ab_transcript(run.transcripts / f'{quiz_key}.jsonl')
        run._state['sessions'] = {key: {'key': key, 'started': '2026-01-01T00:00:00', 'session_hash': 'h-work'},
                                  quiz_key: {'key': quiz_key, 'started': '2026-01-02T00:00:00', 'session_hash': 'h-quiz'}}
        notes = run.stores / 'dev' / 'domains' / 'd' / 'notes'
        notes.mkdir(parents=True)
        if with_brief:
            (notes / 'b.md').write_text('---\ntitle: "Project brief"\ntype: brief\nstatus: active\ndomain: d\n---\nGoals and owners.\n', encoding='utf-8')
        captured = {'kind': 'command', 'event': 'capture', 'exit_code': 0, 'status': 'created'}
        jsonl(run.stores / 'dev' / 'logs' / 'a.jsonl', [{'kind': 'hook', 'event': 'pre-tool-use', 'detail': {'decision': 'deny:call-operator'}},
                                                         {'kind': 'hook', 'event': 'pre-tool-use', 'detail': {'decision': 'allow'}},
                                                         # the work session's two captures (its transcript sees both), one
                                                         # more whose output `| tail` cut off, a failed one, and a quiz one
                                                         {**captured, 'session': 'h-work'}, {**captured, 'session': 'h-work'},
                                                         {**captured, 'session': 'h-work'},
                                                         {'kind': 'command', 'event': 'capture', 'exit_code': 2, 'session': 'h-work'},
                                                         {**captured, 'session': 'h-quiz'}])
        return run

    def test_block_ab_headline_covers_the_requested_metrics(self):
        m = analyze.block_ab(self.make_run(True), {'score_should_know': 0.5, 'score_all': 0.4}, {'capture_coverage': {'mean_ratio': 0.7}})
        h = m['headline']
        self.assertEqual((h['work_sessions'], h['captures'], h['captures_per_work_session'], h['sessions_with_capture']), (1, 3, 3.0, 1))
        self.assertEqual((h['warned_results'], h['warned_share'], h['warnings']), (1, 0.5, 2))   # work sessions only
        self.assertEqual((h['lm_call_errors'], h['malformed_calls'], h['hook_denies']), (4, 2, 1))   # work and quiz sessions
        self.assertEqual((h['help_calls'], h['sessions_using_help'], h['capture_coverage']), (2, 2, 0.7))
        self.assertEqual((h['project_briefs'], h['quiz_score_should_know'], h['quiz_score_all']), (1, 0.5, 0.4))
        self.assertEqual(m['help_topics'], {'capture': 2})
        self.assertEqual(m['hook_denies_by_decision'], {'deny:call-operator': 1})
        self.assertEqual(m['briefs']['dev'][0]['text'], 'Goals and owners.')

    def test_compare_ab_and_arm_table_read_the_same_metrics(self):
        a = {'run': 'run-A', 'block_ab': analyze.block_ab(self.make_run(True))}
        b = {'run': 'run-B', 'block_ab': analyze.block_ab(self.make_run(False))}
        text = analyze.compare_ab(a, b)
        self.assertIn('captures_per_work_session', text)
        self.assertIn('project_briefs', text)
        self.assertIn("'Project brief'", text)
        self.assertIn('summary is a list x1', text)
        table = analyze.compare_arms({'A': [a], 'B': [b]})
        self.assertRegex(table, r'captures/work session\s+3 ± 0 \(n=1\)\s+3 ± 0 \(n=1\)')
        self.assertRegex(table, r'project briefs\s+1 ± 0 \(n=1\)\s+0 ± 0 \(n=1\)')

    def test_no_sessions_gives_empty_headline_not_a_crash(self):
        run = FakeRun(tempfile.mkdtemp())
        run.stores = run.dir / 'stores'
        h = analyze.block_ab(run)['headline']
        self.assertEqual((h['work_sessions'], h['captures_per_work_session'], h['warned_share']), (0, None, None))



if __name__ == '__main__':
    unittest.main()
