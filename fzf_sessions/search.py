"""Search for fzf-sessions."""
from __future__ import annotations
from collections import deque
from pathlib import Path
from . import common as common_mod
from . import conversation as conversation_mod
from . import models as models_mod


def literal_spans(text: str, terms: list[str], max_per_term: int = 32) -> list[tuple[int, int]]:
    """Map casefolded matches back to the original text, including ß -> ss."""
    folded = text.casefold()
    offsets = None
    spans = []
    for term in terms:
        start = folded.find(term)
        if start < 0:
            continue
        if offsets is None:
            offsets = [i for i, char in enumerate(text) for _ in char.casefold()]
        count = 0
        while start >= 0 and count < max_per_term:
            spans.append((offsets[start], offsets[start + len(term) - 1] + 1))
            count += 1
            start = folded.find(term, start + len(term))
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def matching_excerpts(session: models_mod.Session, query: str, messages=None) -> list[tuple[str, str]]:
    terms = list(dict.fromkeys(query.casefold().split()))
    if not terms:
        return []
    latest = {}
    recent = deque(maxlen=3)
    for role, body in (conversation_mod.conversation(session) if messages is None else messages):
        text = " ".join(common_mod.readable(body).split())
        windows = []
        for start, end in literal_spans(text, terms, max_per_term=1):
            start, end = max(0, start - 100), min(len(text), end + 180)
            if windows and start <= windows[-1][1]:
                windows[-1] = (windows[-1][0], max(end, windows[-1][1]))
            else:
                windows.append((start, end))
        for start, end in windows:
            excerpt = ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")
            item = (role, excerpt)
            recent.append(item)
            for term in terms:
                if term in excerpt.casefold():
                    latest[term] = item
    # Include evidence for terms spread across different messages, then fill with
    # recent hits. Keep the preview bounded even for very common search words.
    selected = []
    for item in [*(latest[term] for term in terms if term in latest), *reversed(recent)]:
        if item not in selected:
            selected.append(item)
        if len(selected) == 6:
            break
    return selected


def content_index(sessions: list[models_mod.Session]) -> list[str]:
    return [" ".join(common_mod.readable(body) for _, body in conversation_mod.conversation(session)).casefold()
            for session in sessions]


def content_rows(index: list[str], rows: list[str], query: str) -> list[str]:
    # Literal AND search avoids fuzzy matching across entire conversations.
    terms = query.casefold().split()
    matching = {i for i, text in enumerate(index) if all(term in text for term in terms)}
    # Rows may be reordered when live Herdr status arrives. Their hidden IDs
    # still refer to the original session/content index, not the display order.
    return [rows[0], *(row for row in rows[1:] if int(row.split("\t", 1)[0]) in matching)]


def search_rows(data: dict, query: str) -> list[str]:
    path = Path(data.get("herdr_rows", ""))
    rows = common_mod.read_view(path)["rows"] if path.is_file() else data["rows"]
    return content_rows(data["index"], rows, query)


class SearchIndex:
    """Per-picker SQLite index: full search text is independent of display rows."""

    def __init__(self, path: Path):
        self.path = path

    @classmethod
    def create(cls, path: Path, sessions: list[models_mod.Session], initial_rows: Path,
               live_rows: Path, preserve_order: bool) -> SearchIndex:
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.executescript('''
                CREATE TABLE sessions (id INTEGER PRIMARY KEY, title TEXT, folder TEXT, body TEXT);
                CREATE TABLE messages (session_id INTEGER, position INTEGER, role TEXT, body TEXT);
                CREATE INDEX messages_by_session ON messages(session_id);
                CREATE TABLE settings (name TEXT PRIMARY KEY, value TEXT);
            ''')
            connection.executemany('INSERT INTO sessions(id,title,folder) VALUES (?,?,?)',
                ((i, ' '.join(common_mod.clean(s.title).split()), common_mod.clean(Path(s.cwd).name or s.cwd))
                 for i, s in enumerate(sessions)))
            connection.executemany('INSERT INTO settings VALUES (?,?)',
                [('initial_rows', str(initial_rows)), ('live_rows', str(live_rows)),
                 ('preserve_order', str(int(preserve_order))), ('content_ready', '0')])
        return cls(path)

    def enable_content(self, sessions: list[models_mod.Session]) -> None:
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.path)) as connection, connection:
            if connection.execute("SELECT value FROM settings WHERE name='content_ready'").fetchone()[0] == '1':
                return
            for i, session in enumerate(sessions):
                parts = []
                for position, (role, body) in enumerate(conversation_mod.conversation(session)):
                    body = common_mod.readable(body)
                    if body:
                        parts.append(body.casefold())
                        connection.execute('INSERT INTO messages VALUES (?,?,?,?)', (i, position, role, body))
                connection.execute('UPDATE sessions SET body=? WHERE id=?', (' '.join(parts), i))
            connection.execute("UPDATE settings SET value='1' WHERE name='content_ready'")

    def rows(self, mode: str, query: str, rows: list[str] | None = None) -> list[str]:
        import sqlite3
        import os
        import subprocess
        from contextlib import closing
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as connection:
            settings = dict(connection.execute('SELECT name,value FROM settings'))
            if rows is None:
                live = Path(settings['live_rows'])
                rows = common_mod.read_view(live if live.is_file() else Path(settings['initial_rows']))["rows"]
            if not query.strip():
                return rows
            if mode == 'content':
                terms = list(dict.fromkeys(query.casefold().split()))
                where = ' AND '.join('instr(body, ?) > 0' for _ in terms)
                matching = [str(row[0]) for row in connection.execute('SELECT id FROM sessions WHERE ' + where, terms)]
            else:
                # Use fzf's own matcher, including its extended query syntax, on the
                # complete fields. Only the small metadata input crosses this pipe.
                metadata = connection.execute('SELECT id,title,folder FROM sessions ORDER BY id').fetchall()
                data = '\n'.join('\t'.join(map(str, row)) for row in metadata)
                env = os.environ.copy()
                env.pop('FZF_DEFAULT_OPTS', None)
                env.pop('FZF_DEFAULT_OPTS_FILE', None)
                result = subprocess.run(['fzf', '--delimiter=\t', '--nth=2,3', '--filter=' + query],
                    input=data, text=True, capture_output=True, env=env, timeout=5)
                if result.returncode not in (0, 1):
                    raise RuntimeError('Metadata search failed: ' + common_mod.clean(result.stderr)[:200])
                matching = [line.split('\t', 1)[0] for line in result.stdout.splitlines()]
        by_id = {row.split('\t', 1)[0]: row for row in rows[1:]}
        if mode == 'metadata' and settings['preserve_order'] == '0':
            return [rows[0], *(by_id[key] for key in matching if key in by_id)]
        selected = set(matching)
        return [rows[0], *(row for row in rows[1:] if row.split('\t', 1)[0] in selected)]

    def messages(self, session_id: int):
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
            yield from connection.execute('SELECT role,body FROM messages WHERE session_id=? ORDER BY position', (session_id,))
