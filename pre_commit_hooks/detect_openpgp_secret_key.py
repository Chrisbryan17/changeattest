"""Detect binary OpenPGP secret-key packets (best-effort)."""
from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

# v4, v5, and v6 key algorithm IDs (plus historical RSA / ElGamal / DSA).
_KEY_ALGORITHMS = frozenset((1, 2, 3, 16, 17, 18, 19, 22, 25, 26, 27, 28))


def _secret_packet_at_start(header: bytes, size: int) -> bool:
    if len(header) < 8 or header[0] & 0x80 == 0:
        return False
    first = header[0]
    if first & 0x40:
        packet_type = first & 0x3f
        length_code = header[1]
        if length_code < 192:
            n = length_code
            offset = 2
        elif length_code < 224:
            if len(header) < 3:
                return False
            n = ((length_code - 192) << 8) + header[2] + 192
            offset = 3
        elif length_code == 255:
            if len(header) < 6:
                return False
            n = int.from_bytes(header[2:6], 'big')
            offset = 6
        else:
            return False  # Partial lengths are not supported in this check.
    else:
        packet_type = (first >> 2) & 0x0f
        length_type = first & 3
        offset = (2, 3, 5, 1)[length_type]
        if len(header) < offset:
            return False
        n = (size - offset if length_type == 3 else
             int.from_bytes(header[1:offset], 'big'))

    if packet_type not in (5, 7) or n < 6 or n > size - offset:
        return False
    if len(header) < offset + 6:
        return False
    return (
        header[offset] in (3, 4, 5, 6)
        and header[offset + 5] in _KEY_ALGORITHMS
    )


def check_binary_openpgp_private_keys(paths: Sequence[str]) -> int:
    found = False
    for path in paths:
        with open(path, 'rb') as f:
            header = f.read(32)
            size = os.fstat(f.fileno()).st_size
        if _secret_packet_at_start(header, size):
            print(f'{path}: possible binary OpenPGP secret key found')
            found = True
    return int(found)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('filenames', nargs='*')
    args = parser.parse_args(argv)
    return check_binary_openpgp_private_keys(args.filenames)


if __name__ == '__main__':
    raise SystemExit(main())
