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

## Lessons from terminal and Herdr testing

- fzf can return status 1 for an expected shortcut when no row is selected.
  Process the shortcut output before treating status 1 as cancellation.
- fzf's `execute-silent` can restore terminal input settings after one second.
  Help must keep raw input active so Escape works even after the user pauses to read it.
- On macOS, terminal state checks can fail after the controlling session exits.
  Capture the final state before closing the session. Ignore only kernel bookkeeping
  such as `PENDIN`, not actual differences in input settings.
- Wait for fzf's actual state in integration tests instead of relying on fixed delays.
  The test driver uses a private Unix socket; the application does not need a listener.
- Put fake Codex and Claude commands on the test PATH so tests cannot launch real agents.
- Herdr `pane run` acknowledges that a command was queued, not that an agent finished starting.
  Exit code 0 with no output is a valid acknowledgement.
- Keep structured-response checks for workspace creation and agent lists: their IDs
  and session identities are needed to avoid running commands in the wrong pane.

## Releases

- Follow the [release guide](releasing.md) for versioning, packaging, CI, and publishing.
- Keep `AGENTS.md` in the repo root current so future coding sessions can find these instructions.

## Check a marketplace install

- Test `herdr plugin install christianblessing-me/fzf-sessions --yes` from GitHub,
  not just the standalone `install.py` path.
- Use a fresh temporary folder for `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and
  `XDG_CACHE_HOME`. Point `HERDR_CONFIG_PATH` at a config file inside that folder.
- Run `herdr --help` with those settings and confirm its config and log paths are temporary.
- Run `herdr plugin list` and confirm that the test profile is empty before installing.
- Do not unregister or replace the user's real development link to perform this check.
- After installation, check the registered action and run `--version` and a fixture-only
  `--list` from the downloaded plugin folder. Confirm that its Python package is present.
- Check `plugin update` and `plugin uninstall` using the same isolated settings.
- Use test histories and fake agent commands for any picker test. Do not resume real user sessions.
