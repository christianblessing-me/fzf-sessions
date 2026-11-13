# Development

## Run from source

- Keep the `fzf-sessions` executable, `fzf_sessions/` package, `VERSION`, and
  `herdr-plugin.toml` together.
- Run `./fzf-sessions` from the repo folder, or add that folder to PATH.
- Source edits take effect the next time you open the tool.
- An installed copy does not follow source edits. Run the installer again to update it.

## Link Herdr to your source

Run inside Herdr, using your repo's absolute path:

```sh
herdr plugin link /absolute/path/to/fzf-sessions
herdr plugin action invoke fzf-sessions.open
```

- Python code changes need no reinstall or relink.
- After changing `herdr-plugin.toml`, link it again to update the registered settings.
- To remove the plugin link, run `herdr plugin unlink fzf-sessions`.
- Popup size is set in the manifest. The default is 90% width and 80% height.
- Popup requests use Herdr's active pane. Do not add `--workspace` or `--target-pane` to them.
- The action passes its calling workspace into the popup. The code also accepts
  `HERDR_PLUGIN_CONTEXT_JSON` when `HERDR_WORKSPACE_ID` is missing.
- `HERDR_BIN_PATH` can select the Herdr executable.

## Run tests

```sh
python3 -m unittest discover -s tests -v
```

- Tests use sample histories, fake model responses, real fzf filtering, and a fake Herdr command.
- They do not resume real sessions or change session history.
- Terminal tests exercise fzf, help dismissal, search switching, refresh, and jumping.
- Environments that block `/dev/tty` skip those tests. To make a skip fail the run:

```sh
FZF_SESSIONS_REQUIRE_PTY=1 python3 -m unittest discover -s tests -v
```

- GitHub Actions tests macOS and Linux with Python 3.10 and 3.13.
- It builds fzf 0.74.5 and requires the terminal tests to run.
- It also checks installation and removal from a path containing spaces.
- The workflow runs checks only. It does not publish releases.

## Code layout

- `adapters.py` — read Codex and Claude Code history.
- `search.py` — search full titles and conversation text.
- `ui.py` — build and run the fzf list.
- `herdr.py` — find open sessions and navigate to them.
- `previews.py`, `conversation.py` — choose and display saved messages.
- `summaries.py` — check the local model, generate summaries, and save them.
- `usage.py` — read saved token counts.
- `help_ui.py` — draw the shortcut window and handle its keys.
- `doctor.py` — report local setup information.

## Prepare a release

1. Update `VERSION`, the source of the CLI version.
2. Add changes under that version in `CHANGELOG.md`.
3. Run `python3 scripts/release.py --sync` to update the Herdr manifest.
4. Run `python3 scripts/release.py` and the full test suite.
5. Check that GitHub Actions passes on macOS and Linux.
6. Test the real Herdr plugin: open, search, preview, help, refresh, and jump across workspaces.
7. Tag the version and publish the reviewed source tree on GitHub.

- Include the license, version file, installer, executable, Python package,
  plugin manifest, and documentation in the release.
- Keep session history, summary caches, and local test output out of release archives.
