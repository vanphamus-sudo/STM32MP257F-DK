#!/usr/bin/env python3
"""Create a signed full or file-delta router application update."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
from update_bundle import create

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('target', type=Path, help='Target application IPK')
parser.add_argument('output', type=Path)
parser.add_argument('--base', type=Path, help='Previous application IPK; omit for full package')
parser.add_argument('--private-key', type=Path, required=True)
parser.add_argument('--openssl', default='openssl')
if __name__ == '__main__':
    args = parser.parse_args()
    print(create(args.target, args.output, args.private_key, args.base, args.openssl))
