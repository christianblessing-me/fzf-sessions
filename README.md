# fzf-sessions

Find and resume local Codex and Claude Code sessions across repositories using fzf.
Python standard library only; no pip packages, cloud API calls, or persistent daemon.

## Install and run

Supported platforms: **macOS and Linux** (including WSL). Native Windows is not
supported. The picker, content search, recorded usage, and resume work on both
platforms; Apple Intelligence summaries and clipboard copying require macOS.

Requires Python 3.10+, [fzf](https://github.com/junegunn/fzf) 0.74.5+, and the CLI for the
session you want to resume. On macOS, install fzf with `brew install fzf`.
On Linux, install Python through your distribution and get a supported fzf from
[its releases](https://github.com/junegunn/fzf/releases); distribution packages
may be older than the required version. Herdr integration requires Herdr 0.9.5+.

From an extracted release or checkout:

```sh
python3 install.py
export PATH="$HOME/.local/bin:$PATH"
fzf-sessions --version
fzf-sessions --doctor
```

Keep the PATH line in your shell configuration. Installation copies the complete
tool to `~/.local/share/fzf-sessions` and links `~/.local/bin/fzf-sessions` to it.
No pip packages or administrator access are required. Run the installer again
from a newer release to upgrade. Installed copies do not change when the source
checkout changes. Use `--prefix /your/location` for a different installation root.
The installer refuses to replace unrelated files or unmanaged directories.
Close running pickers before upgrading so their helper subprocesses use one version.

To uninstall (unlink an installed Herdr plugin first):

```sh
herdr plugin unlink fzf-sessions  # only if you linked the installed copy
python3 "$HOME/.local/share/fzf-sessions/install.py" --uninstall
```

For a custom prefix, pass that same `--prefix` when uninstalling. History, summary
caches, and shell configuration are preserved. You can also run the checkout
directly without installing:

```sh
./fzf-sessions
./fzf-sessions groceries
./fzf-sessions --tool claude
./fzf-sessions --here
./fzf-sessions --dry-run
```

Run from any directory using the full path, or add this checkout to your PATH:

```sh
export PATH="/absolute/path/to/fzf-sessions:$PATH"
```

Add that line to your shell configuration to keep it across terminals.
An optional shorter alias: `alias fs='fzf-sessions'`.

The default **directory/title** mode searches the folder name (usually the
repo name) and full session title, including text beyond the displayed cutoff. The session column comes before the directory
column; titles are capped at 50 characters with an ellipsis, and directories
show only the final folder name. Full paths remain in the
preview and resume/copy commands. Tool, branch, session ID, and conversation text do
not participate. Sessions start sorted by most recent activity.

Press **Alt-S** to switch between directory/title and **content** search. The
prompt shows the current mode and your query carries over. Content search checks
all saved user/assistant text, excluding tool calls and tool results. It matches
all whitespace-separated words literally, ignoring case; directory/title mode
uses fzf's normal fuzzy matching. Content is indexed only when first requested,
and that snapshot is reused until the picker closes. In content mode, **Alt-P**
shows up to six matching user/assistant passages, with literal search terms
highlighted. Terms may occur in different messages; excerpts include surrounding
text to explain the match. Tool output and injected workspace context are
excluded. Excerpts update as the query changes and reuse an existing cached
recap when available, without starting model generation on every keystroke.
Enter resumes in the current terminal,
using the original working directory; Esc or Ctrl-C cancels. The preview is hidden
by default. Press **Alt-P** to show or hide it when needed. It immediately shows
the original request, last request, and last response. If Apple's `fm` CLI is
available, an on-device AI summary replaces that fallback with **Goal / Progress /
Next**. Progress gets the most space: concrete changes, decisions, verification,
and remaining issues, usually in 3–6 bullets. Colored section headings, a compact
session header, and wrapped, indented bullets make the recap easier to scan.
The picker uses colored agent labels, muted metadata, bold session titles, and a
highlighted selection. Search mode appears in the prompt; shortcuts are in the
help screen (**Alt-?**). The footer contains only the help hint. Set
`NO_COLOR=1` to disable colors throughout. Normal fzf preview scrolling bindings
apply (Shift-Up/Down).

Above the summary, a **Last recorded usage** block shows the model, cumulative
input/output tokens, reused input tokens and cache percentage, and context usage
when available. It is read directly from the saved transcript, independently of
Apple Intelligence; monetary amounts are never displayed. Missing data is marked
as not recorded rather than zero.

Codex totals use the latest cumulative snapshot, with cached input already
included in input tokens. Claude totals sum unique saved API responses (merging
repeated content-block records); input includes uncached input, cache reads, and
cache writes. These totals describe recorded requests, not billing or subscription
quota. Child-agent usage is excluded. Claude context is the last request's input
size, including cached input; its window capacity is not guessed from the model
name. Codex shows the last recorded context count and capacity when provided.
These are saved snapshots, not live measurements or predictions after resuming.
Usage is loaded only when opening a preview, leaving picker startup unaffected.

Summaries require macOS 27+, Apple Intelligence with its on-device model ready,
and acceptance of the `fm` terms (`sudo fm license`). Generation uses
`fm respond --model system`; no cloud model is used. Errors or a 45-second timeout
leave the saved-message fallback visible. AI summaries are labelled as such and
may be inaccurate; the model sees bounded excerpts, not the entire session.
Before generation, the preview checks for macOS, an `fm` executable on PATH, and
an available `system` model via `fm models` (with a three-second timeout). It
shows the reason and saved messages when any check fails. An unavailable PCC
model does not prevent local summaries. Cached recaps remain readable without
the model; availability checks run only when a new recap is needed.

Summaries are cached across launches in
`${XDG_CACHE_HOME:-~/.cache}/fzf-sessions/summaries/`. Cache keys use the actual
summary input and instructions, so metadata-only transcript changes reuse the recap.
After generation, cleanup keeps at most 256 summaries and removes summaries older
than 30 days. Concurrent previews share a generation lock; while another summary
is generating, saved messages remain available. Delete that directory to clear it.
Set `FZF_SESSIONS_NO_AI=1` to use saved-message previews without invoking `fm`.

**UPDATED** is the timestamp of the last recorded conversation activity, read
backwards from the transcript. File modification times, index maintenance,
settings updates, and token-count refreshes do not make a session look recent.
Codex falls back to its recorded recency or creation time when no activity can
be recovered; otherwise missing timestamps show as `unknown`. Relative ages are
calculated when the picker opens (or switches search modes).

Press **Alt-?** for a centered shortcut-help modal over the session list. It lists navigation, search,
preview, copy, and (inside Herdr) refresh shortcuts, plus the OPEN marker legend.
Press **Esc**, **Enter**, or **Alt-?** again to dismiss it; the underlying picker
stays running with its query, selection, search mode, and preview state intact.
Use **↑/↓** or Page Up/Down to scroll help on smaller terminals. Ctrl-C also
dismisses help; outside the modal, Ctrl-C closes the picker.

`--here` matches the exact current directory, keeping worktrees separate.
Press **Alt-C** to copy the selected session's resume command to the macOS
clipboard and close the picker without launching the agent. The command includes
`cd` to its original working directory, with shell quoting for paths containing
spaces or special characters. Paste it in another terminal to resume there.
`--dry-run` prints the command instead of copying it.

`--dry-run` opens the picker and prints the selected resume command without
launching an agent. `--list` outputs session metadata as JSON without opening fzf;
it does not apply the positional fzf query.

## Herdr plugin

The checkout also contains a Herdr plugin (`herdr-plugin.toml`), compatible with
Herdr 0.9.5+ on macOS and Linux. It reuses the same picker; Python 3.10+, fzf,
and your agent CLI must be on Herdr's PATH. Apple Intelligence summaries and
clipboard copy are macOS features; browsing, content search, and resume also
work without them.

From a terminal **inside Herdr**, link this checkout and open the picker:

```sh
herdr plugin link /absolute/path/to/fzf-sessions
herdr plugin action invoke fzf-sessions.open
```

For an installed copy, use `herdr plugin link "$HOME/.local/share/fzf-sessions"`.
For development, link the checkout using its absolute path. Linking registers
the local files; code edits take effect on the next invocation. After changing
`herdr-plugin.toml` (for example popup dimensions), run the link command again
to refresh the registered manifest. To remove the link:

```sh
herdr plugin unlink fzf-sessions
```

The picker opens as a floating popup, 90% of the terminal width and 80% of its
height, leaving the workspace visible around it. **Enter** refreshes the live
agent list and jumps to an existing matching pane, switching workspace and tab
as needed. If it is open in multiple panes, one in the calling workspace is
preferred, otherwise the first matching pane is used. This also works before
the background OPEN markers finish loading.

If no live match exists, Enter creates a new tab in the calling workspace, sets
the selected session's original working directory, submits its native resume
command, and focuses the new tab. If a marked session disappears or a live
lookup/focus request fails, the plugin reports the problem instead of opening a
duplicate; reopen the picker to refresh a stale marker. The popup closes
when its command exits. **Alt-C** still copies and closes without creating a tab;
**Esc** cancels. **Alt-P** and **Alt-S** retain their usual behavior.

When running inside Herdr, the picker opens immediately after local discovery,
then reads one live server snapshot in the background. The compact **OPEN**
column appears first: a green `●` marks a saved session already open anywhere on
that server, across all workspaces, tabs, and panes. Workspace/tab names are kept
in the preview, which lists every matching location, pane ID, and agent status.

Matching uses the agent's reported session ID (or exact transcript path), never
the repository or folder name. `—` means no exact live match was reported; it
does not prove the session is closed. Detection depends on Herdr receiving session
references from its agent integrations. `?` means checking or unavailable. Markers
update automatically when the background read finishes. Open sessions are grouped
at the top, newest activity first within each group. This order is preserved
while filtering in both search modes; fuzzy scores do not reorder the Herdr list.
The query is preserved, and the refreshed list starts at the top for navigation.
Press **Alt-R** to request another live-status refresh without returning to the
shell. The current query and metadata/content search mode are retained; requests
made while a refresh is running reuse that in-flight read. The list stays usable
while the snapshot loads, then updates its markers, locations, and active-first
ordering. Refresh updates Herdr status for the sessions already listed; reopening
the picker also rediscovers saved session files. A slow or unavailable Herdr
server does not delay opening the picker. Status is refreshed on opening and on
Alt-R, rather than continuously monitored, and covers the connected Herdr server rather than other named
sessions or remote machines. Outside Herdr the extra column is omitted.

An optional shortcut can be added to your Herdr configuration, using an unused
key in your layout:

```toml
[[keys.command]]
key = "prefix+shift+s"
type = "plugin_action"
command = "fzf-sessions.open"
description = "Find a coding session"
```

You can also run `fzf-sessions --herdr` directly inside a Herdr pane. Add
`--dry-run` to print the intended resume command without creating a tab.
The action carries its source workspace into the popup explicitly. The adapter
also understands `HERDR_PLUGIN_CONTEXT_JSON` when popup processes do not receive
`HERDR_WORKSPACE_ID` directly. Startup errors stay visible in the popup until you
press Enter, rather than disappearing as soon as the process exits.
The popup itself uses Herdr's built-in active-pane targeting; popup launch
requests must not include `--workspace` or `--target-pane`. It uses `HERDR_BIN_PATH` when provided,
and uses the pane/tab IDs returned by Herdr. Failed or timed-out launch requests
are not automatically retried: inspect any reported tab before trying again.
A successful submission means the command was queued, not that the agent has
finished starting or passed any repository trust prompts.

The standalone command still resumes in the current terminal by default, even
when run inside Herdr; the plugin selects `--herdr` explicitly.

## Data and limitations

- Codex: reads the newest usable `state_*.sqlite` index read-only, plus session
  names in `session_index.jsonl`. Falls back to transcripts under `sessions/` for
  sessions absent from the index. Archived, batch (`exec`), and child-agent
  sessions are excluded when identified by their source metadata.
- Claude Code: reads top-level `projects/*/*.jsonl` transcripts, extracting the
  actual working directory rather than decoding the project folder name. Prefers
  custom titles, then generated titles, then the first user prompt. Child-agent
  transcripts are excluded.
- Respects `CODEX_HOME` and `CLAUDE_CONFIG_DIR`; otherwise uses `~/.codex` and
  `~/.claude`.

Reads are bounded to keep startup fast: Claude metadata uses the first 64 KiB and
last 128 KiB; fallback Codex metadata uses the first 64 KiB. Previews use the last
512 KiB, plus the first 64 KiB for the original request. Summary input is capped
at 6,500 characters. A title or message outside those windows may be missing. Unknown or
partially written JSONL records are skipped. Unexpected record shapes are skipped
with a diagnostic identifying the source file. These internal storage formats may
change with CLI updates. Content search reads the full transcripts on first use.
Session metadata, the SQLite search index, and parsed preview usage stay in a
private temporary directory removed when the picker closes. Content and matching
passages are read from that index after the first scan, rather than reparsing
transcripts for every query. Usage is cached until its transcript changes. AI summaries persist in the
local cache described above. Everything is local.

The standalone tool resumes saved conversations in the current terminal. The
Herdr plugin can locate and focus matching live sessions on its connected server.
Other terminal applications and unsaved terminal state are not tracked. Resume behavior and permission prompts are handled by each CLI.
A missing original working directory produces an error.

To keep the picker output predictable, `FZF_DEFAULT_OPTS` and
`FZF_DEFAULT_OPTS_FILE` are ignored for this invocation.

## Checks

```sh
python3 -m unittest discover -s tests -v
```

Tests use temporary fixtures, mocked model responses, real fzf filtering, and a
fake Herdr executable for the complete CLI launch path. They do not resume real
agent sessions or modify their history.


Interactive tests create an isolated terminal and exercise the actual fzf picker,
help dismissal, search switching, and Herdr refresh/focus with a fake server CLI.
They skip explicitly when the environment forbids access to `/dev/tty`. To require
those checks in an unrestricted development terminal or CI runner:

```sh
FZF_SESSIONS_REQUIRE_PTY=1 python3 -m unittest discover -s tests -v
```

The executable is a thin entry point; implementation lives in `fzf_sessions/`.
`adapters.py` reads agent history, `search.py` owns the SQLite index, `ui.py`
coordinates fzf, and `herdr.py` handles live session lookup and navigation.
Preview rendering, usage accounting, summary generation, and help each have their
own module. Keep the package directory alongside the executable when installing
or linking a checkout. Development edits take effect on the next invocation;
the plugin manifest and its link do not need changing for Python-only edits.


## Diagnostics

`fzf-sessions --doctor` reports the tool and dependency versions, configured history
roots, agent executables, Herdr invocation context, clipboard support, and local
summary availability. It does not scan conversations, display session IDs, query
the Herdr server, or start agents. The optional model probe uses `fm models`, not
a generation request. Paths may contain your username; review output before
sharing it. Missing optional integrations are informational. Exit status is 1
when the required fzf dependency is missing or unsupported, otherwise 0.

## Release process

`VERSION` is authoritative for the CLI version. When preparing a release:

1. Update `VERSION` and add its changes to `CHANGELOG.md`.
2. Run `python3 scripts/release.py --sync` to update the Herdr manifest.
3. Run `python3 scripts/release.py` and the full test suite.
4. Require the **Checks** workflow to pass on macOS and Linux, with Python 3.10
   and 3.13. It builds the tested fzf 0.74.5 baseline and fails if terminal tests
   skip. The workflow also checks clean installation and removal.
5. Smoke-test the native Herdr integration, then tag and publish the reviewed
   source tree, including `LICENSE`, `VERSION`, `install.py`, the executable,
   `fzf_sessions/`, and `herdr-plugin.toml`.

The workflow performs checks only; it does not publish releases. A workflow file
in this checkout is not evidence that hosted CI has run. No history, generated
summary caches, or local test output belongs in a release archive.

## License

MIT; see [LICENSE](LICENSE). Copyright 2026 Christian Blessing.
