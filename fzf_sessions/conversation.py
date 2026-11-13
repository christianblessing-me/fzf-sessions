"""Conversation for fzf-sessions."""
from __future__ import annotations
from collections import deque
from pathlib import Path
from . import common as common_mod
from . import models as models_mod


def conversation(session: models_mod.Session, budget: int | None = None):
    """Only conversational text; omit tool calls, results, and internal events."""
    if not session.transcript:
        return
    for obj in common_mod.records(Path(session.transcript), budget, tail=budget is not None):
        kind = obj.get("type")
        role = body = ""
        if session.tool == "claude" and kind in ("user", "assistant") and not obj.get("isMeta"):
            role = kind
            body = common_mod.text_content((obj.get("message") or {}).get("content"))
        elif session.tool == "codex" and kind == "response_item":
            payload = obj.get("payload") or {}
            if payload.get("type") == "message" and payload.get("role") in ("user", "assistant"):
                role = payload["role"]
                body = common_mod.text_content(payload.get("content"))
        if body.strip():
            yield role, body


def preview_context(session: models_mod.Session) -> tuple[str, str]:
    first = ""
    # Read the head for the original goal, and the tail for current status.
    if session.transcript:
        for obj in common_mod.records(Path(session.transcript), 65536):
            if session.tool == "codex" and obj.get("type") == "response_item":
                msg = obj.get("payload") or {}
            elif session.tool == "claude" and obj.get("type") == "user" and not obj.get("isMeta"):
                msg = obj.get("message") or {}
                msg = dict(msg, role="user")
            else:
                continue
            if msg.get("role") == "user":
                body = common_mod.readable(common_mod.text_content(msg.get("content")))
                if body:
                    first = body
                    break
    recent = deque(((role, common_mod.readable(body)) for role, body in conversation(session, 524288)
                    if common_mod.readable(body)), maxlen=8)
    latest_user = next((body for role, body in reversed(recent) if role == "user"), "")
    latest_answer = next((body for role, body in reversed(recent) if role == "assistant"), "")
    fallback = [f"Started with\n{first[:1200] or session.title}",
                f"Last request\n{latest_user[:1600] or 'Not available in recent transcript text.'}",
                f"Last response\n{latest_answer[:3000] or 'No recent assistant response available.'}"]
    excerpts = [f"Session title: {session.title[:300]}", f"Initial request (excerpt): {first[:900]}"]
    remaining = 6500 - len("\n\n".join(excerpts))
    selected = []
    # Give recent assistant answers enough room for implementation and test details.
    # Keep both ends: validation results often appear at the end of an answer.
    for role, body in reversed(recent):
        limit = min(1500 if role == "assistant" else 700, remaining - 40)
        if limit < 200:
            break
        excerpt = body if len(body) <= limit else body[:limit * 2 // 3] + "\n[…]\n" + body[-(limit // 3 - 6):]
        part = f"{role.upper()} (excerpt): {excerpt}"
        selected.append(part)
        remaining -= len(part) + 2
    excerpts.extend(reversed(selected))
    return "\n\n".join(fallback), "\n\n".join(excerpts)[:6500]
