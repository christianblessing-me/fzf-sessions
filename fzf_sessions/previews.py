"""Previews for fzf-sessions."""
from __future__ import annotations
from datetime import datetime
import os
import re
import textwrap
from . import common as common_mod
from . import conversation as conversation_mod
from . import models as models_mod
from . import search as search_mod
from . import summaries as summaries_mod
from . import usage as usage_mod


def preview(session: models_mod.Session) -> str:
    # The raw fallback remains useful without Apple Intelligence (and in tests).
    fallback, _ = conversation_mod.preview_context(session)
    return common_mod.clean(f"{session.cwd} · {session.branch or 'unknown branch'}\n\n{fallback}", multiline=True)


def styled_preview(session: models_mod.Session, body: str, caption: str, usage: models_mod.Usage | None = None,
                   excerpts: list[tuple[str, str]] | None = None, query: str = "") -> str:
    try:
        width = max(20, min(100, int(os.environ.get("FZF_PREVIEW_COLUMNS", "64")) - 4))
    except ValueError:
        width = 60
    color = "NO_COLOR" not in os.environ

    def paint(text: str, code: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if color else text

    def wrapped(text: str, indent: str = "  ", subsequent: str | None = None) -> list[str]:
        return textwrap.wrap(text, width=width, initial_indent=indent,
                             subsequent_indent=subsequent or indent, break_long_words=True,
                             break_on_hyphens=False) or [""]

    title = " ".join(common_mod.clean(session.title).split())
    lines = [paint(line, "1") for line in wrapped(title, "")]
    meta = common_mod.clean(f"{session.tool.upper()}  ·  {session.branch or 'unknown branch'}  ·  {common_mod.age(session.updated)}")
    lines += [paint(meta, "36"), *[paint(line, "2") for line in wrapped(common_mod.clean(session.cwd), "")],
              paint("─" * width, "2")]
    if query.strip():
        lines.append(paint("MATCHING PASSAGES", "1;33"))
        terms = list(dict.fromkeys(query.casefold().split()))
        for role, excerpt in excerpts or []:
            lines.append(paint(f"  {role.upper()}", "2"))
            for line in wrapped(common_mod.clean(excerpt)):
                highlighted, end = [], 0
                for start, stop in search_mod.literal_spans(line, terms):
                    highlighted.extend([line[end:start], paint(line[start:stop], "1;33")])
                    end = stop
                lines.append("".join(highlighted) + line[end:])
            lines.append("")
        if not excerpts:
            lines.append("  No matching text remains in the saved conversation.")
        lines.extend([paint("─" * width, "2"), ""])
    if session.herdr_locations:
        lines.append(paint("OPEN IN HERDR", "1;32"))
        for location in session.herdr_locations:
            value = common_mod.clean(f"{location['workspace']} / {location['tab']}")
            lines.extend(wrapped(value, "  • ", "    "))
            details = common_mod.clean(f"{location['status']} · {location['pane_id']}")
            lines.extend(paint(line, "2") for line in wrapped(details, "    "))
        lines.extend(["", paint("─" * width, "2")])
    if usage is not None:
        recorded = common_mod.timestamp(usage.recorded_at)
        when = datetime.fromtimestamp(recorded).astimezone().strftime("%d %b %H:%M") if recorded else ""
        lines.append(paint("LAST RECORDED USAGE" + (f" · {when}" if when else ""), "1;36"))
        for label, value in usage_mod.usage_lines(usage, session.tool):
            # Reserve space for labels when wrapping the usage values.
            parts = textwrap.wrap(common_mod.clean(value), width=max(10, width - 10)) or [""]
            lines.append(paint(f"  {label:<8}", "2") + parts[0])
            lines.extend(" " * 10 + part for part in parts[1:])
        lines.extend(["", paint("─" * width, "2")])
    lines.append(paint(common_mod.clean(caption), "2"))
    labels = {"goal": ("GOAL", "1;36"), "progress": ("PROGRESS", "1;32"),
              "next": ("NEXT", "1;33"), "started with": ("STARTED WITH", "1;36"),
              "last request": ("LAST REQUEST", "1;33"), "last response": ("LAST RESPONSE", "1;32")}
    for raw in common_mod.clean(body, multiline=True).splitlines():
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", raw.strip())
        line = re.sub(r"^#{1,6}\s+", "", line)
        match = re.match(r"^(Goal|Progress|Next|Started with|Last request|Last response)(?::\s*(.*))?$",
                         line, re.IGNORECASE)
        if match:
            label, code = labels[match[1].lower()]
            lines.extend(["", paint(label, code)])
            if match[2]:
                lines.extend(wrapped(match[2]))
        elif line:
            bullet = re.match(r"^(?:[-*•]|\d+[.)])\s+(.*)", line)
            lines.extend(wrapped(bullet[1], "  • ", "    ") if bullet else wrapped(line))
        elif lines and lines[-1] != "":
            lines.append("")
    return "\n".join(lines).rstrip()


def show_preview(session: models_mod.Session, query: str = "", messages=None) -> None:
    fallback, context = conversation_mod.preview_context(session)
    usage = usage_mod.session_usage(session)
    if query.strip():
        excerpts = search_mod.matching_excerpts(session, query, messages)
        # Query changes rerun previews frequently. Reuse a recap when available;
        # do not start a new model generation on every keystroke.
        summary = None
        if os.environ.get("FZF_SESSIONS_NO_AI") != "1":
            cache = summaries_mod.summary_cache(session, context)
            summary = summaries_mod.read_cached_summary(cache)
        caption = "Apple Intelligence · cached recap" if summary else "Saved conversation"
        print(styled_preview(session, summary or fallback, caption, usage, excerpts, query), flush=True)
        return
    print(styled_preview(session, fallback, "Saved conversation", usage), flush=True)

    def generating() -> None:
        print("\x1b[2J\x1b[H", end="")
        print(styled_preview(session, fallback, "Generating on-device summary…", usage), flush=True)

    summary, status = summaries_mod.ai_summary(session, context, on_generate=generating)
    # fzf supports clearing a streaming preview, replacing the fallback in place.
    print("\x1b[2J\x1b[H", end="")
    caption = f"Apple Intelligence · on-device · {status}" if summary else status
    print(styled_preview(session, summary or fallback, caption, usage), flush=True)
