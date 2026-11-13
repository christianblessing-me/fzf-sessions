"""Validate the CLI versions whose features this application uses."""
from __future__ import annotations
from functools import lru_cache
import re
import shutil
import subprocess
import sys


def fzf_install_hint(upgrade: bool = False) -> str:
    if sys.platform == 'darwin':
        return 'brew upgrade fzf' if upgrade else 'brew install fzf'
    return 'install fzf 0.74.5+ from https://github.com/junegunn/fzf/releases (distribution packages may be older)'

# Conservative, tested baseline, rather than guessing support for every old build.
MIN_FZF = (0, 74, 5)
MIN_HERDR = (0, 9, 5)


@lru_cache(maxsize=8)
def require_version(binary: str, minimum: tuple[int, int, int], label: str) -> str:
    try:
        result = subprocess.run([binary, '--version'], text=True, capture_output=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f'Cannot check {label} version: {exc}') from None
    match = re.search(r'\b(\d+)\.(\d+)\.(\d+)\b', result.stdout)
    needed = '.'.join(map(str, minimum))
    if result.returncode or not match:
        raise RuntimeError(f'Cannot determine {label} version; {needed}+ is required')
    if tuple(map(int, match.groups())) < minimum:
        hint = fzf_install_hint(upgrade=True) if label == 'fzf' else 'update Herdr to a supported version'
        raise RuntimeError(f'{label} {needed}+ is required (found {match[0]}). Update with: {hint}')
    return binary


def require_fzf() -> str:
    binary = shutil.which('fzf')
    if not binary:
        raise RuntimeError('fzf is required: ' + fzf_install_hint())
    return require_version(binary, MIN_FZF, 'fzf')


def require_herdr(binary: str) -> str:
    return require_version(binary, MIN_HERDR, 'Herdr')
