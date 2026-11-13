"""Release installation and diagnostics, isolated from real user histories."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fzf_sessions import __version__, dependencies, doctor

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sessions_installer', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prefix = self.root / 'prefix with spaces'

    def test_cli_version_and_manifest_match_canonical_version(self):
        result = subprocess.run([sys.executable, str(ROOT / 'fzf-sessions'), '--version'],
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), f'fzf-sessions {__version__}')
        self.assertIn(f'\nversion = "{__version__}"\n', (ROOT / 'herdr-plugin.toml').read_text())

    def test_install_upgrade_and_uninstall_from_installed_copy(self):
        def run(*arguments, **kwargs):
            return subprocess.run([sys.executable, *map(str, arguments)], capture_output=True,
                                  text=True, check=True, **kwargs)
        run(ROOT / 'install.py', '--prefix', self.prefix)
        command = self.prefix / 'bin/fzf-sessions'
        target = self.prefix / 'share/fzf-sessions'
        # No imports or files may come from the checkout.
        env = dict(os.environ, PYTHONPATH='', HERDR_ENV='0', CODEX_HOME=str(self.root / 'empty-codex'),
                   CLAUDE_CONFIG_DIR=str(self.root / 'empty-claude'))
        self.assertEqual(run(command, '--version', cwd=self.root, env=env).stdout.strip(),
                         f'fzf-sessions {__version__}')
        self.assertEqual(run(command, '--list', cwd=self.root, env=env).stdout.strip(), '[]')
        (target / 'old-file').write_text('obsolete')
        run(ROOT / 'install.py', '--prefix', self.prefix)
        self.assertFalse((target / 'old-file').exists())
        sentinel = self.prefix / 'share/another-tool'
        sentinel.write_text('keep')
        run(target / 'install.py', '--prefix', self.prefix, '--uninstall')
        self.assertFalse(command.is_symlink())
        self.assertFalse(target.exists())
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_installer_refuses_unrelated_commands_and_directories(self):
        command = self.prefix / 'bin/fzf-sessions'
        command.parent.mkdir(parents=True)
        command.write_text('unrelated')
        with self.assertRaisesRegex(RuntimeError, 'unrelated command'):
            installer.install(self.prefix)
        self.assertEqual(command.read_text(), 'unrelated')
        command.unlink()
        target = self.prefix / 'share/fzf-sessions'
        target.mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'unmanaged directory'):
            installer.install(self.prefix, uninstall=True)

    def test_failed_upgrade_restores_previous_installation(self):
        with contextlib.redirect_stdout(io.StringIO()):
            installer.install(self.prefix)
        command = self.prefix / 'bin/fzf-sessions'
        target = self.prefix / 'share/fzf-sessions'
        command.unlink()
        with patch.object(Path, 'symlink_to', side_effect=OSError('simulated failure')):
            with self.assertRaises(OSError):
                installer.install(self.prefix)
        self.assertTrue(installer.managed(target))
        self.assertEqual((target / 'VERSION').read_text().strip(), __version__)

    def test_doctor_is_read_only_and_optional_components_do_not_fail(self):
        env = {'CODEX_HOME': str(self.root / 'codex'), 'CLAUDE_CONFIG_DIR': str(self.root / 'claude'),
               'HERDR_ENV': '0', 'HERDR_BIN_PATH': '', 'FZF_SESSIONS_NO_AI': '0'}
        output = io.StringIO()
        with patch.dict(os.environ, env), \
             patch.object(dependencies, 'require_fzf', return_value='/fake/fzf'), \
             patch.object(shutil, 'which', return_value=None), \
             patch.object(doctor.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '0.74.5', '')) as run, \
             patch.object(doctor.summaries, 'summary_backend', return_value=(None, 'requires macOS')), \
             contextlib.redirect_stdout(output):
            self.assertEqual(doctor.doctor(), 0)
        self.assertIn('0.74.5', output.getvalue())
        self.assertIn('requires macOS', output.getvalue())
        self.assertEqual([call.args[0] for call in run.call_args_list], [['/fake/fzf', '--version']])

    def test_linux_dependency_hint_does_not_suggest_homebrew(self):
        with patch.object(dependencies.sys, 'platform', 'linux'):
            self.assertNotIn('brew', dependencies.fzf_install_hint())
            self.assertIn('releases', dependencies.fzf_install_hint())

    def test_doctor_returns_failure_for_a_missing_required_dependency(self):
        with patch.dict(os.environ, {'HERDR_ENV': '0', 'HERDR_BIN_PATH': '', 'FZF_SESSIONS_NO_AI': '1'}), \
             patch.object(dependencies, 'require_fzf', side_effect=RuntimeError('fzf missing')), \
             patch.object(shutil, 'which', return_value=None), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(doctor.doctor(), 1)
        self.assertIn('fzf: ERROR', output.getvalue())


if __name__ == '__main__':
    unittest.main()
