"""Read-only diagnostics; never scan transcripts or contact the Herdr server."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from . import __version__, common, dependencies, herdr, summaries


def doctor() -> int:
    print(f'fzf-sessions {__version__}')
    print(f'Platform: {platform.system()} {platform.release()}')
    print(f'Python: {platform.python_version()} ({sys.executable})')
    failed = False
    try:
        binary = dependencies.require_fzf()
        result = subprocess.run([binary, '--version'], text=True, capture_output=True, timeout=3)
        print(f'fzf: OK {common.clean(result.stdout).strip()} ({binary})')
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f'fzf: ERROR {common.clean(exc)}')
        failed = True
    for name in ('codex', 'claude'):
        print(f'{name}: {shutil.which(name) or "not on PATH (optional until resuming this agent)"}')
    for label, variable, default in [('Codex history', 'CODEX_HOME', '.codex'),
                                     ('Claude history', 'CLAUDE_CONFIG_DIR', '.claude')]:
        path = Path(os.environ.get(variable, str(Path.home() / default))).expanduser()
        state = 'readable' if path.is_dir() and os.access(path, os.R_OK | os.X_OK) else 'missing or unreadable'
        print(f'{label}: {common.clean(path)} ({state})')
    binary = os.environ.get('HERDR_BIN_PATH') or shutil.which('herdr')
    if binary:
        try:
            dependencies.require_herdr(binary)
            result = subprocess.run([binary, '--version'], text=True, capture_output=True, timeout=3)
            print(f'Herdr: {common.clean(result.stdout).strip()} ({common.clean(binary)})')
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            print(f'Herdr: unavailable ({common.clean(exc)})')
    else:
        print('Herdr: not on PATH (optional)')
    if os.environ.get('HERDR_ENV') == '1':
        try:
            herdr.herdr_context()
            print('Herdr context: present; server connection not tested')
        except RuntimeError as exc:
            print(f'Herdr context: {common.clean(exc)}')
    else:
        print('Herdr context: outside Herdr')
    if os.environ.get('FZF_SESSIONS_NO_AI') == '1':
        print('Summaries: disabled by FZF_SESSIONS_NO_AI; saved messages available')
    else:
        binary, reason = summaries.summary_backend()
        print('Summaries: local system model ready' if binary else 'Summaries: ' + common.clean(reason))
    print('Clipboard: ' + ('pbcopy available' if sys.platform == 'darwin' and shutil.which('pbcopy')
                            else 'unavailable; use --dry-run to print the resume command'))
    print('History contents and session identifiers were not read. No agents were launched.')
    return int(failed)
