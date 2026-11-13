"""Ui for fzf-sessions."""
from __future__ import annotations
from dataclasses import asdict
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from . import common as common_mod
from . import dependencies as dependencies_mod
from . import herdr as herdr_mod
from . import launch as launch_mod
from . import models as models_mod
from . import search as search_mod


def picker(sessions: list[models_mod.Session], query: str, dry_run: bool = False, herdr_note: str = "") -> models_mod.Session | None:
    dependencies_mod.require_fzf()
    with tempfile.TemporaryDirectory(prefix="fzf-sessions-") as tmp:
        manifest = Path(tmp) / "sessions.json"
        manifest.write_text(json.dumps([asdict(s) for s in sessions]))
        command = shlex.join([sys.executable, str(common_mod.ENTRYPOINT), "--preview", str(manifest)]) + " {1}"
        use_color = "NO_COLOR" not in os.environ

        def paint(value: str, code: str) -> str:
            return f"\x1b[{code}m{value}\x1b[0m" if use_color else value

        show_herdr = bool(herdr_note)
        def build_rows(view: list[models_mod.Session] | None = None) -> list[str]:
            view = sessions if view is None else view
            columns = [[*(["OPEN"] if show_herdr else []),
                        "UPDATED", "AGENT", "SESSION", "DIRECTORY", "BRANCH", "ID"]]
            for i, s in enumerate(view):
                directory = Path(s.cwd).name or s.cwd
                title = " ".join(common_mod.clean(s.title).split())
                if len(title) > 50:
                    title = title[:49] + "…"
                columns.append([*([herdr_mod.herdr_location_label(s)] if show_herdr else []),
                                common_mod.age(s.updated), s.tool, title, directory, s.branch, s.id])
            columns = [[common_mod.clean(value) for value in fields] for fields in columns]

            def display_width(value: str) -> int:
                return sum(0 if unicodedata.combining(c) else
                           2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
                           for c in value)

            widths = [max(display_width(fields[i]) for fields in columns) for i in range(len(columns[0]))]
            rows = []
            for i, fields in enumerate(columns):
                padded = [value + " " * (width - display_width(value))
                          for value, width in zip(fields, widths)]
                if i == 0:
                    padded = [paint(value, "1;36") for value in padded]
                else:
                    session = view[i - 1]
                    recent = 0 < session.updated <= time.time() + 60 and time.time() - session.updated < 86400
                    colors = [*(["32" if session.herdr_locations else "2"] if show_herdr else []),
                              "32" if recent else "2", "36" if session.tool == "codex" else "33",
                              "1", "2", "2", "2"]
                    padded = [paint(value, code) for value, code in zip(padded, colors)]
                # fzf renders the first row as a sticky header, with the same field
                # transformation and gutter as selectable rows. The key stays hidden.
                rows.append("\t".join([str(i - 1), *padded]))
            if show_herdr:
                order = sorted(range(len(view)), key=lambda i:
                               (not bool(view[i].herdr_locations), -view[i].updated))
                return [rows[0], *(rows[i + 1] for i in order)]
            return rows

        rows = build_rows()
        env = os.environ.copy()
        # User fzf bindings/output flags can alter the selection protocol.
        env.pop("FZF_DEFAULT_OPTS", None)
        env.pop("FZF_DEFAULT_OPTS_FILE", None)
        counts = "  ·  ".join(f"{sum(s.tool == tool for s in sessions)} {name}"
                                for tool, name in (("codex", "Codex"), ("claude", "Claude")))
        theme = ["--ansi", "--highlight-line", "--pointer=▌", "--info=inline-right",
                 "--border=rounded", "--border-label= fzf-sessions ", "--border-label-pos=3",
                 "--padding=1,2", "--input-border=bottom", "--header-border=bottom",
                 "--footer-border=top", "--separator=─"]
        if use_color:
            theme += ["--color=border:8,label:6,header:8,prompt:6,pointer:6,marker:6,hl:3,hl+:3,info:8,spinner:6"]
        else:
            theme += ["--no-color"]
        mode = "metadata"
        search_cache = Path(tmp) / "search.sqlite"
        script = [sys.executable, str(common_mod.ENTRYPOINT)]
        ready_rows = Path(tmp) / "herdr-rows.tsv"
        initial_rows = Path(tmp) / "initial-rows.tsv"
        initial_rows.write_text("\n".join(rows))
        search_index = search_mod.SearchIndex.create(search_cache, sessions, initial_rows, ready_rows, show_herdr)
        content_ready = False
        env["FZF_SESSIONS_HERDR_STATE"] = str(ready_rows)
        env["FZF_SESSIONS_SEARCH_DB"] = str(search_cache)
        env["FZF_SESSIONS_PREVIEW_CACHE"] = str(Path(tmp) / "usage")
        if show_herdr:
            def refresh_herdr(base: tuple[models_mod.Session, ...]) -> None:
                try:
                    # The worker owns its copies; UI-visible objects never mutate.
                    updated = [models_mod.Session(**asdict(session)) for session in base]
                    herdr_mod.annotate_herdr_sessions(updated)
                    # One atomic artifact contains both rows and preview locations.
                    common_mod.atomic_write(ready_rows, json.dumps({
                        "sessions": [asdict(session) for session in updated], "rows": build_rows(updated)}))
                except (OSError, RuntimeError):
                    pass  # Cancelling the picker may already have removed its tempdir.
            refresh_thread = None

            def start_refresh() -> None:
                nonlocal refresh_thread
                if refresh_thread is not None and refresh_thread.is_alive():
                    return
                if ready_rows.exists():
                    common_mod.atomic_write(initial_rows, "\n".join(common_mod.read_view(ready_rows)["rows"]))
                    ready_rows.unlink()
                base = tuple(models_mod.Session(**asdict(session)) for session in sessions)
                refresh_thread = threading.Thread(target=refresh_herdr, args=(base,), daemon=True)
                refresh_thread.start()

            start_refresh()
        while True:
            if ready_rows.exists():
                view = common_mod.read_view(ready_rows)
                rows = view["rows"]
                sessions = [models_mod.Session(**record) for record in view["sessions"]]
            help_command = shlex.join([*script, "--shortcut-modal", "herdr" if show_herdr else "standalone"])
            bindings = "alt-p:toggle-preview,alt-?:execute-silent(" + help_command + ")+clear-screen"
            extra = ["--disabled"]
            if mode == "content" and not content_ready:
                print("Indexing conversation text for content search…", file=sys.stderr)
                search_index.enable_content(sessions)
                content_ready = True
            input_rows = search_index.rows(mode, query, rows)
            search_command = shlex.join([*script, "--search", str(search_cache), mode]) + " {q}"
            bindings += ",change:reload(" + search_command + ")"
            if show_herdr:
                extra += ["--no-sort", "--id-nth=1"]
                watch_command = shlex.join([*script, "--watch-herdr", str(ready_rows), str(search_cache), mode])
                # A background transform survives ordinary query reloads. Once ready,
                # it asks fzf to search using the query at that moment, not a stale one.
                bindings += ",load:unbind(load)+bg-transform(" + watch_command + ")"
            preview_command = command + (" content {q}" if mode == "content" else " metadata ''")
            proc = subprocess.run(["fzf", "--delimiter=\t", "--with-nth=2..", "--nth=" + ("4,5" if show_herdr else "3,4"),
                "--layout=reverse", "--no-multi", "--tabstop=2", "--header-lines=1",
                "--query", query, "--print-query", "--expect=alt-s,alt-c" + (",alt-r" if show_herdr else ""),
                "--prompt=" + ("Directory / title  › " if mode == "metadata" else "Conversation  › "),
                "--header=" + f"{len(sessions)} sessions  ·  {counts}" + (f"  ·  {herdr_note}" if herdr_note else ""),
                "--footer=Alt-?  shortcuts",
                "--preview", preview_command, "--preview-window=right,55%,wrap,hidden,border-left", "--preview-label= Session recap ", "--bind", bindings, *theme, *extra],
                input="\n".join(input_rows) + "\n", text=True, stdout=subprocess.PIPE, env=env)
            if proc.returncode == 130:
                return None
            if proc.returncode not in (0, 1):
                raise RuntimeError(f"fzf exited with status {proc.returncode}")
            output = proc.stdout.splitlines()
            # An expected shortcut can exit with status 1 when there is no
            # selected row. Search switching and refresh must still work then.
            expected = ("alt-s", "alt-c", "alt-r") if show_herdr else ("alt-s", "alt-c")
            if proc.returncode == 1 and (len(output) < 2 or output[1] not in expected):
                return None
            if not output:
                raise RuntimeError("fzf returned an invalid selection")
            query = output.pop(0)
            if output and output[0] == "alt-s":
                mode = "content" if mode == "metadata" else "metadata"
                continue
            if show_herdr and output and output[0] == "alt-r":
                start_refresh()
                continue
            copy = bool(output and output[0] == "alt-c")
            if output and output[0] in ("", "alt-c"):
                output.pop(0)
            if copy and not output:
                return None
            try:
                index = int(output[0].split("\t", 1)[0])
                if index < 0:
                    raise ValueError
                if ready_rows.exists():
                    sessions = [models_mod.Session(**record) for record in common_mod.read_view(ready_rows)["sessions"]]
                selected = sessions[index]
            except (ValueError, IndexError):
                raise RuntimeError("fzf returned an invalid selection") from None
            if copy:
                if dry_run:
                    print(launch_mod.resume_command(selected))
                else:
                    launch_mod.copy_resume_command(selected)
                return None
            return selected
