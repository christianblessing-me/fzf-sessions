# Working on fzf-sessions

## Where to find project knowledge

- `README.md`: installation, everyday use, and shortcuts.
- `docs/development.md`: local development, tests, and code layout.
- `docs/reference.md`: session formats, search, usage counts, and Herdr behavior.
- `docs/releasing.md`: version choices, release commands, checks, and lessons from past releases.
- `CHANGELOG.md`: changes shipped in each release.

Update these files when behavior or the release process changes. Keep lasting
decisions in the repo rather than relying on a chat transcript.

## Product rules

- Use simple English and short bullet lists in user-facing documentation.
- Keep runtime dependencies limited to the Python standard library and external CLIs.
- Default search covers folder names and full session titles. Conversation search is separate.
- Previews start hidden. Keep the shortcut help and documentation in sync with bindings.
- AI summaries are optional and local. Missing models must leave saved messages usable.
- Show recorded token usage, never monetary estimates or guessed subscription limits.
- In Herdr, focus an exact existing session match. Otherwise resume in a new workspace
  using the session's original folder. Do not open a duplicate after a failed lookup.

## Testing and Herdr

- Use fixture histories and fake agent commands for automated tests.
- Do not resume real user sessions or change their history just to test a change.
- Read the installed Herdr CLI help and bundled API schema before changing its commands.
- Follow Herdr's built-in guidance (`herdr --skill`) before controlling a live session.
- An exit-0 empty reply is valid for `pane run`, `workspace focus`, and `agent focus`.
  Creation and inventory commands must still return structured data.
- Use returned workspace and pane IDs. Never guess them or reuse the caller's pane.
- Do not blindly retry a timed-out mutation: it may already have succeeded.
- Terminal tests matter. A skipped terminal test is not a passed terminal test.
- Known terminal pitfalls are recorded in `docs/development.md`.

## Releases

- Follow `docs/releasing.md` when the user asks for a release.
- `VERSION` is authoritative; sync `herdr-plugin.toml` with the release script.
- Check CI for the exact commit being released. Report queued, skipped, or failed checks honestly.
- Build downloads from committed files with `git archive`, not a copy of the working folder.
- Keep existing public tags and release downloads unchanged. Publish changes as a new version.
- Documentation changes alone do not require publishing another release.
