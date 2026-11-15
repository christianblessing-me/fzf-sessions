"""Herdr for fzf-sessions."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
from . import common as common_mod
from . import dependencies as dependencies_mod
from . import launch as launch_mod
from . import models as models_mod


HERDR_PLUGIN_ID = "fzf-sessions"


def herdr_context() -> tuple[str, str]:
    if os.environ.get("HERDR_ENV") != "1":
        raise RuntimeError("Run the Herdr integration inside a Herdr pane")
    workspace = os.environ.get("FZF_SESSIONS_HERDR_WORKSPACE") or os.environ.get("HERDR_WORKSPACE_ID")
    if not workspace:
        # A floating popup has no pane ID; some Herdr launch paths expose the
        # underlying workspace only through the plugin invocation context.
        try:
            context = json.loads(os.environ.get("HERDR_PLUGIN_CONTEXT_JSON", "{}"))
            workspace = context.get("workspace_id") if isinstance(context, dict) else None
        except ValueError:
            workspace = None
    if not isinstance(workspace, str) or not workspace:
        raise RuntimeError("Herdr did not provide the calling workspace; refusing to use the focused workspace")
    binary = os.environ.get("HERDR_BIN_PATH") or shutil.which("herdr")
    if not binary:
        raise RuntimeError("Herdr is not installed or is not on PATH")
    return binary, workspace


def herdr_call(binary: str, args: list[str], timeout: int = 15) -> dict:
    try:
        result = subprocess.run([binary, *args], text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Herdr request timed out. Check the workspace before retrying; it may have succeeded.") from None
    if result.returncode:
        detail = common_mod.clean(result.stderr.strip())[:600]
        raise RuntimeError(f"Herdr {' '.join(args[:2])} failed: {detail or 'unknown error'}")
    # These CLI commands can acknowledge success with exit status 0 alone.
    # Commands that return identities or inventory still require structured data.
    if not result.stdout.strip() and tuple(args[:2]) in {
            ("pane", "run"), ("workspace", "focus"), ("agent", "focus")}:
        return {}
    try:
        response = json.loads(result.stdout)
        if not isinstance(response, dict) or not isinstance(response.get("result"), dict):
            raise ValueError
        return response["result"]
    except (ValueError, TypeError):
        raise RuntimeError("Herdr returned an unexpected response. Check the workspace before retrying.") from None


def annotate_herdr_sessions(sessions: list[models_mod.Session]) -> str:
    """Identify live sessions throughout this server, including unfocused workspaces."""
    if os.environ.get("HERDR_ENV") != "1":
        return ""
    for session in sessions:
        session.herdr_locations = []
        session.herdr_checked = False
    try:
        binary, _ = herdr_context()
        response = herdr_call(binary, ["api", "snapshot"], timeout=3)
        snapshot = response.get("snapshot")
        if not isinstance(snapshot, dict) or any(not isinstance(snapshot.get(k), list)
                                                 for k in ("agents", "panes", "tabs", "workspaces")):
            raise RuntimeError("Missing snapshot fields")
    except (OSError, RuntimeError):
        return "Herdr status unavailable"
    workspaces = {w["workspace_id"]: w.get("label") or w["workspace_id"]
                  for w in snapshot["workspaces"] if isinstance(w, dict) and isinstance(w.get("workspace_id"), str) and w["workspace_id"]}
    tabs = {t["tab_id"]: t.get("label") or t["tab_id"]
            for t in snapshot["tabs"] if isinstance(t, dict) and isinstance(t.get("tab_id"), str) and t["tab_id"]}
    by_id = {(session.tool, session.id.casefold()): session for session in sessions}
    by_path = {(session.tool, str(Path(session.transcript).expanduser().resolve())): session
               for session in sessions if session.transcript}
    seen = set()
    for agent in [*snapshot["agents"], *snapshot["panes"]]:
        if not isinstance(agent, dict) or not agent.get("agent"):
            continue  # Ignore saved session references on panes now running a shell.
        ref = agent.get("agent_session")
        if not isinstance(ref, dict) or not isinstance(ref.get("value"), str):
            continue
        tool = str(ref.get("agent", "")).casefold()
        current_tool = str(agent["agent"]).casefold()
        if tool not in ("codex", "claude") or current_tool != tool:
            continue
        if ref.get("kind") == "id":
            session = by_id.get((tool, ref["value"].casefold()))
        elif ref.get("kind") == "path":
            try:
                session = by_path.get((tool, str(Path(ref["value"]).expanduser().resolve())))
            except (OSError, ValueError):
                continue
        else:
            continue
        pane, tab, workspace = (agent.get(k) for k in ("pane_id", "tab_id", "workspace_id"))
        if not session or not all(isinstance(value, str) and value for value in (pane, tab, workspace)):
            continue
        if (tool, session.id, pane) in seen:
            continue
        seen.add((tool, session.id, pane))
        session.herdr_locations.append({"pane_id": pane, "tab_id": tab, "workspace_id": workspace,
            "workspace": str(workspaces.get(workspace, workspace)), "tab": str(tabs.get(tab, tab)),
            "status": str(agent.get("agent_status") or "unknown")})
    for session in sessions:
        session.herdr_checked = True
    return f"{sum(bool(session.herdr_locations) for session in sessions)} detected open in Herdr"


def herdr_location_label(session: models_mod.Session) -> str:
    if not session.herdr_locations:
        return "—" if session.herdr_checked else "?"
    return "●"


def open_herdr_picker() -> None:
    binary, workspace = herdr_context()
    dependencies_mod.require_herdr(binary)
    # Herdr overlays and popups always target the active pane. Explicit workspace/pane
    # targeting is only valid for other placements and is rejected here.
    herdr_call(binary, ["plugin", "pane", "open", "--plugin", HERDR_PLUGIN_ID,
                       "--entrypoint", "picker", "--env",
                       f"FZF_SESSIONS_HERDR_WORKSPACE={workspace}", "--focus"])


def herdr_session_matches(session: models_mod.Session, agent: dict) -> bool:
    ref = agent.get("agent_session")
    if not agent.get("agent") or not isinstance(ref, dict) or not isinstance(ref.get("value"), str):
        return False
    if str(agent["agent"]).casefold() != session.tool or str(ref.get("agent", "")).casefold() != session.tool:
        return False
    if ref.get("kind") == "id":
        return ref["value"].casefold() == session.id.casefold()
    if ref.get("kind") == "path" and session.transcript:
        try:
            return Path(ref["value"]).expanduser().resolve() == Path(session.transcript).expanduser().resolve()
        except (OSError, ValueError):
            return False
    return False


def resume_herdr(session: models_mod.Session, dry_run: bool = False) -> None:
    binary, workspace = herdr_context()
    dependencies_mod.require_herdr(binary)
    if dry_run:
        if session.herdr_locations:
            location = next((loc for loc in session.herdr_locations if loc["workspace_id"] == workspace),
                            session.herdr_locations[0])
            print(f"Herdr: focus existing pane {location['pane_id']} (live identity checked on Enter)")
        else:
            print("Herdr: focus if already open, otherwise resume in a new workspace")
            print(launch_mod.resume_command(session))
        return
    # Refresh only the compact agent inventory, not the full layout snapshot.
    # This also catches sessions opened since the picker appeared or before its
    # background status lookup completed.
    agents = herdr_call(binary, ["agent", "list"], timeout=3).get("agents")
    if not isinstance(agents, list):
        raise RuntimeError("Herdr did not return its live agent list; no additional session was opened")
    matches = [agent for agent in agents if isinstance(agent, dict) and herdr_session_matches(session, agent)
               and isinstance(agent.get("pane_id"), str) and agent["pane_id"]]
    if matches:
        target = next((agent for agent in matches if agent.get("workspace_id") == workspace), matches[0])
        try:
            # agent focus reveals the workspace, tab and exact pane together.
            herdr_call(binary, ["agent", "focus", target["pane_id"]])
        except RuntimeError as exc:
            raise RuntimeError(f"Could not focus the existing session; no additional session was opened. {exc}") from None
        return
    if session.herdr_locations:
        raise RuntimeError("This session was marked open but is no longer reported by Herdr. "
                           "Reopen the picker to refresh it before resuming.")
    if not Path(session.cwd).is_dir():
        raise RuntimeError(f"Session directory no longer exists: {session.cwd}")
    if not shutil.which(launch_mod.resume_args(session)[0]):
        raise RuntimeError(f"{session.tool} is not installed or is not on PATH")
    title = " ".join(common_mod.clean(session.title).split())
    label = f"{session.tool} · {title[:49]}"
    created = herdr_call(binary, ["workspace", "create", "--cwd", session.cwd,
                                  "--label", label, "--no-focus"])
    try:
        pane = created["root_pane"]["pane_id"]
        new_workspace = created["workspace"]["workspace_id"]
        if not all(isinstance(value, str) and value for value in (pane, new_workspace)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("Herdr created a workspace but did not return its IDs. Check Herdr before retrying.") from None
    try:
        # Only run in the new pane returned by Herdr, never in an existing agent's pane.
        # The explicit cd also protects against shell startup hooks changing directory.
        herdr_call(binary, ["pane", "run", pane, launch_mod.resume_command(session)])
    except RuntimeError as exc:
        raise RuntimeError(f"Created workspace {new_workspace}, but resume could not be confirmed. "
                           f"Inspect that workspace before retrying. {exc}") from None
    try:
        herdr_call(binary, ["workspace", "focus", new_workspace])
    except RuntimeError as exc:
        raise RuntimeError(f"Resume was submitted in workspace {new_workspace}, but focusing it failed. {exc}") from None
