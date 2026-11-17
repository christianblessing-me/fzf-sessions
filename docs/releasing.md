# Releasing fzf-sessions

This is the release guide for maintainers and coding agents. Update it whenever
the process changes. GitHub Actions runs checks; it does not publish releases.

## Website updates

- The landing page lives in `site/` and uses a separate Website workflow.
- Changes to `site/` on `main` deploy to `https://fzf-sessions.christianblessing.me`.
- Website updates do not require a tool version bump or a GitHub release.
- See [the website guide](../site/README.md) for preview and domain settings.

## Choose a version

- Use **patch releases** for fixes: `0.2.0` → `0.2.1`.
- Use **minor releases** for features or changes to normal behavior: `0.2.0` → `0.3.0`.
- This is our convention while the project is below `1.0`. It is not a claim
  that SemVer requires every `0.x` project to use these rules.
- Example: moving resumes from tabs to workspaces, plus fixing the false error,
  shipped together as `0.2.0`. The error fix alone would have suited `0.1.1`.
- Do not replace a published version's tag or files. Release a new version instead.
- Do not publish a release unless the user has asked for one.

## 1. Prepare the commit

- Check `git status --short`. Keep unrelated user files out of the release commit.
- Change `VERSION` and add a dated section in `CHANGELOG.md`.
- Describe what users will notice, including changed defaults.
- Sync the plugin version, then check the metadata:

```sh
python3 scripts/release.py --sync
python3 scripts/release.py
```

- Run checks appropriate to the changes. For application changes, use the full suite,
  including the real terminal tests:

```sh
FZF_SESSIONS_REQUIRE_PTY=1 python3 -m unittest discover -s tests -v
```

- Stage the intended files explicitly, commit them, and push `main`.
- Record the exact commit being released. Run the remaining shell examples in
  the same terminal so these variables remain set:

```sh
release_version="$(cat VERSION)"
release_tag="v${release_version}"
release_commit="$(git rev-parse HEAD)"
release_repo="christianblessing-me/fzf-sessions"
```

## 2. Check GitHub Actions

```sh
gh run list --repo "$release_repo" --limit 5 \
  --json databaseId,status,conclusion,headSha,url
```

- Choose the run whose `headSha` equals `release_commit`, rather than assuming
  the latest run belongs to the right commit.
- Replace `RUN_ID` below with that run's ID:

```sh
gh run view RUN_ID --repo "$release_repo" --json status,conclusion,headSha,jobs
gh run watch RUN_ID --repo "$release_repo" --exit-status --interval 15
```

- Require all four jobs to pass: macOS and Linux, each with Python 3.10 and 3.13.
- The workflow requires real terminal tests and checks a clean installation.
- A queued job is waiting for a runner. It has not passed or failed. Do not create
  repeated reruns just because macOS runners are slow to become available.
- For a failed run, read its logs before changing code or the workflow:

```sh
gh run view RUN_ID --repo "$release_repo" --log-failed
```

- If a sandbox blocks gh's cache directory, point its cache at an allowed temporary folder:

```sh
XDG_CACHE_HOME="${TMPDIR:-/tmp}/fzf-sessions-gh-cache" \
  gh run view RUN_ID --repo "$release_repo" --log-failed
```

- If `gh` reports a DNS or connection error, check network permissions and
  authentication. Do not assume the CLI is missing or reinstall it.
- Do not disable tests or accept skips merely to make a release green.

## 3. Build and verify the download

- Build from the recorded commit. `git archive` excludes untracked files, Git
  metadata, and ignored caches. Do not zip the working folder.
- Make sure HEAD still points to the commit checked above.

```sh
release_dir="$(mktemp -d)"
git archive --format=tar.gz \
  --prefix="fzf-sessions-${release_version}/" \
  --output="$release_dir/fzf-sessions-${release_version}.tar.gz" \
  "$release_commit"

python3 - "$release_dir" "$release_version" <<'PY'
import hashlib
from pathlib import Path
import sys

directory = Path(sys.argv[1])
archive = directory / f"fzf-sessions-{sys.argv[2]}.tar.gz"
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(directory / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n")
PY
```

