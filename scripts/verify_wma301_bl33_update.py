#!/usr/bin/env python3
"""Independently parse a WMABL33 update file as the U-Boot check_pkg() does.

Does not generate a package, touch a router, or modify flash. Deliberately
uses byte offsets from oem_fip_bl33.c rather than the writer's pack format.
"""

import argparse
import hashlib
import json
import lzma
import struct
from pathlib import Path

MAGIC = b"WMABL33\x00"
HEADER_SIZE = 128
BOARD = b"tplink,wma301-v2"
LINK_ADDRESS = 0x41E00000
MAX_BL33_RAW = 0x200000
XZ_CRC32_HEADER = bytes.fromhex("fd377a585a000001")


def require(condition, explanation):
    if not condition:
        raise ValueError(explanation)


def sha256(data):
    return hashlib.sha256(data).digest()


def verify_update_package(package, *, raw_reference=None, xz_reference=None):
    """Check the actual binary envelope; return independently parsed metadata."""
    require(len(package) >= HEADER_SIZE, "package shorter than 128-byte header")
    require(package[0x00:0x08] == MAGIC, "magic mismatch")

    version = struct.unpack_from("<I", package, 0x08)[0]
    header_size = struct.unpack_from("<I", package, 0x0C)[0]
    require(version == 1, "unsupported package version")
    require(header_size == HEADER_SIZE, "header_size mismatch")

    board_field = package[0x10:0x30]
    require(board_field == BOARD.ljust(32, b"\x00"),
            "board ID or NUL padding mismatch")

    xz_size = struct.unpack_from("<I", package, 0x30)[0]
    raw_size = struct.unpack_from("<I", package, 0x34)[0]
    xz_hash = package[0x38:0x58]
    raw_hash = package[0x58:0x78]
    link_address = struct.unpack_from("<I", package, 0x78)[0]
    reserved = struct.unpack_from("<I", package, 0x7C)[0]

    require(reserved == 0, "reserved field must be zero")
    require(link_address == LINK_ADDRESS, "header BL33 link address mismatch")
    require(0 < raw_size <= MAX_BL33_RAW, "raw_size outside 1..2 MiB")
    require(HEADER_SIZE + xz_size == len(package),
            "compressed size does not match full package size")

    xz = package[HEADER_SIZE:]
    require(xz[:8] == XZ_CRC32_HEADER, "XZ stream header is not CRC32 XZ")
    require(sha256(xz) == xz_hash, "XZ SHA-256 mismatch")

    dec = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
    try:
        raw = dec.decompress(xz, max_length=MAX_BL33_RAW + 1)
    except lzma.LZMAError as exc:
        raise ValueError("XZ decoding failed") from exc
    require(dec.check == lzma.CHECK_CRC32, "XZ check type is not CRC32")
    require(dec.eof and not dec.unused_data, "XZ stream incomplete or contains trailing data")
    require(0 < len(raw) <= MAX_BL33_RAW, "decoded BL33 exceeds 2 MiB")
    require(len(raw) == raw_size, "decoded raw_size mismatch")
    require(sha256(raw) == raw_hash, "raw BL33 SHA-256 mismatch")
    require(len(raw) >= 16, "raw BL33 too short for embedded link address")
    embedded_link = struct.unpack_from("<Q", raw, 0x08)[0]
    require(embedded_link == LINK_ADDRESS, "embedded BL33 link address mismatch")

    if raw_reference is not None:
        require(raw == raw_reference, "package BL33 differs from freshly built u-boot.bin")
    if xz_reference is not None:
        require(xz == xz_reference, "package XZ differs from freshly generated BL33.xz")

    return {
        "verification": "PASS (offline format only)",
        "board": BOARD.decode("ascii"),
        "version": version,
        "header_size": header_size,
        "xz_size": xz_size,
        "raw_size": raw_size,
        "xz_sha256": xz_hash.hex(),
        "raw_sha256": raw_hash.hex(),
        "link_address": hex(link_address),
        "embedded_link_address": hex(embedded_link),
        "reserved": reserved,
        "xz_check": "CRC32",
        "raw_limit_bytes": MAX_BL33_RAW,
        "hardware_tested": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--raw", type=Path, help="Compare with build's u-boot.bin")
    parser.add_argument("--xz", type=Path, help="Compare with build's BL33.xz")
    parser.add_argument("--report", type=Path, help="Write JSON audit")
    args = parser.parse_args()
    report = verify_update_package(
        args.package.read_bytes(),
        raw_reference=args.raw.read_bytes() if args.raw else None,
        xz_reference=args.xz.read_bytes() if args.xz else None,
    )
    output = json.dumps(report, indent=2) + "\n"
    print(output)
    if args.report:
        args.report.write_text(output)


if __name__ == "__main__":
    main()
