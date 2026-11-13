"""Adapters for fzf-sessions."""
from __future__ import annotations
from contextlib import closing
import os
from pathlib import Path
import sqlite3
from . import common as common_mod
from . import models as models_mod


def codex_sessions(root: Path) -> list[models_mod.Session]:
    result = {}
    indexed = set()
    # The database is an internal format: inspect columns and fall back to rollouts.
    for db in sorted(root.glob("state_*.sqlite"), key=common_mod.file_mtime, reverse=True):
        try:
            with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.1)) as conn:
                conn.row_factory = sqlite3.Row
                for row in conn.execute("SELECT * FROM threads"):
                    r = dict(row)
                    sid = r.get("id")
                    if not isinstance(sid, str) or not sid:
                        continue
                    indexed.add(sid)
                    source = str(r.get("source", ""))
                    if r.get("archived") or source == "exec" or "subagent" in source:
                        continue
                    cwd = r.get("cwd")
                    if not isinstance(cwd, str) or not cwd:
                        continue
                    title = next((value for value in (r.get("name"), r.get("title"), r.get("first_user_message"))
                                  if isinstance(value, str) and value), "Untitled session")
                    rollout = r.get("rollout_path") if isinstance(r.get("rollout_path"), str) else ""
                    branch = r.get("git_branch") if isinstance(r.get("git_branch"), str) else ""
                    result[sid] = models_mod.Session("codex", sid, title,
                        cwd, common_mod.last_activity(Path(rollout), "codex",
                            common_mod.timestamp(r.get("recency_at_ms") or r.get("recency_at") or
                                      r.get("created_at_ms") or r.get("created_at"))),
                        rollout, branch)
            break
        except (sqlite3.Error, OSError):
            continue
    names = {}
    for obj in common_mod.records(root / "session_index.jsonl"):
        if obj.get("id") and obj.get("thread_name"):
            names[obj["id"]] = obj["thread_name"]
    for path in (root / "sessions").glob("**/*.jsonl"):
        # Rollout filenames end in the UUID. Skip indexed sessions without opening them.
        if path.stem[-36:] in indexed:
            continue
        meta = None
        title = ""
        for obj in common_mod.records(path, 65536):
            payload = obj.get("payload", {})
            if not isinstance(payload, dict):
                continue
            if obj.get("type") == "session_meta":
                meta = payload
            if obj.get("type") == "event_msg" and payload.get("type") == "user_message":
                title = payload.get("message", "")
                break
        if not meta:
            continue
        source = str(meta.get("source", ""))
        sid = meta.get("id") or meta.get("session_id")
        if not sid or sid in indexed or not meta.get("cwd") or source == "exec" or "subagent" in source:
            continue
        updated = common_mod.last_activity(path, "codex", common_mod.timestamp(meta.get("timestamp")))
        git = meta.get("git") or {}
        result[sid] = models_mod.Session("codex", sid, names.get(sid) or title or "Untitled session",
                              meta["cwd"], updated, str(path), git.get("branch", ""))
    for sid, name in names.items():
        if sid in result:
            result[sid].title = name
    return list(result.values())


def claude_sessions(root: Path) -> list[models_mod.Session]:
    result = []
    for path in (root / "projects").glob("*/*.jsonl"):
        cwd = branch = first = title = custom = ""
        sidechain = False
        # Bounded reads avoid scanning megabytes of tool output for every session.
        for obj in (*common_mod.records(path, 65536), *common_mod.records(path, 131072, tail=True)):
            cwd = obj.get("cwd") or cwd
            branch = obj.get("gitBranch") or branch
            sidechain = sidechain or bool(obj.get("isSidechain"))
            kind = obj.get("type")
            if kind == "custom-title":
                custom = obj.get("customTitle") or custom
            elif kind == "ai-title":
                title = obj.get("aiTitle") or title
            elif kind == "summary" and not title:
                title = obj.get("summary") or title
            elif kind == "user" and not first and not obj.get("isMeta"):
                first = common_mod.text_content((obj.get("message") or {}).get("content"))
        if not cwd or sidechain:
            continue
        updated = common_mod.last_activity(path, "claude")
        result.append(models_mod.Session("claude", path.stem, custom or title or first or "Untitled session",
                              cwd, updated, str(path), branch))
    return result


def discover(tool: str | None, here: bool) -> list[models_mod.Session]:
    sessions = []
    if tool != "claude":
        sessions.extend(codex_sessions(Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()))
    if tool != "codex":
        sessions.extend(claude_sessions(Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")).expanduser()))
    if here:
        cwd = Path.cwd().resolve()
        sessions = [s for s in sessions if Path(s.cwd).resolve() == cwd]
    return sorted(sessions, key=lambda s: s.updated, reverse=True)
