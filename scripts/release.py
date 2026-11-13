#!/usr/bin/env python3
"""Check release metadata, or synchronize the plugin manifest with VERSION."""
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sync', action='store_true')
    args = parser.parse_args()
    version = (ROOT / 'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', version):
        parser.error('VERSION must contain a semantic version')
    manifest = ROOT / 'herdr-plugin.toml'
    text = manifest.read_text()
    updated, count = re.subn(r'(?m)^version = "[^"]+"$', f'version = "{version}"', text)
    if count != 1:
        parser.error('Expected exactly one plugin version')
    if args.sync:
        manifest.write_text(updated)
    elif text != updated:
        parser.error('Plugin version differs from VERSION; run python3 scripts/release.py --sync')
    if f'## {version}' not in (ROOT / 'CHANGELOG.md').read_text():
        parser.error('CHANGELOG.md needs an entry for this version')
    if not (ROOT / 'LICENSE').is_file():
        parser.error('LICENSE is missing')
    print(f'Release metadata consistent: {version}')


if __name__ == '__main__':
    main()
