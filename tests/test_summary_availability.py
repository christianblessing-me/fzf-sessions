"""Optional on-device summaries must degrade to readable saved messages."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from fzf_sessions import models, previews, summaries


class SummaryAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {'XDG_CACHE_HOME': self.temp.name, 'FZF_SESSIONS_NO_AI': '0'}).start()
        self.platform = patch.object(summaries.platform, 'system', return_value='Darwin').start()
        self.which = patch.object(summaries.shutil, 'which', return_value='/usr/bin/fm').start()
        self.run = patch.object(summaries.subprocess, 'run').start()
        self.session = models.Session('claude', 'test', 'Title', '/repo', 0)

    def test_other_operating_systems_never_invoke_fm(self):
        for system in ('Linux', 'Windows'):
            with self.subTest(system=system):
                self.platform.return_value = system
                value, reason = summaries.ai_summary(self.session, 'context')
                self.assertIsNone(value)
                self.assertIn('require macOS', reason)
        self.which.assert_not_called()
        self.run.assert_not_called()

    def test_missing_cli_explains_path_requirement(self):
        self.which.return_value = None
        value, reason = summaries.summary_backend()
        self.assertIsNone(value)
        self.assertIn('PATH', reason)
        self.run.assert_not_called()

    def test_system_available_even_when_pcc_is_unavailable(self):
        self.run.return_value = subprocess.CompletedProcess([], 1,
            '\x1b[32m  ✓ system ()\x1b[0m\n  ✗ pcc (Sign in to iCloud.)', '')
        self.assertEqual(summaries.summary_backend(), ('/usr/bin/fm', ''))
        self.assertEqual(self.run.call_args.args[0], ['/usr/bin/fm', 'models'])
        self.assertEqual(self.run.call_args.kwargs['timeout'], 3)

    def test_missing_model_explains_reason_without_generating(self):
        self.run.return_value = subprocess.CompletedProcess([], 1,
            '  ✗ system (Apple Intelligence is disabled.)\n  ✓ pcc', '')
        generating = Mock()
        value, reason = summaries.ai_summary(self.session, 'context', on_generate=generating)
        self.assertIsNone(value)
        self.assertIn('Apple Intelligence is disabled', reason)
        self.assertEqual(self.run.call_count, 1)
        generating.assert_not_called()

    def test_probe_errors_and_unknown_output_fall_back(self):
        for failure in (OSError('cannot start'), subprocess.TimeoutExpired('fm', 3)):
            with self.subTest(failure=failure):
                self.run.side_effect = failure
                self.assertIsNone(summaries.summary_backend()[0])
        self.run.side_effect = None
        self.run.return_value = subprocess.CompletedProcess([], 0, 'unexpected format', '')
        self.assertIsNone(summaries.summary_backend()[0])

    def test_cached_recaps_remain_available_without_the_model(self):
        self.platform.return_value = 'Linux'
        cache = summaries.summary_cache(self.session, 'context')
        cache.parent.mkdir(parents=True)
        cache.write_text('Goal: Saved recap.')
        self.assertEqual(summaries.ai_summary(self.session, 'context'), ('Goal: Saved recap.', 'cached'))
        self.platform.assert_not_called()
        self.run.assert_not_called()

    def test_preview_shows_platform_reason_without_a_generating_message(self):
        self.platform.return_value = 'Linux'
        transcript = Path(self.temp.name) / 'session.jsonl'
        transcript.write_text('{"type":"user","message":{"content":"Please fix login"}}\n')
        self.session.transcript = str(transcript)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            previews.show_preview(self.session)
        self.assertIn('Please fix login', output.getvalue())
        self.assertIn('require macOS', output.getvalue())
        self.assertNotIn('Generating', output.getvalue())
        self.run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
