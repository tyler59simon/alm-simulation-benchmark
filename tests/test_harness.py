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

from simkit import analyze, engine, probes, replies, sessions  # noqa: E402

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


if __name__ == '__main__':
    unittest.main()
