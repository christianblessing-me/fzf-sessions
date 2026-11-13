#!/usr/bin/env python3
"""Install or uninstall a self-contained copy; no pip or administrator access needed."""
import argparse
import os
from pathlib import Path
import shutil
import shlex
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
MARKER = '.fzf-sessions-install'
MARKER_CONTENT = 'fzf-sessions managed installation v1\n'


def managed(path: Path) -> bool:
    try:
        return not path.is_symlink() and (path / MARKER).read_text() == MARKER_CONTENT
    except (OSError, UnicodeError):
        return False


def install(prefix: Path, uninstall: bool = False) -> None:
    target = prefix / 'share' / 'fzf-sessions'
    command = prefix / 'bin' / 'fzf-sessions'
    if target in ROOT.parents or (target == ROOT and not uninstall):
        raise RuntimeError('Installation target contains this checkout; choose another prefix')
    if target.exists() or target.is_symlink():
        if not managed(target):
            raise RuntimeError(f'Refusing to replace an unmanaged directory: {target}')
    if command.exists() or command.is_symlink():
        if not command.is_symlink() or command.resolve() != target / 'fzf-sessions':
            raise RuntimeError(f'Refusing to replace an unrelated command: {command}')
    if uninstall:
        if command.is_symlink():
            command.unlink()
        if managed(target):
            shutil.rmtree(target)
        print(f'Uninstalled from {prefix}; history and caches were preserved.')
        return
    files = ['fzf-sessions', 'VERSION', 'herdr-plugin.toml', 'README.md', 'CHANGELOG.md', 'LICENSE', 'install.py',
             'screenshot-fzf-sessions.png']
    for name in files:
        if not (ROOT / name).is_file():
            raise RuntimeError(f'Incomplete release: {name} is missing')
    target.parent.mkdir(parents=True, exist_ok=True)
    command.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.fzf-sessions-', dir=target.parent) as temporary:
        staging = Path(temporary) / 'new'
        staging.mkdir()
        for name in files:
            shutil.copy2(ROOT / name, staging / name)
        shutil.copytree(ROOT / 'fzf_sessions', staging / 'fzf_sessions',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copytree(ROOT / 'docs', staging / 'docs')
        (staging / 'fzf-sessions').chmod(0o755)
        (staging / MARKER).write_text(MARKER_CONTENT)
        backup = Path(temporary) / 'previous'
        if target.exists():
            target.rename(backup)
        try:
            staging.rename(target)
            if not command.is_symlink():
                command.symlink_to(target / 'fzf-sessions')
        except OSError:
            if target.exists():
                shutil.rmtree(target)
            if backup.exists():
                backup.rename(target)
            raise
    print(f'Installed {command}')
    print(f'Add {command.parent} to PATH if needed.')
    print('Herdr: ' + shlex.join(['herdr', 'plugin', 'link', str(target)]))
    print('Uninstall: ' + shlex.join(['python3', str(target / 'install.py'), '--prefix', str(prefix), '--uninstall']))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, default=Path.home() / '.local')
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    if sys.platform not in ('darwin', 'linux'):
        parser.error('Supported platforms: macOS and Linux (or WSL)')
    try:
        install(args.prefix.expanduser().resolve(), args.uninstall)
    except (OSError, RuntimeError) as exc:
        print(f'fzf-sessions installer: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
