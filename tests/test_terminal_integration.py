"""Real PTY tests. Use FZF_SESSIONS_REQUIRE_PTY=1 in unrestricted CI."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

from fzf_sessions import dependencies


class TerminalIntegrationTests(unittest.TestCase):
    def check_case(self, name):
        try:
            dependencies.require_fzf()
        except RuntimeError as exc:
            if os.environ.get('FZF_SESSIONS_REQUIRE_PTY') == '1':
                self.fail(str(exc))
            self.skipTest(str(exc))
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('pty_driver.py')), name],
                                text=True, capture_output=True, timeout=25)
        if result.returncode == 77:
            if os.environ.get('FZF_SESSIONS_REQUIRE_PTY') == '1':
                self.fail(result.stdout)
            self.skipTest(result.stdout.strip())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_modal_escape_resize_and_terminal_restoration(self):
        self.check_case('modal')

    def test_picker_help_full_title_and_content_preview(self):
        self.check_case('picker')

    def test_refresh_while_typing_then_jump_to_existing_workspace(self):
        self.check_case('refresh')