- Extract this exact archive and test its installer from outside the repo:

```sh
tar -xzf "$release_dir/fzf-sessions-${release_version}.tar.gz" -C "$release_dir"
python3 "$release_dir/fzf-sessions-${release_version}/install.py" \
  --prefix "$release_dir/install check"
"$release_dir/install check/bin/fzf-sessions" --version

HERDR_ENV=0 \
  CODEX_HOME="$release_dir/empty-codex" \
  CLAUDE_CONFIG_DIR="$release_dir/empty-claude" \
  "$release_dir/install check/bin/fzf-sessions" --list

python3 "$release_dir/install check/share/fzf-sessions/install.py" \
  --prefix "$release_dir/install check" --uninstall
```

- Confirm the printed version matches `VERSION`, and the empty test history returns `[]`.
- Check the installed plugin manifest uses the same version.
- Check documentation and the screenshot are present in the installed copy.
- Keep test prefixes and history folders temporary. Do not replace a real installation
  or read user conversations for this check.
- For Herdr behavior changes, also verify the affected flow against the installed
  CLI contract. Use an isolated test workspace for live checks; remove only what you created.

## 4. Create and publish the release

- Write `$release_dir/release-notes.md` in plain English with:
  - The changes users will notice.
  - Installation and update commands for this exact archive.
  - Requirements and any compatibility changes.
  - A link to the README at the new version tag.
- Explain that installed copies need the installer run again. A checkout linked
  for development picks up code changes on the next launch.
- After changing `herdr-plugin.toml`, tell installed-plugin users to refresh the link:

```sh
herdr plugin link "$HOME/.local/share/fzf-sessions"
```

- Use the actual installation folder for custom prefixes or development checkouts.
- Create a draft with the verified archive and its checksum file:

```sh
gh release create "$release_tag" \
  "$release_dir/fzf-sessions-${release_version}.tar.gz" \
  "$release_dir/SHA256SUMS" \
  --repo "$release_repo" --draft --target "$release_commit" \
  --title "$release_tag" --notes-file "$release_dir/release-notes.md"
```

- Confirm the draft targets the intended commit, both uploads are complete, and
  the archive's uploaded SHA-256 digest matches the local checksum.
- Publish once the checks are complete. A request to make the release already
  authorizes publication; no extra confirmation is needed just because a draft was used.

```sh
gh release edit "$release_tag" --repo "$release_repo" \
  --draft=false --latest --target "$release_commit"
```

- GitHub creates the tag if it does not already exist. If it exists, verify that
  it points to the intended commit; never move a public tag to make it match.

## 5. Verify and report

```sh
gh release view "$release_tag" --repo "$release_repo" \
  --json tagName,isDraft,isPrerelease,publishedAt,url,targetCommitish,assets
gh api "repos/$release_repo/commits/$release_tag" --jq .sha
```

- Check the release is public rather than a draft, and the tag resolves to `release_commit`.
- Check both downloads are uploaded and the archive digest matches `SHA256SUMS`.
- Check the release is marked Latest when publishing a normal new version.
- Give the user the release link, the main changes, and the real validation results.
- Distinguish local test results from hosted CI. Do not describe queued or skipped checks as passed.
- Leave older releases and their downloads unchanged.

## Marketplace listing

- The public repo uses the GitHub topic `herdr-plugin` for marketplace discovery.
- The index reads manifests from the default branch, not from the latest release.
  Keep the root `herdr-plugin.toml` valid and its version aligned with `VERSION`.
- Publishing a release is separate from updating the default branch. Unreleased
  code on the default branch can reach people who install the plugin without `--ref`.
- Keep the GitHub description and the README's direct plugin install command current.
- Before changing installation behavior, repeat the isolated GitHub install check
  described in [development.md](development.md#check-a-marketplace-install).
- The marketplace refreshes about every 30 minutes. Adding the topic makes the
  repo eligible; it does not prove the listing has appeared or been reviewed.
- Reference: [Herdr marketplace documentation](https://herdr.dev/tui/docs/marketplace/).
