"""Usage for fzf-sessions."""
from __future__ import annotations
from dataclasses import field
from pathlib import Path
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from . import common as common_mod
from . import models as models_mod


def token_number(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _uncached_session_usage(session: models_mod.Session) -> models_mod.Usage:
    """Recorded token accounting only. Never inspect or display monetary fields."""
    usage = models_mod.Usage()
    if not session.transcript:
        return usage
    messages = {}
    for obj in common_mod.records(Path(session.transcript)):
        if session.tool == "codex":
            payload = obj.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if obj.get("type") in ("turn_context", "session_meta") and payload.get("model"):
                usage.model = str(payload["model"])
            if obj.get("type") != "event_msg" or payload.get("type") != "token_count":
                continue
            info = payload.get("info")
            if not isinstance(info, dict):
                continue
            # These are cumulative snapshots; repeated events must never be summed.
            total = info.get("total_token_usage") or {}
            latest = info.get("last_token_usage") or {}
            if not isinstance(total, dict) or not isinstance(latest, dict):
                continue
            usage.input_tokens = token_number(total.get("input_tokens"))
            usage.output_tokens = token_number(total.get("output_tokens"))
            usage.cached_tokens = token_number(total.get("cached_input_tokens"))
            usage.context_tokens = token_number(latest.get("total_tokens"))
            usage.context_limit = token_number(info.get("model_context_window"))
            usage.recorded_at = str(obj.get("timestamp") or "")
        else:
            if obj.get("type") != "assistant" or obj.get("isSidechain"):
                continue
            message = obj.get("message") or {}
            if not isinstance(message, dict):
                continue
            if message.get("model") and message["model"] != "<synthetic>":
                usage.model = str(message["model"])
            counters = message.get("usage")
            if not isinstance(counters, dict) or token_number(counters.get("input_tokens")) is None:
                continue
            # One API response can be stored as several content-block records.
            # Merge cumulative partial counters by maximum, then sum unique responses.
            key = message.get("id") or obj.get("requestId")
            if not key:
                continue  # Without identity we cannot safely account for duplicates.
            previous = messages.setdefault(key, {})
            for field in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                number = token_number(counters.get(field))
                if number is not None:
                    previous[field] = max(previous.get(field, 0), number)
            # Claude reports uncached, cache-read and cache-write inputs separately.
            usage.context_tokens = sum(previous.get(field, 0) for field in
                                       ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            usage.recorded_at = str(obj.get("timestamp") or "")
    if session.tool == "claude" and messages:
        usage.input_tokens = sum(sum(m.get(field, 0) for field in
                                     ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
                                 for m in messages.values())
        cached = [m["cache_read_input_tokens"] for m in messages.values() if "cache_read_input_tokens" in m]
        usage.cached_tokens = sum(cached) if cached else None
        outputs = [m["output_tokens"] for m in messages.values() if "output_tokens" in m]
        usage.output_tokens = sum(outputs) if outputs else None
    return usage


def session_usage(session: models_mod.Session) -> models_mod.Usage:
    root = os.environ.get("FZF_SESSIONS_PREVIEW_CACHE")
    cache = None
    stamp = None
    if root and session.transcript:
        try:
            stat = Path(session.transcript).stat()
            stamp = [stat.st_mtime_ns, stat.st_size]
            key = hashlib.sha256((session.tool + "\0" + session.transcript).encode()).hexdigest()
            cache = Path(root) / (key + ".json")
            if cache.is_file():
                data = json.loads(cache.read_text())
                if data.get("stamp") == stamp:
                    values = data.get("usage", {})
                    if (isinstance(values, dict) and isinstance(values.get("model"), str)
                            and isinstance(values.get("recorded_at"), str)
                            and all(value is None or token_number(value) is not None
                                    for name, value in values.items() if name not in ("model", "recorded_at"))):
                        return models_mod.Usage(**values)
        except (OSError, ValueError, TypeError):
            pass
    usage = _uncached_session_usage(session)
    if cache is not None:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            common_mod.atomic_write(cache, json.dumps({"stamp": stamp, "usage": asdict(usage)}))
        except OSError:
            pass
    return usage


def compact_tokens(number: int | None) -> str:
    if number is None:
        return "unknown"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"
    if number >= 1000:
        return f"{number / 1000:.1f}k"
    return str(number)


def usage_lines(usage: models_mod.Usage, tool: str) -> list[tuple[str, str]]:
    rows = [("MODEL", usage.model or "not recorded")]
    if usage.context_tokens is not None:
        context = compact_tokens(usage.context_tokens)
        if usage.context_limit:
            percent = usage.context_tokens / usage.context_limit * 100
            context += f" / {compact_tokens(usage.context_limit)} · {percent:.0f}% used"
        elif tool == "claude":
            context += " input · window limit not recorded"
        else:
            context += " · window limit not recorded"
        rows.append(("CONTEXT", context))
    if usage.input_tokens is not None or usage.output_tokens is not None:
        rows.append(("TOKENS", f"{compact_tokens(usage.input_tokens)} in · {compact_tokens(usage.output_tokens)} out"))
    if usage.cached_tokens is not None:
        cache = compact_tokens(usage.cached_tokens)
        if usage.input_tokens and usage.cached_tokens <= usage.input_tokens:
            cache += f" · {usage.cached_tokens / usage.input_tokens:.0%} of input reused"
        rows.append(("CACHE", cache))
    if len(rows) == 1:
        rows.append(("USAGE", "not recorded"))
    return rows
