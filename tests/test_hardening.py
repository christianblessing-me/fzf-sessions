"""Regression tests for input drift, complete-title search, caches and requirements."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from fzf_sessions import adapters, common, conversation, dependencies, models, search, summaries, usage


class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def index(self, sessions, rows, preserve=True):
        initial, live = self.root / 'initial.tsv', self.root / 'live.tsv'
        initial.write_text('\n'.join(rows))
        return search.SearchIndex.create(self.root / 'search.sqlite', sessions, initial, live, preserve)

    def test_full_title_search_does_not_expand_the_displayed_column(self):
        sessions = [models.Session('claude', 'a', 'A' * 60 + ' unique_suffix', '/parent/repo', 0),
                    models.Session('codex', 'b', 'Another topic', '/elsewhere', 0)]
        rows = ['header', '0\t' + 'A' * 49 + '…\trepo', '1\tAnother topic\telsewhere']
        index = self.index(sessions, rows)
        self.assertEqual(index.rows('metadata', 'unique_suffix'), rows[:2])
        self.assertEqual(index.rows('metadata', 'repo'), rows[:2])
        for query in ('claude', 'parent', 'does-not-exist'):
            self.assertEqual(index.rows('metadata', query), ['header'])
        self.assertLessEqual(len(index.rows('metadata', 'unique_suffix')[1].split('\t')[1]), 50)

    def test_sqlite_content_search_keeps_ids_order_and_literal_semantics(self):
        path = self.root / 'chat.jsonl'
        path.write_text(json.dumps({'type': 'user', 'message': {'content': 'Straße token $(literal)'}}) + '\n')
        sessions = [models.Session('claude', 'a', 'needle title', '/repo', 0, str(path)),
                    models.Session('claude', 'b', 'needle title', '/repo', 0)]
        rows = ['header', '1\tsecond', '0\tfirst']
        index = self.index(sessions, rows)
        index.enable_content(sessions)
        index.enable_content(sessions)  # Idempotent; messages are not duplicated.
        self.assertEqual(index.rows('content', 'STRASSE $(literal)'), ['header', '0\tfirst'])
        self.assertEqual(index.rows('content', 'needle'), ['header'])
        self.assertEqual(len(list(index.messages(0))), 1)
        self.assertEqual(index.rows('metadata', 'needle'), rows)

    def test_unexpected_shapes_are_skipped_without_losing_healthy_records(self):
        path = self.root / 'projects/repo/chat.jsonl'
        path.parent.mkdir(parents=True)
        records = [{'type': 'user', 'message': ['invalid']},
                   {'type': 'user', 'cwd': '/repo', 'timestamp': '2026-11-10T10:00:00Z',
                    'message': {'content': 'Healthy request'}},
                   {'type': 'assistant', 'cwd': ['invalid'], 'message': {'content': 'bad'}},
                   {'type': 'assistant', 'message': {'id': ['invalid'], 'content': 'bad'}}]
        path.write_text(''.join(json.dumps(record) + '\n' for record in records))
        with self.assertLogs('fzf_sessions', level='WARNING') as logs:
            sessions = adapters.claude_sessions(self.root)
        self.assertEqual(sessions[0].title, 'Healthy request')
        self.assertIn(str(path), '\n'.join(logs.output))
        self.assertEqual(list(conversation.conversation(sessions[0])), [('user', 'Healthy request')])

    def test_codex_unrelated_summary_flag_is_not_rejected(self):
        path = self.root / 'codex.jsonl'
        path.write_text(json.dumps({'type': 'turn_context', 'payload': {'model': 'test', 'summary': False}}) + '\n')
        self.assertEqual(list(common.records(path))[0]['payload']['summary'], False)

    def test_reverse_reader_handles_large_records_and_partial_eof(self):
        path = self.root / 'large.jsonl'
        objects = [{'type': 'user', 'message': {'content': 'first'}},
                   {'type': 'assistant', 'message': {'content': 'x' * 1_000_000}},
                   {'type': 'user', 'message': {'content': 'last'}}]
        path.write_text(''.join(json.dumps(obj) + '\n' for obj in objects) + '{"partial":')
        self.assertEqual(list(common.reverse_records(path)), list(reversed(objects)))

    def test_metadata_touch_reuses_summary_but_changed_input_invalidates(self):
        path = self.root / 'chat.jsonl'
        path.write_text(json.dumps({'type': 'user', 'message': {'content': 'Initial request'}}) + '\n')
        session = models.Session('claude', 'unique', 'Title', '/repo', 0, str(path))
        result = subprocess.CompletedProcess([], 0, 'Goal: Initial.\nProgress: Work.\nNext: Test.', '')
        with patch.dict(os.environ, {'XDG_CACHE_HOME': str(self.root), 'FZF_SESSIONS_NO_AI': '0'}), \
             patch.object(summaries, 'summary_backend', return_value=('/usr/bin/fm', '')), \
             patch.object(summaries.subprocess, 'run', return_value=result) as generate:
            _, context = conversation.preview_context(session)
            self.assertEqual(summaries.ai_summary(session, context)[1], 'generated')
            with path.open('a') as stream:
                stream.write(json.dumps({'type': 'pr-link', 'timestamp': '2026-11-13T10:00:00Z'}) + '\n')
            os.utime(path, None)
            _, same_context = conversation.preview_context(session)
            self.assertEqual(context, same_context)
            self.assertEqual(summaries.ai_summary(session, same_context)[1], 'cached')
            with path.open('a') as stream:
                stream.write(json.dumps({'type': 'assistant', 'message': {'content': 'Actual new progress'}}) + '\n')
            _, new_context = conversation.preview_context(session)
            self.assertEqual(summaries.ai_summary(session, new_context)[1], 'generated')
            self.assertEqual(generate.call_count, 2)
            with patch.object(summaries, 'summary_backend', side_effect=AssertionError('Cached recap must bypass availability checks')):
                self.assertEqual(summaries.ai_summary(session, new_context)[1], 'cached')

    def test_cache_cleanup_limits_count_age_and_only_removes_summary_files(self):
        for i in range(4):
            path = self.root / f'{i}.txt'
            path.write_text('summary')
            os.utime(path, (time.time() - i, time.time() - i))
        other = self.root / 'generation.lock'
        other.write_text('')
        summaries.prune_cache(self.root, max_entries=2)
        self.assertEqual(sorted(p.name for p in self.root.glob('*.txt')), ['0.txt', '1.txt'])
        self.assertTrue(other.exists())
        os.utime(self.root / '0.txt', (0, 0))
        summaries.prune_cache(self.root)
        self.assertFalse((self.root / '0.txt').exists())

    def test_corrupt_summary_cache_falls_back_and_busy_generator_is_not_duplicated(self):
        session = models.Session('claude', 'cache-test', 'Title', '/repo', 0)
        with patch.dict(os.environ, {'XDG_CACHE_HOME': str(self.root), 'FZF_SESSIONS_NO_AI': '0'}), \
             patch.object(summaries, 'summary_backend', return_value=('/usr/bin/fm', '')), \
             patch.object(summaries.subprocess, 'run') as generate:
            cache = summaries.summary_cache(session, 'context')
            cache.parent.mkdir(parents=True)
            cache.write_bytes(b'\xff')
            with (cache.parent / 'generation.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                value, status = summaries.ai_summary(session, 'context')
                self.assertIsNone(value)
                self.assertIn('generating', status)
                generate.assert_not_called()
            generate.return_value = subprocess.CompletedProcess([], 0, 'Goal: Recovered.', '')
            self.assertEqual(summaries.ai_summary(session, 'context'), ('Goal: Recovered.', 'generated'))
            self.assertEqual(cache.read_text(), 'Goal: Recovered.')

    def test_usage_is_cached_for_preview_queries_and_invalidates_when_file_changes(self):
        path = self.root / 'usage.jsonl'
        path.write_text(json.dumps({'type': 'assistant', 'message': {'id': 'm1', 'usage': {
            'input_tokens': 10, 'output_tokens': 20}}}) + '\n')
        session = models.Session('claude', 'id', 'Title', '/repo', 0, str(path))
        with patch.dict(os.environ, {'FZF_SESSIONS_PREVIEW_CACHE': str(self.root / 'usage-cache')}), \
             patch.object(usage, '_uncached_session_usage', wraps=usage._uncached_session_usage) as read:
            self.assertEqual(usage.session_usage(session).output_tokens, 20)
            self.assertEqual(usage.session_usage(session).output_tokens, 20)
            self.assertEqual(read.call_count, 1)
            with path.open('a') as stream:
                stream.write(json.dumps({'type': 'assistant', 'message': {'id': 'm2', 'usage': {
                    'input_tokens': 2, 'output_tokens': 3}}}) + '\n')
            self.assertEqual(usage.session_usage(session).output_tokens, 23)
            self.assertEqual(read.call_count, 2)

    def test_old_or_unidentifiable_fzf_fails_with_actionable_message(self):
        dependencies.require_version.cache_clear()
        for output in ['0.40.0', 'unrecognizable']:
            with self.subTest(output=output), patch.object(dependencies.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], 0, output, '')):
                with self.assertRaisesRegex(RuntimeError, '0.74.5'):
                    dependencies.require_version('/test/fzf', dependencies.MIN_FZF, 'fzf')
        with patch.object(dependencies.subprocess, 'run',
                          return_value=subprocess.CompletedProcess([], 0, '0.74.5 (test)', '')):
            self.assertEqual(dependencies.require_version('/test/fzf', dependencies.MIN_FZF, 'fzf'), '/test/fzf')
        dependencies.require_version.cache_clear()


if __name__ == '__main__':
    unittest.main()
