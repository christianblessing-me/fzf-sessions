"""Launch for fzf-sessions."""
from __future__ import annotations
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from . import models as models_mod


def resume_args(session: models_mod.Session) -> list[str]:
    return ["codex", "resume", session.id] if session.tool == "codex" else ["claude", "--resume", session.id]


def resume_command(session: models_mod.Session) -> str:
    return f"cd {shlex.quote(session.cwd)} && {shlex.join(resume_args(session))}"


def copy_resume_command(session: models_mod.Session) -> None:
    binary = shutil.which("pbcopy")
    if not binary:
        raise RuntimeError("Clipboard copy requires the macOS pbcopy command")
    try:
        result = subprocess.run([binary], input=resume_command(session), text=True,
                                capture_output=True, timeout=5)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Clipboard copy timed out") from None
    if result.returncode:
        raise RuntimeError("Could not copy the resume command to the clipboard")
    print("Copied resume command to clipboard.", file=sys.stderr)


def resume(session: models_mod.Session, dry_run: bool = False) -> None:
    args = resume_args(session)
    if dry_run:
        print(resume_command(session))
        return
    if not Path(session.cwd).is_dir():
        raise RuntimeError(f"Session directory no longer exists: {session.cwd}")
    binary = shutil.which(args[0])
    if not binary:
        raise RuntimeError(f"{args[0]} is not installed or is not on PATH")
    os.chdir(session.cwd)
    os.execv(binary, args)
