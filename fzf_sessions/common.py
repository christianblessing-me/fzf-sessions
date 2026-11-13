"""Common for fzf-sessions."""
from __future__ import annotations
from datetime import datetime
import json
import logging
import tempfile
import math
import os
import re
from pathlib import Path
import time
import unicodedata


ENTRYPOINT = Path(__file__).resolve().parent.parent / "fzf-sessions"


def clean(value: object, multiline: bool = False) -> str:
    """Keep transcript text from injecting terminal controls or fzf fields."""
    return "".join(c if (multiline and c == "\n") or not unicodedata.category(c).startswith("C") else " "
                   for c in str(value))


def text_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content
                         if isinstance(b, dict) and b.get("type") in ("text", "input_text", "output_text"))
    return ""


_record_warnings: set[tuple[str, str]] = set()


def record_issue(path: Path, reason: str) -> None:
    key = (str(path), reason)
    if key not in _record_warnings:
        _record_warnings.add(key)
        logging.getLogger("fzf_sessions").warning("Skipped incompatible record in %s: %s", clean(path), reason)


def parse_record(line: bytes, path: Path) -> dict | None:
    try:
        obj = json.loads(line)
    except (ValueError, UnicodeError):
        return None  # A writer can leave a partial JSONL record at EOF.
    if not isinstance(obj, dict):
        record_issue(path, "expected an object")
        return None
    kind = obj.get("type")
    expected = []
    if kind in ("user", "assistant"):
        expected.append(("message", obj.get("message")))
    elif kind in ("session_meta", "turn_context", "response_item", "event_msg"):
        expected.append(("payload", obj.get("payload")))
    for name, value in expected:
        if value is not None and not isinstance(value, dict):
            record_issue(path, f"{name} must be an object")
            return None
    values = [obj]
    values.extend(value for _, value in expected if isinstance(value, dict))
    for value in values:
        for name in ("cwd", "gitBranch", "customTitle", "aiTitle", "thread_name", "model", "requestId"):
            if name in value and value[name] is not None and not isinstance(value[name], str):
                record_issue(path, f"{name} must be text")
                return None
    if kind == "summary" and obj.get("summary") is not None and not isinstance(obj["summary"], str):
        record_issue(path, "summary must be text")
        return None
    for _, value in expected:
        if not isinstance(value, dict):
            continue
        for name in ("id", "session_id", "role"):
            if name in value and value[name] is not None and not isinstance(value[name], str):
                record_issue(path, f"{name} must be text")
                return None
        if value.get("git") is not None and not isinstance(value["git"], dict):
            record_issue(path, "git must be an object")
            return None
    if kind is None:  # Codex's lightweight session-name index has no type field.
        for name in ("id", "thread_name"):
            if obj.get(name) is not None and not isinstance(obj[name], str):
                record_issue(path, f"{name} must be text")
                return None
    return obj


def records(path: Path, budget: int | None = None, tail: bool = False):
    """Yield validated JSONL records, tolerating concurrent writes and schema drift."""
    try:
        with path.open("rb") as stream:
            if tail and budget and path.stat().st_size > budget:
                stream.seek(-budget, os.SEEK_END)
                stream.readline()
            consumed = 0
            while True:
                line = stream.readline() if budget is None else stream.readline(budget - consumed + 1)
                if not line:
                    break
                consumed += len(line)
                if budget is not None and consumed > budget:
                    break
                obj = parse_record(line, path)
                if obj is not None:
                    yield obj
    except OSError:
        return


def reverse_records(path: Path):
    """Read backwards in chunks; accumulate long records without quadratic copying."""
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            position = stream.tell()
            pending = []
            while position:
                size = min(position, 65536)
                position -= size
                stream.seek(position)
                parts = stream.read(size).split(b"\n")
                if len(parts) == 1:
                    pending.append(parts[0])
                    continue
                last = parts.pop() + b"".join(reversed(pending))
                for line in [last, *reversed(parts[1:])]:
                    if line:
                        obj = parse_record(line, path)
                        if obj is not None:
                            yield obj
                pending = [parts[0]]
            if pending:
                obj = parse_record(b"".join(reversed(pending)), path)
                if obj is not None:
                    yield obj
    except OSError:
        return


def file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return -1


def activity_timestamp(obj: dict, tool: str) -> float:
    kind = obj.get("type")
    active = False
    if tool == "claude":
        message = obj.get("message") or {}
        active = (kind in ("user", "assistant") and not obj.get("isMeta")
                  and not obj.get("isSidechain") and isinstance(message, dict)
                  and message.get("model") != "<synthetic>")
    else:
        payload = obj.get("payload") or {}
        if isinstance(payload, dict):
            if kind == "response_item":
                active = ((payload.get("type") == "message" and payload.get("role") in ("user", "assistant"))
                          or payload.get("type") in ("function_call", "function_call_output",
                              "custom_tool_call", "custom_tool_call_output", "reasoning"))
            elif kind == "event_msg":
                active = payload.get("type") in ("task_started", "task_complete", "user_message", "agent_message")
    value = timestamp(obj.get("timestamp")) if active else 0
    return value if math.isfinite(value) and value > 0 else 0


def last_activity(path: Path, tool: str, fallback: float = 0) -> float:
    for obj in reverse_records(path):
        value = activity_timestamp(obj, tool)
        if value:
            return value
    return fallback


def timestamp(value: object, fallback: float = 0) -> float:
    try:
        if isinstance(value, (float, int)):
            return float(value) / 1000 if value > 100_000_000_000 else float(value)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError):
        return fallback


def readable(body: str) -> str:
    # Saved CLI prompts may include injected workspace context alongside the request.
    for tag in ("environment_context", "user_instructions", "permissions_instructions"):
        body = re.sub(rf"<{tag}>.*?</{tag}>", "", body, flags=re.DOTALL)
    if body.lstrip().startswith("# AGENTS.md instructions"):
        return ""
    return clean(body, multiline=True).strip()


def age(updated: float) -> str:
    if not math.isfinite(updated) or updated <= 0 or updated > time.time() + 60:
        return "unknown"
    seconds = max(0, time.time() - updated)
    if seconds < 60:
        return "now"
    for divisor, unit, limit in [(60, "m", 3600), (3600, "h", 86400), (86400, "d", float("inf"))]:
        if seconds < limit:
            return f"{int(seconds / divisor)}{unit} ago"
    return "unknown"


def atomic_write(path: Path, contents: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(contents)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_view(path: Path) -> dict:
    """Load one atomically published Herdr snapshot, or an older TSV row file."""
    text = path.read_text()
    if text.startswith('{'):
        value = json.loads(text)
        if not isinstance(value, dict) or not isinstance(value.get('rows'), list):
            raise ValueError('Invalid picker refresh snapshot')
        return value
    return {'rows': text.splitlines()}
