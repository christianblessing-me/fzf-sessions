"""Find and resume local Codex and Claude Code sessions."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time


def _run_main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--shortcut-modal":
        from . import help_ui as help_ui_mod
        help_ui_mod.show_shortcut_modal(sys.argv[2] == "herdr")
        return 0
    if len(sys.argv) == 5 and sys.argv[1] == "--watch-herdr":
        import shlex
        from . import common as common_mod
        ready = Path(sys.argv[2])
        deadline = time.monotonic() + 4
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.025)
        if ready.exists():
            command = shlex.join([sys.executable, str(common_mod.ENTRYPOINT), "--search", sys.argv[3], sys.argv[4]])
            print("reload(" + command + " {q})+refresh-preview")
        return 0
    if len(sys.argv) in (6, 7) and sys.argv[1] == "--await-herdr-rows":
        from . import search as search_mod, common as common_mod
        ready, initial = Path(sys.argv[2]), Path(sys.argv[3])
        deadline = time.monotonic() + 4
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.025)
        rows = common_mod.read_view(ready if ready.exists() else initial)["rows"]
        if len(sys.argv) == 7:
            rows = search_mod.SearchIndex(Path(sys.argv[4])).rows(sys.argv[5], sys.argv[6], rows)
        elif sys.argv[4] != "-":
            data = json.loads(Path(sys.argv[4]).read_text())
            rows = search_mod.content_rows(data["index"], rows, sys.argv[5])
        print("\n".join(rows))
        return 0
    if len(sys.argv) == 5 and sys.argv[1] == "--search":
        from . import search as search_mod
        print("\n".join(search_mod.SearchIndex(Path(sys.argv[2])).rows(sys.argv[3], sys.argv[4])))
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == "--content-search":
        from . import search as search_mod
        data = json.loads(Path(sys.argv[2]).read_text())
        print("\n".join(search_mod.search_rows(data, sys.argv[3])))
        return 0
    if len(sys.argv) in (4, 6) and sys.argv[1] == "--preview":
        from . import models as models_mod, previews as previews_mod
        try:
            data = json.loads(Path(sys.argv[2]).read_text())
            state = os.environ.get("FZF_SESSIONS_HERDR_STATE")
            if state and Path(state).is_file():
                from . import common as common_mod
                data = common_mod.read_view(Path(state)).get("sessions", data)
            query = sys.argv[5] if len(sys.argv) == 6 and sys.argv[4] == "content" else ""
            position = int(sys.argv[3])
            messages = None
            if query and os.environ.get("FZF_SESSIONS_SEARCH_DB"):
                from . import search as search_mod
                messages = search_mod.SearchIndex(Path(os.environ["FZF_SESSIONS_SEARCH_DB"])).messages(position)
            previews_mod.show_preview(models_mod.Session(**data[position]), query, messages)
            return 0
        except (OSError, ValueError, IndexError, TypeError) as exc:
            print(f"Preview unavailable: {exc}")
            return 0
    from . import adapters as adapters_mod, herdr as herdr_mod, launch as launch_mod, ui as ui_mod
    parser = argparse.ArgumentParser(description=__doc__)
    from . import __version__
    parser.add_argument("--version", action="version", version=f"fzf-sessions {__version__}")
    parser.add_argument("--doctor", action="store_true", help="check dependencies and local configuration without reading conversations")
    parser.add_argument("query", nargs="*", help="initial fzf search")
    parser.add_argument("--tool", choices=("codex", "claude"))
    parser.add_argument("--here", action="store_true", help="only sessions from this exact working directory")
    parser.add_argument("--list", action="store_true", help="list sessions as JSON without opening fzf")
    parser.add_argument("--herdr", action="store_true", help="focus an open Herdr session, or resume in a new workspace")
    parser.add_argument("--herdr-open", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true", help="pick a session and print its resume command")
    args = parser.parse_args()
    if args.doctor:
        from .doctor import doctor
        return doctor()
    if args.herdr_open:
        herdr_mod.open_herdr_picker()
        return 0
    if args.herdr and not args.list:
        herdr_mod.herdr_context()  # Fail before opening fzf when caller context is missing.
    sessions = adapters_mod.discover(args.tool, args.here)
    herdr_note = "● open · — not detected · ? checking/unavailable" if os.environ.get("HERDR_ENV") == "1" else ""
    if args.list:
        herdr_mod.annotate_herdr_sessions(sessions)
        print(json.dumps([asdict(s) for s in sessions], indent=2))
        return 0
    if not sessions:
        print("No sessions found.", file=sys.stderr)
        return 0
    selected = ui_mod.picker(sessions, " ".join(args.query), dry_run=args.dry_run, herdr_note=herdr_note)
    if selected:
        if args.herdr:
            herdr_mod.resume_herdr(selected, args.dry_run)
        else:
            launch_mod.resume(selected, args.dry_run)
    return 0


def main() -> int:
    import logging
    import sqlite3
    logging.basicConfig(format='fzf-sessions: %(message)s', level=logging.WARNING)
    try:
        return _run_main()
    except (RuntimeError, OSError, ValueError, sqlite3.Error) as exc:
        print(f"fzf-sessions: {exc}", file=sys.stderr, flush=True)
        if (os.environ.get("HERDR_PLUGIN_ID") == "fzf-sessions"
                and os.environ.get("HERDR_PLUGIN_ENTRYPOINT_ID") == "picker"
                and sys.stdin.isatty()):
            print("\nPress Enter to close this popup.", file=sys.stderr, flush=True)
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass
        return 1
    except KeyboardInterrupt:
        return 130
