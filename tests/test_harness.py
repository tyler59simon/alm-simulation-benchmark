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
