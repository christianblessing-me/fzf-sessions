from fzf_sessions import dependencies as dependencies_mod
import shutil
from fzf_sessions import cli as cli_mod
from fzf_sessions import herdr as herdr_mod
from fzf_sessions import launch as launch_mod
from fzf_sessions import models as models_mod
from fzf_sessions import previews as previews_mod
from fzf_sessions import search as search_mod
from fzf_sessions import ui as ui_mod
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'fzf-sessions'


class HerdrTests(unittest.TestCase):
    def setUp(self):
        for name in ('require_fzf', 'require_herdr'):
            check = patch.object(dependencies_mod, name, return_value='/test/checked')
            check.start()
            self.addCleanup(check.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.context = {'HERDR_ENV': '1', 'HERDR_WORKSPACE_ID': 'w-test', 'HERDR_BIN_PATH': '/test/herdr'}

    def test_outside_herdr_cannot_control_focused_session(self):
        with patch.dict(os.environ, {'HERDR_ENV': '0'}), patch.object(subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'inside a Herdr pane'):
                herdr_mod.open_herdr_picker()
            run.assert_not_called()
        with patch.dict(os.environ, dict(self.context, HERDR_WORKSPACE_ID='',
                                         FZF_SESSIONS_HERDR_WORKSPACE='', HERDR_PLUGIN_CONTEXT_JSON='{}')):
            with self.assertRaisesRegex(RuntimeError, 'calling workspace'):
                herdr_mod.herdr_context()

    def test_popup_context_without_pane_workspace_environment(self):
        env = dict(self.context, HERDR_WORKSPACE_ID='', FZF_SESSIONS_HERDR_WORKSPACE='',
                   HERDR_PLUGIN_CONTEXT_JSON=json.dumps({'workspace_id': 'source-workspace'}))
        with patch.dict(os.environ, env):
            self.assertEqual(herdr_mod.herdr_context(), ('/test/herdr', 'source-workspace'))
        env['FZF_SESSIONS_HERDR_WORKSPACE'] = 'original-workspace'
        with patch.dict(os.environ, env):
            self.assertEqual(herdr_mod.herdr_context(), ('/test/herdr', 'original-workspace'))

    def test_popup_startup_error_remains_visible_until_dismissed(self):
        env = dict(self.context, HERDR_WORKSPACE_ID='', FZF_SESSIONS_HERDR_WORKSPACE='',
                   HERDR_PLUGIN_CONTEXT_JSON='{}', HERDR_PLUGIN_ID='fzf-sessions',
                   HERDR_PLUGIN_ENTRYPOINT_ID='picker')
        output = io.StringIO()
        with patch.dict(os.environ, env), patch.object(sys, 'argv', ['fzf-sessions', '--herdr']), \
             patch.object(sys.stdin, 'isatty', return_value=True), \
             patch('builtins.input', return_value='') as dismiss, contextlib.redirect_stderr(output):
            self.assertEqual(cli_mod.main(), 1)
            dismiss.assert_called_once()
        self.assertIn('calling workspace', output.getvalue())
        self.assertIn('Press Enter to close', output.getvalue())

    def test_popup_open_does_not_pass_unsupported_targeting(self):
        with patch.dict(os.environ, self.context), patch.object(herdr_mod, 'herdr_call', return_value={}) as call:
            herdr_mod.open_herdr_picker()
        call.assert_called_once_with('/test/herdr', ['plugin', 'pane', 'open', '--plugin', 'fzf-sessions',
                                                     '--entrypoint', 'picker', '--env',
                                                     'FZF_SESSIONS_HERDR_WORKSPACE=w-test', '--focus'])

    def test_action_cli_opens_popup_without_workspace_parameter(self):
        def run(args, **kwargs):
            if '--workspace' in args or '--target-pane' in args:
                return subprocess.CompletedProcess(args, 1, '',
                    'invalid_params: overlay and popup plugin panes target the active pane')
            return subprocess.CompletedProcess(args, 0, '{"result": {"type": "ok"}}', '')
        with patch.dict(os.environ, self.context), \
             patch.object(sys, 'argv', ['fzf-sessions', '--herdr-open']), \
             patch.object(subprocess, 'run', side_effect=run) as call:
            self.assertEqual(cli_mod.main(), 0)
        self.assertEqual(call.call_count, 1)

    def test_resuming_uses_returned_ids_and_shell_quotes(self):
        session = models_mod.Session('claude', 'session-id', 'Fix login', str(self.root), 0)
        responses = [{'agents': []}, {'root_pane': {'pane_id': 'opaque-pane'}, 'tab': {'tab_id': 'opaque-tab'}}, {}, {}]
        with patch.dict(os.environ, self.context), patch.object(shutil, 'which', return_value='/bin/claude'), \
             patch.object(herdr_mod, 'herdr_call', side_effect=responses) as call:
            herdr_mod.resume_herdr(session)
        calls = [c.args[1] for c in call.call_args_list]
        self.assertEqual(calls.pop(0), ['agent', 'list'])
        self.assertEqual(calls[0][:5], ['tab', 'create', '--workspace', 'w-test', '--cwd'])
        self.assertIn('--no-focus', calls[0])
        self.assertEqual(calls[1], ['pane', 'run', 'opaque-pane', launch_mod.resume_command(session)])
        self.assertEqual(calls[2], ['tab', 'focus', 'opaque-tab'])

    def test_failed_submission_does_not_retry_or_close_tabs(self):
        session = models_mod.Session('codex', 'id', 'Title', str(self.root), 0)
        created = {'root_pane': {'pane_id': 'new-pane'}, 'tab': {'tab_id': 'new-tab'}}
        with patch.dict(os.environ, self.context), patch.object(shutil, 'which', return_value='/bin/codex'), \
             patch.object(herdr_mod, 'herdr_call', side_effect=[{'agents': []}, created, RuntimeError('not ready')]) as call:
            with self.assertRaisesRegex(RuntimeError, 'Inspect that tab before retrying'):
                herdr_mod.resume_herdr(session)
        self.assertEqual(call.call_count, 3)

    def test_dry_run_and_missing_directory_never_create_tabs(self):
        session = models_mod.Session('codex', 'id', 'Title', str(self.root / 'missing'), 0)
        output = io.StringIO()
        with patch.dict(os.environ, self.context), patch.object(herdr_mod, 'herdr_call', return_value={'agents': []}) as call:
            with contextlib.redirect_stdout(output):
                herdr_mod.resume_herdr(session, dry_run=True)
            self.assertIn('codex resume id', output.getvalue())
            with self.assertRaisesRegex(RuntimeError, 'no longer exists'):
                herdr_mod.resume_herdr(session)
            call.assert_called_once_with('/test/herdr', ['agent', 'list'], timeout=3)

    def test_enter_focuses_exact_live_pane_and_prefers_calling_workspace(self):
        # No local CLI or directory is needed to focus an already running agent.
        session = models_mod.Session('codex', 'selected-id', 'Title', '/missing-directory', 0)
        def agent(sid, pane, workspace):
            return {'agent': 'codex', 'agent_session': {'agent': 'codex', 'kind': 'id', 'value': sid},
                    'pane_id': pane, 'tab_id': 'different-tab', 'workspace_id': workspace}
        agents = [agent('another-session', 'wrong-pane', 'w-test'),
                  agent('selected-id', 'remote-workspace-pane', 'w-other'),
                  agent('selected-id', 'local-workspace-pane', 'w-test')]
        with patch.dict(os.environ, self.context), \
             patch.object(herdr_mod, 'herdr_call', side_effect=[{'agents': agents}, {}]) as call:
            herdr_mod.resume_herdr(session)
        self.assertEqual([c.args[1] for c in call.call_args_list],
                         [['agent', 'list'], ['agent', 'focus', 'local-workspace-pane']])

    def test_enter_jumps_across_workspaces_before_background_detection_finished(self):
        session = models_mod.Session('claude', 'selected-id', 'Title', '/missing-directory', 0)
        agent = {'agent': 'claude', 'agent_session': {'agent': 'claude', 'kind': 'id', 'value': 'selected-id'},
                 'pane_id': 'other-pane', 'tab_id': 'other-tab', 'workspace_id': 'other-workspace'}
        self.assertFalse(session.herdr_checked)
        with patch.dict(os.environ, self.context), \
             patch.object(herdr_mod, 'herdr_call', side_effect=[{'agents': [agent]}, {}]) as call:
            herdr_mod.resume_herdr(session)
        self.assertEqual(call.call_args.args[1], ['agent', 'focus', 'other-pane'])
        self.assertEqual(call.call_count, 2)

    def test_stale_marker_and_failed_focus_never_create_duplicates(self):
        session = models_mod.Session('codex', 'id', 'Title', '/repo', 0,
                            herdr_locations=[{'pane_id': 'old-pane', 'workspace_id': 'w-test'}])
        with patch.dict(os.environ, self.context), \
             patch.object(herdr_mod, 'herdr_call', return_value={'agents': []}) as call:
            with self.assertRaisesRegex(RuntimeError, 'Reopen the picker'):
                herdr_mod.resume_herdr(session)
            self.assertEqual(call.call_count, 1)
        agent = {'agent': 'codex', 'agent_session': {'agent': 'codex', 'kind': 'id', 'value': 'id'},
                 'pane_id': 'pane', 'workspace_id': 'w-test'}
        with patch.dict(os.environ, self.context), \
             patch.object(herdr_mod, 'herdr_call', side_effect=[{'agents': [agent]}, RuntimeError('focus failed')]) as call:
            with self.assertRaisesRegex(RuntimeError, 'no additional session was opened'):
                herdr_mod.resume_herdr(session)
            self.assertEqual(call.call_count, 2)
        with patch.dict(os.environ, self.context), \
             patch.object(herdr_mod, 'herdr_call', return_value={}) as call:
            with self.assertRaisesRegex(RuntimeError, 'live agent list'):
                herdr_mod.resume_herdr(session)
            self.assertEqual(call.call_count, 1)

    def test_detects_exact_session_ids_across_workspaces_and_tabs(self):
        first = models_mod.Session('codex', 'first-id', 'First', '/same-repo', 0)
        second = models_mod.Session('claude', 'second-id', 'Second', '/same-repo', 0)
        other = models_mod.Session('claude', 'different-id', 'Other session in same repo', '/same-repo', 0)
        def agent(tool, sid, pane, tab, workspace, **extra):
            return dict({'agent': tool, 'agent_session': {'agent': tool, 'kind': 'id', 'value': sid},
                         'pane_id': pane, 'tab_id': tab, 'workspace_id': workspace,
                         'agent_status': 'working'}, **extra)
        a = agent('codex', 'FIRST-ID', 'pane-a', 'tab-a', 'workspace-a')
        b = agent('claude', 'second-id', 'pane-b', 'tab-b', 'workspace-b')
        c = agent('claude', 'second-id', 'pane-c', 'tab-c', 'workspace-b')
        stale = agent('claude', 'different-id', 'pane-stale', 'tab-c', 'workspace-b', agent=None)
        snapshot = {'workspaces': [{'workspace_id': 'workspace-a', 'label': 'Backend'},
                                   {'workspace_id': 'workspace-b', 'label': 'Website'}],
                    'tabs': [{'tab_id': 'tab-a', 'label': 'API'}, {'tab_id': 'tab-b', 'label': 'Login'},
                             {'tab_id': 'tab-c', 'label': 'Tests'}],
                    'agents': [a, b, c], 'panes': [a, b, c, stale]}
        with patch.dict(os.environ, self.context), \
             patch.object(herdr_mod, 'herdr_call', return_value={'snapshot': snapshot}) as call:
            note = herdr_mod.annotate_herdr_sessions([first, second, other])
        call.assert_called_once_with('/test/herdr', ['api', 'snapshot'], timeout=3)
        self.assertEqual(note, '2 detected open in Herdr')
        self.assertEqual(len(first.herdr_locations), 1)  # pane/agent snapshots refer to the same pane
        self.assertEqual(len(second.herdr_locations), 2)
        self.assertTrue(other.herdr_checked)
        self.assertEqual(other.herdr_locations, [])  # same cwd never implies the same session
        self.assertEqual(herdr_mod.herdr_location_label(second), '●')
        output = previews_mod.styled_preview(second, 'Goal: Work.', 'Summary')
        self.assertIn('OPEN IN HERDR', output)
        self.assertIn('Website / Login', output)
        self.assertIn('Website / Tests', output)

    def test_path_session_references_are_matched_by_exact_transcript_path(self):
        path = self.root / 'chat.jsonl'
        session = models_mod.Session('claude', 'id', 'Title', '/repo', 0, str(path))
        snapshot = {'workspaces': [], 'tabs': [], 'panes': [], 'agents': [
            {'agent': 'claude', 'agent_session': {'agent': 'claude', 'kind': 'path', 'value': str(path)},
             'pane_id': 'pane', 'tab_id': 'tab', 'workspace_id': 'workspace'}]}
        with patch.dict(os.environ, self.context), \
             patch.object(herdr_mod, 'herdr_call', return_value={'snapshot': snapshot}):
            herdr_mod.annotate_herdr_sessions([session])
        self.assertEqual(session.herdr_locations[0]['pane_id'], 'pane')

    def test_detection_failure_is_unknown_and_outside_herdr_does_not_query(self):
        session = models_mod.Session('codex', 'id', 'Title', '/repo', 0)
        with patch.dict(os.environ, {'HERDR_ENV': '0'}), patch.object(herdr_mod, 'herdr_call') as call:
            self.assertEqual(herdr_mod.annotate_herdr_sessions([session]), '')
            call.assert_not_called()
        with patch.dict(os.environ, self.context), \
             patch.object(herdr_mod, 'herdr_call', side_effect=RuntimeError('socket unavailable')):
            self.assertEqual(herdr_mod.annotate_herdr_sessions([session]), 'Herdr status unavailable')
        self.assertFalse(session.herdr_checked)
        self.assertEqual(herdr_mod.herdr_location_label(session), '?')
        with patch.dict(os.environ, self.context), patch.object(herdr_mod, 'herdr_call', return_value={}):
            self.assertEqual(herdr_mod.annotate_herdr_sessions([session]), 'Herdr status unavailable')

    def test_picker_opens_before_herdr_lookup_finishes_and_refreshes_rows(self):
        session = models_mod.Session('codex', 'id', 'Title', '/repo', 0)
        started, release = threading.Event(), threading.Event()
        real_run = subprocess.run
        def annotate(sessions):
            started.set()
            self.assertTrue(release.wait(2))
            sessions[0].herdr_checked = True
            sessions[0].herdr_locations = [{'workspace': 'A very long workspace name', 'tab': 'A long tab name',
                'pane_id': 'pane', 'tab_id': 'tab', 'workspace_id': 'workspace', 'status': 'idle'}]
            return '1 detected open in Herdr'
        def run(args, **kwargs):
            self.assertTrue(started.wait(1))
            self.assertFalse(release.is_set())  # fzf is reached while the API is still waiting.
            self.assertIn('OPEN', kwargs['input'])
            self.assertNotIn('A very long workspace', kwargs['input'])
            bindings = args[args.index('--bind') + 1]
            self.assertIn('load:unbind(load)+bg-transform(', bindings)
            command = bindings.split('load:unbind(load)+bg-transform(', 1)[1][:-1]
            release.set()
            action = real_run(command, shell=True, capture_output=True, text=True, timeout=5, check=True).stdout.strip()
            self.assertTrue(action.startswith('reload('))
            reload_command = action[len('reload('):-len(')+refresh-preview')].replace(
                '{q}', shlex.quote(args[args.index('--query') + 1]))
            result = real_run(reload_command, shell=True, capture_output=True, text=True, timeout=3, check=True)
            self.assertIn('●', result.stdout)
            self.assertNotIn('A very long workspace', result.stdout)
            state_file = Path(shlex.split(command)[3])
            data = json.loads(state_file.read_text())['sessions']
            self.assertEqual(data[0]['herdr_locations'][0]['workspace'], 'A very long workspace name')
            return subprocess.CompletedProcess(args, 130, '')
        with patch.object(herdr_mod, 'annotate_herdr_sessions', side_effect=annotate), \
             patch.object(subprocess, 'run', side_effect=run):
            self.assertIsNone(ui_mod.picker([session], '', herdr_note='checking'))

    def test_open_sessions_sort_first_without_changing_selection_identity(self):
        sessions = [models_mod.Session('codex', 'closed-old', 'needle closed old', '/repo', 300),
                    models_mod.Session('codex', 'open-old', 'needle open old', '/repo', 100, herdr_locations=[{}]),
                    models_mod.Session('codex', 'open-new', 'needle open new', '/repo', 200, herdr_locations=[{}]),
                    models_mod.Session('codex', 'closed-new', 'needle closed new', '/repo', 400)]
        real_run = subprocess.run
        def filtered(args, **kwargs):
            self.assertIn('--no-sort', args)
            ids = [int(row.split('\t', 1)[0]) for row in kwargs['input'].splitlines()[1:]]
            self.assertEqual(ids, [2, 1, 3, 0])
            return real_run([*args, '--filter=needle'], **kwargs)
        with patch.object(herdr_mod, 'annotate_herdr_sessions', return_value=''), \
             patch.object(subprocess, 'run', side_effect=filtered):
            selected = ui_mod.picker(sessions, '', herdr_note='open sessions first')
        self.assertEqual(selected.id, 'open-new')

    def test_content_matching_uses_ids_after_active_sessions_are_reordered(self):
        rows = ['header', '2\topen matching', '1\topen unrelated', '0\tclosed matching']
        index = ['needle in closed session', 'unrelated conversation', 'needle in open session']
        self.assertEqual(search_mod.content_rows(index, rows, 'needle'),
                         ['header', '2\topen matching', '0\tclosed matching'])

    def test_alt_r_refreshes_status_while_preserving_content_mode_and_query(self):
        transcript = self.root / 'chat.jsonl'
        transcript.write_text(json.dumps({'type': 'user', 'message': {'content': 'needle conversation'}}) + '\n')
        session = models_mod.Session('codex', 'id', 'Title', '/repo', 0, str(transcript))
        # Use Claude records for this fixture's content parser.
        session.tool = 'claude'
        refreshes = []
        invocations = []
        real_run = subprocess.run
        def annotate(sessions):
            refreshes.append(1)
            sessions[0].herdr_checked = True
            sessions[0].herdr_locations = ([{'workspace': 'Work', 'tab': 'Tab', 'pane_id': 'pane',
                'workspace_id': 'workspace', 'tab_id': 'tab', 'status': 'idle'}] if len(refreshes) == 1 else [])
            return 'updated'
        def run(args, **kwargs):
            invocations.append(args)
            self.assertIn('--expect=alt-s,alt-c,alt-r', args)
            bindings = args[args.index('--bind') + 1]
            command = bindings.split('load:unbind(load)+bg-transform(', 1)[1][:-1]
            action = real_run(command, shell=True, capture_output=True, text=True, timeout=5, check=True).stdout.strip()
            self.assertTrue(action.startswith('reload('))
            reload_command = action[len('reload('):-len(')+refresh-preview')].replace(
                '{q}', shlex.quote(args[args.index('--query') + 1]))
            result = real_run(reload_command, shell=True, capture_output=True, text=True, timeout=3, check=True)
            if len(invocations) == 1:
                self.assertIn('●', result.stdout)
                return subprocess.CompletedProcess(args, 0, 'needle\nalt-s\n')
            self.assertIn('--disabled', args)
            self.assertEqual(args[args.index('--query') + 1], 'needle')
            self.assertIn(' content {q}', args[args.index('--preview') + 1])
            if len(invocations) == 2:
                return subprocess.CompletedProcess(args, 0, 'needle\nalt-r\n')
            self.assertEqual(len(refreshes), 2)
            self.assertNotIn('●', result.stdout)
            self.assertIn('—', result.stdout)
            return subprocess.CompletedProcess(args, 130, '')
        with patch.object(herdr_mod, 'annotate_herdr_sessions', side_effect=annotate), \
             patch.object(subprocess, 'run', side_effect=run):
            self.assertIsNone(ui_mod.picker([session], '', herdr_note='checking'))
        self.assertEqual(len(invocations), 3)

    def test_content_search_uses_refreshed_marker_rows(self):
        path = self.root / 'rows.tsv'
        path.write_text('header\n0\t● updated row\n1\t— other row')
        data = {'index': ['matching phrase', 'other text'], 'rows': ['header', '0\t?', '1\t?'],
                'herdr_rows': str(path)}
        self.assertEqual(search_mod.search_rows(data, 'matching'), ['header', '0\t● updated row'])

    def test_end_to_end_cli_uses_manifest_launch_mode(self):
        # Launch the actual Python CLI with fixture history and fake external commands.
        # No real Herdr server or coding agent is contacted.
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        log = self.root / 'calls.jsonl'
        fake_herdr = bin_dir / 'herdr'
        fake_herdr.write_text(f'''#!{sys.executable}
import json,os,sys
from pathlib import Path
if sys.argv[1:] == ['--version']:
 print('herdr 0.9.5');sys.exit(0)
with Path(os.environ['TEST_HERDR_LOG']).open('a') as f:
 f.write(json.dumps(sys.argv[1:])+'\\n')
result = {{'tab': {{'tab_id': 'w7:t19'}}, 'root_pane': {{'pane_id': 'w7:p23'}}}} if sys.argv[1:3] == ['tab','create'] else ({{'agents': json.loads(os.environ.get('TEST_OPEN_AGENTS','[]'))}} if sys.argv[1:3] == ['agent','list'] else {{}})
print(json.dumps({{'ok': True, 'result': result}}))
''')
        fake_fzf = bin_dir / 'fzf'
        fake_fzf.write_text(f'''#!{sys.executable}
import sys
if sys.argv[1:] == ['--version']:
 print('0.74.5');sys.exit(0)
rows=sys.stdin.read().splitlines()
print('')
print('')
print(rows[1])
''')
        fake_codex = bin_dir / 'codex'
        fake_codex.write_text('#!/bin/sh\nexit 99\n')
        for path in (fake_herdr, fake_fzf, fake_codex):
            path.chmod(0o755)
        repo = self.root / "repo's $(name)"
        repo.mkdir()
        history = self.root / 'codex/sessions/2026/11/13/chat.jsonl'
        history.parent.mkdir(parents=True)
        history.write_text(json.dumps({'type': 'session_meta', 'payload': {
            'id': 'uuid-test', 'cwd': str(repo), 'source': 'cli'}}) + '\n')
        env = dict(os.environ, HERDR_ENV='1', HERDR_WORKSPACE_ID='w-test', HERDR_BIN_PATH=str(fake_herdr),
                   TEST_HERDR_LOG=str(log), CODEX_HOME=str(self.root / 'codex'),
                   PATH=str(bin_dir) + os.pathsep + os.environ['PATH'])
        result = subprocess.run([sys.executable, str(SCRIPT), '--herdr', '--tool', 'codex'],
                                env=env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        calls = [call for call in calls if call not in (['api', 'snapshot'], ['agent', 'list'])]
        self.assertEqual(calls[1][:3], ['pane', 'run', 'w7:p23'])
        self.assertEqual(shlex.split(calls[1][3]), ['cd', str(repo), '&&', 'codex', 'resume', 'uuid-test'])
        self.assertEqual(calls[2], ['tab', 'focus', 'w7:t19'])
        # The fake agent would fail if the standalone resume path were called.
        self.assertEqual(len(calls), 3)
        log.write_text('')
        env['TEST_OPEN_AGENTS'] = json.dumps([{
            'agent': 'codex', 'agent_session': {'agent': 'codex', 'kind': 'id', 'value': 'uuid-test'},
            'pane_id': 'existing-pane', 'tab_id': 'existing-tab', 'workspace_id': 'another-workspace'}])
        result = subprocess.run([sys.executable, str(SCRIPT), '--herdr', '--tool', 'codex'],
                                env=env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        calls = [call for call in calls if call not in (['api', 'snapshot'], ['agent', 'list'])]
        self.assertEqual(calls, [['agent', 'focus', 'existing-pane']])


if __name__ == '__main__':
    unittest.main()
