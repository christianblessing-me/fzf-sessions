# How it works

## Session history

- Codex history comes from its local database and saved conversations. Session
  names also come from `session_index.jsonl`.
- Claude Code history comes from `projects/*/*.jsonl`. Folder names come from
  the saved working directory, rather than the encoded project folder name.
- Archived Codex sessions, batch runs, and sessions created by child agents are
  left out when their saved records identify them.
- `--here` matches the exact folder, so separate Git worktrees stay separate.
- **UPDATED** uses the last saved conversation activity. Touching a file or
  updating settings does not make a session look recent.
- Ages update when the list opens or you switch search modes.
- Missing dates show as `unknown`. Missing working folders prevent resume.
- Resuming uses each tool's own command. Its normal permission and trust prompts still apply.
- Other terminal apps and unsaved terminal contents are not tracked.

## Search and previews

- Folder/title search uses fzf's fuzzy matching. The agent name, branch, session
  ID, full parent path, and conversation text are excluded.
- Conversation search checks saved user and assistant messages. All search
  words must appear, ignoring case; they can appear in different messages.
- Tool calls, tool results, and recognized injected workspace instructions are excluded.
- The full conversations are read when you first switch to conversation search.
  That search copy lasts until you close the list. Reopen it to include new messages.
- The preview shows up to six matching passages and highlights the search words.
- Titles are shortened to 50 characters in the list. Folders show their final name.
  Full titles remain searchable; full paths appear in the preview and resume commands.
- `--list` prints session details and does not apply the typed search query.
- `FZF_DEFAULT_OPTS` and `FZF_DEFAULT_OPTS_FILE` are ignored to keep shortcuts and output consistent.

## Token usage

- Counts describe saved requests, not billing, subscription limits, or future context use.
- Missing values show as not recorded, rather than zero. Child-agent usage is excluded.
- Codex uses its latest running totals. Reused input tokens are already included in input.
- Claude adds unique saved responses, combining repeated records for one response.
  Input includes new input, cache reads, and cache writes.
- Claude context is the last request's input size, including cached input.
  Its maximum context size is not guessed from the model name.
- Codex shows the saved context count and maximum size when available.

## Local summaries

- Only Apple's `system` model is used. The tool does not select a cloud model.
- Before generating, it checks the OS, the `fm` command, and the local model's availability.
- A missing PCC model does not stop local summaries.
- A failed model check or generation request leaves saved messages visible.
  Model checks time out after three seconds; generation times out after 45 seconds.
- Conversation search reuses an existing summary but does not generate one as you type.
- Saved summaries still work when the model is no longer available.
- Summaries are stored in `${XDG_CACHE_HOME:-~/.cache}/fzf-sessions/summaries/`.
  Delete that folder to clear them.
- A changed summary input creates a new summary. Unrelated file changes do not.
- After generation, cleanup keeps at most 256 summaries and removes entries older than 30 days.
- Only one summary is generated at a time. Other previews show saved messages while waiting.

## Herdr behavior

- Matching uses the exact agent session ID or conversation file path, not a folder name.
- Detection covers the connected Herdr server, including its workspaces, tabs, and panes.
  It does not check other servers or remote machines.
- Herdr must receive session details from its agent integrations. A **—** marker
  means no match was reported; it does not prove the session is closed.
- Open sessions stay first while searching, with newer sessions first within each group.
- Status loads in the background and refreshes on **Alt-R**. It is not monitored continuously.
- Refresh keeps your query and search mode. Reopening also finds newly saved sessions.
- Enter checks again before jumping. If a session has several open panes,
  one in the calling workspace is preferred.
- A failed lookup or jump reports an error instead of creating a duplicate.
  If a marked session has disappeared, reopen the list before trying again.
- New sessions open in a new tab in the calling workspace, using the original folder.
- Failed or timed-out commands are not retried automatically. Check the workspace
  before retrying: a new tab may already exist.
- Running `fzf-sessions` directly resumes in the current terminal, even inside Herdr.
  Use `--herdr` to request Herdr navigation; the plugin sets this option for you.

## Reading limits and privacy

- To keep startup quick, Claude session details use the first 64 KiB and last
  128 KiB of a conversation file. Codex file fallback uses the first 64 KiB.
- Previews use the first 64 KiB and last 512 KiB. Summary input is limited to
  6,500 characters, so it does not cover the whole conversation.
- Titles or messages outside these limits may be missing from previews.
- Incomplete records are skipped. Unexpected record formats are skipped with a
  warning that names the file. Agent updates may change their history formats.
- Search data and parsed usage are stored in a private temporary folder,
  removed when the list closes. AI summaries stay in the cache described above.
- `--doctor` shows versions, executable paths, history folders, Herdr context,
  clipboard support, and model availability. It does not read conversations,
  show session IDs, contact the Herdr server, or start agents.
- Diagnostic paths may include your username. Check them before sharing output.
- `--doctor` returns status 1 if fzf is missing or unsupported. Missing optional tools are informational.
