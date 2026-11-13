from fzf_sessions import dependencies as dependencies_mod
import shutil
from fzf_sessions import adapters as adapters_mod
from fzf_sessions import cli as cli_mod
from fzf_sessions import common as common_mod
from fzf_sessions import conversation as conversation_mod
from fzf_sessions import help_ui as help_ui_mod
from fzf_sessions import launch as launch_mod
from fzf_sessions import models as models_mod
from fzf_sessions import previews as previews_mod
from fzf_sessions import search as search_mod
from fzf_sessions import summaries as summaries_mod
from fzf_sessions import ui as ui_mod
from fzf_sessions import usage as usage_mod
import subprocess
import time
import contextlib
import io
import json
import os
import shlex
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'fzf-sessions'


def write_records(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r) + '\n' for r in records))


class SessionsTests(unittest.TestCase):
    def setUp(self):
        for name in ('require_fzf', 'require_herdr'):
            check = patch.object(dependencies_mod, name, return_value='/test/checked')
            check.start()
            self.addCleanup(check.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_codex_index_filters_children_exec_and_archived_but_not_unset_user_flag(self):
        db = self.root / 'state_5.sqlite'
        with contextlib.closing(sqlite3.connect(db)) as c:
            c.execute('create table threads (id, cwd, title, source, archived, has_user_event, updated_at)')
            c.executemany('insert into threads values (?,?,?,?,?,?,?)', [
                ('main', '/repo', 'Original', 'cli', 0, 0, 100),
                ('child', '/repo', 'Child', '{"subagent":{}}', 0, 1, 100),
                ('exec', '/repo', 'Batch', 'exec', 0, 1, 100),
                ('old', '/repo', 'Old', 'cli', 1, 1, 100)])
            c.commit()
        write_records(self.root / 'session_index.jsonl', [{'id': 'main', 'thread_name': 'Renamed'}])
        found = adapters_mod.codex_sessions(self.root)
        self.assertEqual([(x.id, x.title) for x in found], [('main', 'Renamed')])

    def test_codex_rollout_fallback_and_partial_record(self):
        p = self.root / 'sessions/2026/11/12/rollout.jsonl'
        write_records(p, [
            {'type': 'session_meta', 'payload': {'id': 'abc', 'cwd': '/repo', 'source': 'cli'}},
            {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': 'Fix the login'}}])
        with p.open('a') as f:
            f.write('{"incomplete":')
        found = adapters_mod.codex_sessions(self.root)
        self.assertEqual(found[0].title, 'Fix the login')

    def test_claude_title_cwd_and_child_exclusion(self):
        base = self.root / 'projects/encoded'
        user = {'type': 'user', 'cwd': '/real/path-with-dashes', 'gitBranch': 'feature',
                'message': {'content': 'Initial prompt'}}
        write_records(base / 'main.jsonl', [user,
            {'type': 'custom-title', 'customTitle': 'My title'},
            {'type': 'ai-title', 'aiTitle': 'Automatic'}])
        write_records(base / 'child.jsonl', [dict(user, isSidechain=True)])
        write_records(base / 'main/subagents/agent.jsonl', [user])
        found = adapters_mod.claude_sessions(self.root)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].cwd, found[0].title), ('/real/path-with-dashes', 'My title'))

    def test_claude_updated_ignores_file_touch_and_metadata_rewrites(self):
        path = self.root / 'projects/encoded/main.jsonl'
        write_records(path, [
            {'type': 'user', 'cwd': '/repo', 'timestamp': '2026-11-10T10:00:00Z',
             'message': {'content': 'Actual request'}},
            {'type': 'assistant', 'timestamp': '2026-11-10T10:02:00Z',
             'message': {'content': 'Actual answer'}},
            {'type': 'system', 'timestamp': '2026-11-13T08:00:00Z', 'content': 'metadata ' * 30000},
            {'type': 'assistant', 'isMeta': True, 'timestamp': '2026-11-13T08:01:00Z',
             'message': {'content': 'Internal update'}}])
        os.utime(path, (time.time(), time.time()))
        with path.open('a') as stream:
            stream.write('{"partial":')
        found = adapters_mod.claude_sessions(self.root)
        self.assertEqual(found[0].updated, common_mod.timestamp('2026-11-10T10:02:00Z'))

    def test_codex_updated_ignores_database_and_settings_updates(self):
        path = self.root / 'sessions/rollout.jsonl'
        write_records(path, [
            {'type': 'response_item', 'timestamp': '2026-11-10T10:00:00Z',
             'payload': {'type': 'message', 'role': 'assistant', 'content': []}},
            {'type': 'event_msg', 'timestamp': '2026-11-10T10:02:00Z',
             'payload': {'type': 'task_complete'}},
            {'type': 'event_msg', 'timestamp': '2026-11-13T08:00:00Z',
             'payload': {'type': 'thread_settings_applied'}},
            {'type': 'event_msg', 'timestamp': '2026-11-13T08:01:00Z',
             'payload': {'type': 'token_count', 'info': {}}}])
        with contextlib.closing(sqlite3.connect(self.root / 'state_5.sqlite')) as conn:
            conn.execute('create table threads (id, cwd, title, source, updated_at, rollout_path)')
            conn.execute('insert into threads values (?,?,?,?,?,?)',
                         ('session', '/repo', 'Title', 'cli', time.time(), str(path)))
            conn.commit()
        self.assertEqual(adapters_mod.codex_sessions(self.root)[0].updated, common_mod.timestamp('2026-11-10T10:02:00Z'))

    def test_codex_fallback_timestamp_is_activity_not_mtime(self):
        path = self.root / 'sessions/2026/11/10/rollout.jsonl'
        write_records(path, [
            {'type': 'session_meta', 'payload': {'id': 'fallback', 'cwd': '/repo', 'source': 'cli'}},
            {'type': 'event_msg', 'timestamp': '2026-11-10T10:00:00Z',
             'payload': {'type': 'user_message', 'message': 'Original request'}},
            {'type': 'event_msg', 'timestamp': '2026-11-13T08:00:00Z',
             'payload': {'type': 'thread_settings_applied'}}])
        self.assertEqual(adapters_mod.codex_sessions(self.root)[0].updated, common_mod.timestamp('2026-11-10T10:00:00Z'))

    def test_unknown_activity_does_not_look_recent(self):
        path = self.root / 'projects/encoded/unknown.jsonl'
        write_records(path, [{'type': 'user', 'cwd': '/repo', 'message': {'content': 'No timestamp'}}])
        self.assertEqual(adapters_mod.claude_sessions(self.root)[0].updated, 0)
        self.assertEqual(common_mod.age(0), 'unknown')
        self.assertEqual(common_mod.age(float('nan')), 'unknown')
        self.assertEqual(common_mod.age(time.time() + 86400), 'unknown')

    def test_preview_omits_tools_and_terminal_controls(self):
        p = self.root / 'chat.jsonl'
        write_records(p, [
            {'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'name': 'secret tool'},
                {'type': 'text', 'text': 'Answer\x1b[31m'}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'tool output'}]}}])
        output = previews_mod.preview(models_mod.Session('claude', 'abc', 'Title', '/repo', 0, str(p)))
        self.assertIn('Answer', output)
        self.assertNotIn('\x1b', output)
        self.assertNotIn('secret tool', output)
        self.assertNotIn('tool output', output)

    def test_bounded_tail_skips_partial_first_line(self):
        p = self.root / 'large.jsonl'
        write_records(p, [{'text': 'x' * 1000}, {'text': 'last'}])
        self.assertEqual(list(common_mod.records(p, 100, tail=True)), [{'text': 'last'}])

    def test_here_is_exact_directory_and_newest_first(self):
        found = [models_mod.Session('codex', 'a', 'A', str(Path.cwd()), 10),
                 models_mod.Session('codex', 'b', 'B', str(Path.cwd() / 'other'), 20)]
        with patch.object(adapters_mod, 'codex_sessions', return_value=found):
            self.assertEqual([x.id for x in adapters_mod.discover('codex', True)], ['a'])
            self.assertEqual([x.id for x in adapters_mod.discover('codex', False)], ['b', 'a'])

    def test_resume_uses_argument_array_and_original_directory(self):
        session = models_mod.Session('claude', 'abc', 'Title', str(self.root), 0)
        with patch.object(shutil, 'which', return_value='/bin/claude'), \
             patch.object(os, 'chdir') as cd, patch.object(os, 'execv') as execute:
            launch_mod.resume(session)
        cd.assert_called_once_with(str(self.root))
        execute.assert_called_once_with('/bin/claude', ['claude', '--resume', 'abc'])
        session.tool = 'codex'
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            launch_mod.resume(session, dry_run=True)
        self.assertIn('codex resume abc', out.getvalue())
        session.cwd = str(self.root / 'missing')
        with self.assertRaisesRegex(RuntimeError, 'no longer exists'):
            launch_mod.resume(session)

    def test_alt_c_copies_quoted_resume_command_without_launching(self):
        session = models_mod.Session('claude', 'abc', 'Title', "/tmp/repo's $(name)", 0)
        copied = []
        def run(args, **kwargs):
            if args[0] == 'fzf':
                self.assertIn('--expect=alt-s,alt-c', args)
                return subprocess.CompletedProcess(args, 0, '\nalt-c\n0\tselected\n')
            self.assertEqual(args, ['/usr/bin/pbcopy'])
            copied.append(kwargs['input'])
            return subprocess.CompletedProcess(args, 0, '', '')
        with patch.object(adapters_mod, 'discover', return_value=[session]), \
             patch.object(sys, 'argv', ['fzf-sessions']), \
             patch.object(shutil, 'which', side_effect=lambda name: '/usr/bin/' + name), \
             patch.object(subprocess, 'run', side_effect=run), \
             patch.object(launch_mod, 'resume') as resume, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli_mod.main(), 0)
            resume.assert_not_called()
        self.assertEqual(shlex.split(copied[0]), ['cd', session.cwd, '&&', 'claude', '--resume', 'abc'])
        self.assertFalse(copied[0].endswith('\n'))
        session.tool = 'codex'
        self.assertEqual(shlex.split(launch_mod.resume_command(session))[-3:], ['codex', 'resume', 'abc'])

    def test_alt_c_dry_run_prints_without_touching_clipboard(self):
        session = models_mod.Session('codex', 'abc', 'Title', '/repo', 0)
        result = subprocess.CompletedProcess([], 0, '\nalt-c\n0\tselected\n')
        out = io.StringIO()
        with patch.object(subprocess, 'run', return_value=result), \
             patch.object(launch_mod, 'copy_resume_command') as copy, contextlib.redirect_stdout(out):
            self.assertIsNone(ui_mod.picker([session], '', dry_run=True))
            copy.assert_not_called()
        self.assertEqual(out.getvalue().strip(), 'cd /repo && codex resume abc')

    def test_clipboard_failure_is_reported(self):
        session = models_mod.Session('codex', 'abc', 'Title', '/repo', 0)
        with patch.object(shutil, 'which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'pbcopy'):
                launch_mod.copy_resume_command(session)
        with patch.object(shutil, 'which', return_value='/usr/bin/pbcopy'), \
             patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')):
            with self.assertRaisesRegex(RuntimeError, 'Could not copy'):
                launch_mod.copy_resume_command(session)

    def test_real_fzf_protocol_and_cancel(self):
        # fzf's noninteractive filter exercises the actual delimiter/output protocol.
        real_run = subprocess.run
        query = 'needle'
        def filtered(args, **kwargs):
            return real_run([*args, '--filter=' + query], **kwargs)
        sessions = [models_mod.Session('codex', 'abc', 'needle', '/repo', 0),
                    models_mod.Session('claude', 'def', 'other', '/elsewhere', 0)]
        with patch.object(subprocess, 'run', side_effect=filtered):
            for query in ('needle', 'repo'):
                self.assertEqual(ui_mod.picker(sessions, '').id, 'abc')
            for query in ('codex', 'abc'):
                self.assertIsNone(ui_mod.picker(sessions, ''))
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 130, '')):
            self.assertIsNone(ui_mod.picker(sessions, ''))

    def test_codex_usage_uses_latest_cumulative_snapshot_without_adding_cache(self):
        path = self.root / 'codex.jsonl'
        def snapshot(input_tokens, output_tokens, cached, context):
            return {'timestamp': '2026-11-13T10:00:00Z', 'type': 'event_msg', 'payload': {
                'type': 'token_count', 'info': {
                    'total_token_usage': {'input_tokens': input_tokens, 'output_tokens': output_tokens,
                                          'cached_input_tokens': cached, 'reasoning_output_tokens': 50},
                    'last_token_usage': {'total_tokens': context}, 'model_context_window': 100000}}}
        write_records(path, [
            {'type': 'turn_context', 'payload': {'model': 'example-model'}},
            snapshot(1000, 100, 800, 500), snapshot(3000, 300, 2400, 1000),
            snapshot(3000, 300, 2400, 1000),
            {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': None}}])
        usage = usage_mod.session_usage(models_mod.Session('codex', 'id', 'Title', '/repo', 0, str(path)))
        self.assertEqual((usage.input_tokens, usage.output_tokens, usage.cached_tokens), (3000, 300, 2400))
        self.assertEqual((usage.context_tokens, usage.context_limit), (1000, 100000))
        self.assertEqual(usage.model, 'example-model')
        lines = dict(usage_mod.usage_lines(usage, 'codex'))
        self.assertIn('1% used', lines['CONTEXT'])
        self.assertIn('80%', lines['CACHE'])

    def test_claude_usage_deduplicates_partial_responses_and_includes_cached_inputs(self):
        path = self.root / 'claude.jsonl'
        def response(mid, inputs, outputs, reads, writes, **extra):
            return dict({'type': 'assistant', 'timestamp': '2026-11-13T10:00:00Z', 'message': {
                'id': mid, 'model': 'example-claude', 'usage': {'input_tokens': inputs,
                'output_tokens': outputs, 'cache_read_input_tokens': reads,
                'cache_creation_input_tokens': writes}}}, **extra)
        write_records(path, [response('one', 10, 20, 100, 30), response('one', 10, 50, 100, 30),
                             response('one', 0, 0, 0, 0), response('two', 5, 10, 200, 0),
                             response('child', 9999, 9999, 9999, 9999, isSidechain=True),
                             {'type': 'cost-state', 'totalCostUSD': 999, 'modelUsage': {}}])
        usage = usage_mod.session_usage(models_mod.Session('claude', 'id', 'Title', '/repo', 0, str(path)))
        self.assertEqual((usage.input_tokens, usage.output_tokens, usage.cached_tokens), (345, 60, 300))
        self.assertEqual(usage.context_tokens, 205)
        self.assertIsNone(usage.context_limit)
        self.assertIn('window limit not recorded', dict(usage_mod.usage_lines(usage, 'claude'))['CONTEXT'])
        with patch.dict(os.environ, {'NO_COLOR': '1'}):
            output = previews_mod.styled_preview(models_mod.Session('claude', 'id', 'Title', '/repo', 0),
                                      'Goal: Continue work.', 'Test summary', usage)
        self.assertIn('LAST RECORDED USAGE', output)
        self.assertNotIn('999', output)
        self.assertNotIn('$', output)
        self.assertLess(output.index('TOKENS'), output.index('GOAL'))

    def test_missing_usage_is_unknown_instead_of_zero(self):
        usage = usage_mod.session_usage(models_mod.Session('codex', 'id', 'Title', '/repo', 0))
        self.assertIsNone(usage.input_tokens)
        self.assertEqual(dict(usage_mod.usage_lines(usage, 'codex'))['USAGE'], 'not recorded')
        self.assertEqual(usage_mod.compact_tokens(0), '0')
        self.assertEqual(usage_mod.compact_tokens(None), 'unknown')

    def test_summary_cache_reused_and_invalidated_when_session_changes(self):
        path = self.root / 'chat.jsonl'
        write_records(path, [{'type': 'user', 'message': {'content': 'Fix login'}}])
        session = models_mod.Session('claude', 'abc', 'Login', '/repo', 0, str(path))
        result = subprocess.CompletedProcess([], 0, 'Goal: Fix login.\nProgress: Planned.\nNext: Implement.', '')
        with patch.dict(os.environ, {'XDG_CACHE_HOME': str(self.root), 'FZF_SESSIONS_NO_AI': '0'}), \
             patch.object(summaries_mod, 'summary_backend', return_value=('/usr/bin/fm', '')), \
             patch.object(subprocess, 'run', return_value=result) as run:
            self.assertEqual(summaries_mod.ai_summary(session, 'context')[1], 'generated')
            self.assertEqual(summaries_mod.ai_summary(session, 'context')[1], 'cached')
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][3], 'system')
            with path.open('a') as stream:
                stream.write('\n')
            self.assertEqual(summaries_mod.ai_summary(session, 'new context')[1], 'generated')
            self.assertEqual(run.call_count, 2)

    def test_summary_errors_and_timeouts_fall_back(self):
        session = models_mod.Session('claude', 'id', 'Title', '/repo', 0)
        with patch.object(shutil, 'which', return_value=None):
            self.assertIsNone(summaries_mod.ai_summary(session, 'context')[0])
        with patch.object(summaries_mod, 'summary_backend', return_value=('/usr/bin/fm', '')), \
             patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'unavailable')):
            self.assertIsNone(summaries_mod.ai_summary(session, 'context')[0])
        with patch.object(summaries_mod, 'summary_backend', return_value=('/usr/bin/fm', '')), \
             patch.object(subprocess, 'run', side_effect=subprocess.TimeoutExpired('fm', 30)):
            self.assertIn('timed out', summaries_mod.ai_summary(session, 'context')[1])

    def test_preview_keeps_initial_goal_and_latest_messages_without_internal_context(self):
        path = self.root / 'chat.jsonl'
        write_records(path, [
            {'type': 'user', 'message': {'content': '<environment_context>internal</environment_context>'}},
            {'type': 'user', 'message': {'content': 'Original goal'}},
            {'type': 'assistant', 'message': {'content': 'x' * 100000}},
            {'type': 'user', 'message': {'content': 'Latest request'}},
            {'type': 'assistant', 'message': {'content': 'Latest result'}}])
        fallback, context = conversation_mod.preview_context(models_mod.Session('claude', 'id', 'Title', '/repo', 0, str(path)))
        for text in ['Original goal', 'Latest request', 'Latest result']:
            self.assertIn(text, fallback)
            self.assertIn(text, context)
        self.assertNotIn('internal', fallback)
        self.assertLessEqual(len(context), 6500)

    def test_help_is_bound_inside_fzf_without_exiting_the_current_search(self):
        path = self.root / 'chat.jsonl'
        write_records(path, [{'type': 'user', 'message': {'content': 'needle conversation'}}])
        session = models_mod.Session('claude', 'id', 'Title', '/repo', 0, str(path))
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            self.assertIn('--footer=Alt-?  shortcuts', args)
            bindings = args[args.index('--bind') + 1]
            self.assertIn('alt-?:execute-silent(', bindings)
            self.assertIn(')+clear-screen', bindings)
            self.assertNotIn('alt-?', next(arg for arg in args if arg.startswith('--expect=')))
            if len(calls) == 1:
                return subprocess.CompletedProcess(args, 0, 'needle\nalt-s\n')
            self.assertIn('--disabled', args)
            self.assertEqual(args[args.index('--query') + 1], 'needle')
            return subprocess.CompletedProcess(args, 0, 'needle\n\n0\tselected\n')
        with patch.object(subprocess, 'run', side_effect=run):
            self.assertEqual(ui_mod.picker([session], '').id, 'id')
        self.assertEqual(len(calls), 2)

    def test_help_dialog_is_centered_bounded_and_scrollable(self):
        frame, offset, maximum = help_ui_mod.help_modal_frame(True, 120, 45)
        self.assertIn('Keyboard shortcuts', frame)
        self.assertNotIn('\x1b[2J', frame)
        self.assertNotIn('\x1b[?1049h', frame)
        import re
        positions = [(int(row), int(col)) for row, col in re.findall(r'\x1b\[(\d+);(\d+)H', frame)]
        self.assertGreater(min(row for row, _ in positions), 1)
        self.assertGreater(min(col for _, col in positions), 1)
        self.assertLess(max(row for row, _ in positions), 45)
        self.assertEqual(offset, 0)
        narrow, offset, maximum = help_ui_mod.help_modal_frame(True, 60, 18, 10000)
        self.assertEqual(offset, maximum)
        self.assertIn('HERDR STATUS', narrow)
        self.assertIn('scroll', narrow)

    def test_help_modal_restores_terminal_mode_and_cursor(self):
        import select
        import termios
        import tty
        from unittest.mock import MagicMock
        terminal = MagicMock()
        terminal.__enter__.return_value = terminal
        terminal.fileno.return_value = 42
        original_mode = ['original tty state']
        with patch('builtins.open', return_value=terminal), \
             patch.object(termios, 'tcgetattr', return_value=original_mode), \
             patch.object(termios, 'tcsetattr') as restore, patch.object(tty, 'setraw') as raw, \
             patch.object(os, 'get_terminal_size', return_value=os.terminal_size((120, 45))), \
             patch.object(select, 'select', return_value=([42], [], [])), \
             patch.object(os, 'read', return_value=b'\r'):
            help_ui_mod.show_shortcut_modal(True)
        raw.assert_called_once_with(42)
        restore.assert_called_once_with(42, termios.TCSANOW, original_mode)
        output = b''.join(call.args[0] for call in terminal.write.call_args_list)
        self.assertIn(b'Keyboard shortcuts', output)
        self.assertTrue(output.endswith(b'\x1b[0m\x1b8\x1b[?25h'))

    def test_modal_escape_handles_legacy_and_enhanced_keyboard_events(self):
        for key in [b'\x1b', b'\x1b[27u', b'\x1b[27;1u', b'\x1b[27;1:1u',
                    b'\x1b[27;1:2u', b'\x1b[27;1;27~', b'\x1b?',
                    b'\x1b[63;3u', b'\x1b[47:63;4u', b'\x1b[13u', b'\x1b[99;5u']:
            with self.subTest(key=key):
                self.assertEqual(help_ui_mod.modal_key_action(key), 'close')
        self.assertEqual(help_ui_mod.modal_key_action(b'\x1b[27;1:3u'), '')
        self.assertEqual(help_ui_mod.modal_key_action(b'\x1b[63;3:3u'), '')
        self.assertEqual(help_ui_mod.modal_key_action(b'\x1b[A'), 'up')
        self.assertEqual(help_ui_mod.modal_key_action(b'\x1b[1;2B'), 'down')
        self.assertEqual(help_ui_mod.modal_key_action(b'\x1b[6~'), 'page-down')

    def test_escape_closes_help_after_fzf_restores_line_buffered_input(self):
        import pty
        import select
        import termios
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        original_mode = termios.tcgetattr(slave)
        terminal = os.fdopen(os.dup(slave), 'r+b', buffering=0)
        real_select = select.select
        calls = 0

        def fzf_pause_then_escape(readers, writers, errors, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                # Reproduce fzf's delayed Pause(false), then a lone Escape.
                # In canonical mode it remains queued until Enter or raw mode.
                termios.tcsetattr(slave, termios.TCSANOW, original_mode)
                os.write(master, b'\x1b')
            if calls > 4:
                raise AssertionError('Escape remained buffered after the fzf pause')
            return real_select(readers, writers, errors, timeout)

        with patch.object(help_ui_mod, 'open', return_value=terminal, create=True), \
             patch.object(help_ui_mod, 'help_modal_frame', return_value=('Help', 0, 0)), \
             patch.object(os, 'get_terminal_size', return_value=os.terminal_size((120, 45))), \
             patch.object(select, 'select', side_effect=fzf_pause_then_escape):
            help_ui_mod.show_shortcut_modal(True)
        self.assertGreaterEqual(calls, 2)
        restored_mode = termios.tcgetattr(slave)
        # BSD may set PENDIN while reprocessing queued input on mode changes.
        restored_mode[3] &= ~getattr(termios, 'PENDIN', 0)
        original_mode[3] &= ~getattr(termios, 'PENDIN', 0)
        self.assertEqual(restored_mode, original_mode)

    def test_modal_key_reader_keeps_adjacent_events_separate(self):
        import select
        press = b'\x1b[27;1u'
        release = b'\x1b[27;1:3u'
        data = io.BytesIO(press + release + b'\x1b[B')
        def ready(*args):
            return ([42], [], []) if data.tell() < len(data.getvalue()) else ([], [], [])
        with patch.object(os, 'read', side_effect=lambda fd, n: data.read(n)), \
             patch.object(select, 'select', side_effect=ready):
            self.assertEqual(help_ui_mod.read_modal_key(42), press)
            self.assertEqual(help_ui_mod.read_modal_key(42), release)
            self.assertEqual(help_ui_mod.read_modal_key(42), b'\x1b[B')
            self.assertEqual(help_ui_mod.read_modal_key(42), b'')
        with patch.object(os, 'read', return_value=b'\x1b'), \
             patch.object(select, 'select', return_value=([], [], [])):
            self.assertEqual(help_ui_mod.read_modal_key(42), b'\x1b')

    def test_enhanced_escape_closes_modal_and_restores_terminal(self):
        import select
        import termios
        import tty
        from unittest.mock import MagicMock
        terminal = MagicMock()
        terminal.__enter__.return_value = terminal
        terminal.fileno.return_value = 42
        data = io.BytesIO(b'\x1b[27;1u\x1b[27;1:3u')
        def ready(*args):
            return ([42], [], []) if data.tell() < len(data.getvalue()) else ([], [], [])
        with patch('builtins.open', return_value=terminal), \
             patch.object(termios, 'tcgetattr', return_value=['original']), \
             patch.object(termios, 'tcsetattr') as restore, patch.object(tty, 'setraw'), \
             patch.object(os, 'get_terminal_size', return_value=os.terminal_size((120, 45))), \
             patch.object(select, 'select', side_effect=ready), \
             patch.object(os, 'read', side_effect=lambda fd, n: data.read(n)):
            help_ui_mod.show_shortcut_modal(True)
        restore.assert_called_once_with(42, termios.TCSANOW, ['original'])
        self.assertEqual(data.read(), b'\x1b[27;1:3u')

    def test_content_preview_shows_historical_matches_and_cached_recap_without_generation(self):
        path = self.root / 'chat.jsonl'
        write_records(path, [
            {'type': 'user', 'message': {'content': 'Please fix the Straße backend.'}},
            {'type': 'assistant', 'message': {'content': 'x' * 600000}},
            {'type': 'user', 'message': {'content': 'The other topic is timeout handling.\x1b[31m'}},
            {'type': 'assistant', 'message': {'content': 'A recent unrelated reply.'}}])
        session = models_mod.Session('claude', 'id', 'Title', '/repo', 0, str(path))
        query = 'STRASSE timeout'
        excerpts = search_mod.matching_excerpts(session, query)
        text = ' '.join(body for _, body in excerpts)
        self.assertIn('Straße', text)
        self.assertIn('timeout', text)
        self.assertLessEqual(len(excerpts), 6)
        self.assertNotIn('\x1b', text)
        cache = self.root / 'summary.txt'
        cache.write_text('Goal: Fix the backend.\nProgress: Investigated.\nNext: Continue.')
        output = io.StringIO()
        with patch.dict(os.environ):
            os.environ.pop('NO_COLOR', None)
            os.environ.pop('FZF_SESSIONS_NO_AI', None)
            with patch.object(summaries_mod, 'summary_cache', return_value=cache), \
                 patch.object(summaries_mod, 'ai_summary') as generate, contextlib.redirect_stdout(output):
                previews_mod.show_preview(session, query)
                generate.assert_not_called()
        rendered = output.getvalue()
        self.assertIn('MATCHING PASSAGES', rendered)
        self.assertIn('cached recap', rendered)
        self.assertIn('\x1b[1;33mStraße\x1b[0m', rendered)
        self.assertNotIn('\x1b[31m', rendered)
        self.assertLess(rendered.index('MATCHING PASSAGES'), rendered.index('LAST RECORDED USAGE'))

    def test_content_index_excludes_injected_workspace_context(self):
        path = self.root / 'chat.jsonl'
        write_records(path, [{'type': 'user', 'message': {'content':
            '<environment_context>internal-secret-context</environment_context>Actual request'}}])
        index = search_mod.content_index([models_mod.Session('claude', 'id', 'Title', '/repo', 0, str(path))])
        self.assertIn('actual request', index[0])
        self.assertNotIn('internal-secret-context', index[0])

    def test_content_search_excludes_metadata_and_tools_and_reads_full_transcript(self):
        p = self.root / 'long.jsonl'
        write_records(p, [
            {'type': 'user', 'message': {'content': 'Historical WALRUS discussion'}},
            {'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'name': 'secret-tool'},
                {'type': 'text', 'text': 'x' * 300000}]}},
            {'type': 'assistant', 'message': {'content': 'Recent conclusion'}}])
        index = search_mod.content_index([models_mod.Session('claude', 'id', 'metadata-title', '/repo', 0, str(p))])
        rows = ['header', '0\trow']
        self.assertEqual(search_mod.content_rows(index, rows, 'walrus DISCUSSION'), rows)
        self.assertEqual(search_mod.content_rows(index, rows, 'metadata-title'), ['header'])
        self.assertEqual(search_mod.content_rows(index, rows, 'secret-tool'), ['header'])
        self.assertEqual(search_mod.content_rows(index, rows, 'walrus missing'), ['header'])

    def test_mode_switch_preserves_query_and_uses_original_session_ids(self):
        p = self.root / 'chat.jsonl'
        write_records(p, [{'type': 'user', 'message': {'content': 'unique content'}}])
        sessions = [models_mod.Session('claude', 'a', 'Unrelated', '/repo', 0),
                    models_mod.Session('claude', 'b', 'Other', '/elsewhere', 0, str(p))]
        calls = []
        real_run = subprocess.run
        def run(args, **kwargs):
            calls.append(args)
            self.assertIn('alt-p:toggle-preview', args[args.index('--bind') + 1])
            if len(calls) == 1:
                self.assertIn('--prompt=Directory / title  › ', args)
                return subprocess.CompletedProcess(args, 0, 'unique\nalt-s\n')
            self.assertIn('--disabled', args)
            self.assertEqual(args[args.index('--query') + 1], 'unique')
            self.assertIn('1\t', kwargs['input'])
            self.assertNotIn('0\t', kwargs['input'])
            bindings = args[args.index('--bind') + 1]
            command = bindings.split('change:reload(', 1)[1][:-1]
            result = real_run(command.replace('{q}', shlex.quote("missing $(false) '")),
                              shell=True, text=True, capture_output=True, check=True)
            self.assertEqual(len(result.stdout.splitlines()), 1)
            row = kwargs['input'].splitlines()[1]
            return subprocess.CompletedProcess(args, 0, 'unique\n\n' + row + '\n')
        with patch.object(subprocess, 'run', side_effect=run):
            self.assertEqual(ui_mod.picker(sessions, '').id, 'b')
        self.assertEqual(len(calls), 2)

    def test_preview_command_handles_shell_metacharacters(self):
        def inspect(args, **kwargs):
            command = args[args.index('--preview') + 1].replace('{1}', '0')
            result = real_run(command, shell=True, text=True, capture_output=True, check=True,
                              env=dict(os.environ, FZF_SESSIONS_NO_AI='1'))
            self.assertIn('/repo', result.stdout)
            return subprocess.CompletedProcess(args, 130, '')
        real_run = subprocess.run
        with patch.object(subprocess, 'run', side_effect=inspect):
            self.assertIsNone(ui_mod.picker([models_mod.Session('codex', 'abc', "Title $(false)", '/repo', 0)], ''))


if __name__ == '__main__':
    unittest.main()
