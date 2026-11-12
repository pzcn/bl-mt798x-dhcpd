#!/usr/bin/env python3
"""WMABL33 v1 package encoder/strict decoder for WMA301 V2.

Wire format matches pzcn/wma301-openwrt PR #4, parse_bl33_package().
Packaging is a format test, not hardware validation or permission to flash.
"""
import argparse
import hashlib
import json
import lzma
import struct
from pathlib import Path

MAGIC = b"WMABL33\x00"
BOARD = b"tplink,wma301-v2".ljust(32, b"\0")
HEADER_SIZE = 128
VERSION = 1
LINK_ADDRESS = 0x41E00000
MAX_RAW = 0x200000
MAX_XZ = MAX_RAW + 0x10000
FIP_XZ_START = 0x23848
FIP_END = 0x3C0000
HEADER = struct.Struct("<8sII32sII32s32sII")
assert HEADER.size == HEADER_SIZE


def digest(data):
    return hashlib.sha256(data).digest()


def decode(package):
    if not HEADER_SIZE <= len(package) <= HEADER_SIZE + MAX_XZ:
        raise ValueError("WMABL33 package length out of bounds")
    (magic, version, hdr_len, board, xz_len, raw_len, xz_sha,
     raw_sha, address, reserved) = HEADER.unpack_from(package)
    if (magic != MAGIC or version != VERSION or hdr_len != HEADER_SIZE or
            board != BOARD or address != LINK_ADDRESS or reserved):
        raise ValueError("WMABL33 header mismatch")
    if (not 0 < xz_len <= MAX_XZ or not 0 < raw_len <= MAX_RAW or
            len(package) != HEADER_SIZE + xz_len):
        raise ValueError("WMABL33 length fields invalid")
    xz = package[HEADER_SIZE:]
    if not xz.startswith(bytes.fromhex("fd377a585a000001")):
        raise ValueError("XZ header is not CRC32")
    if digest(xz) != xz_sha:
        raise ValueError("XZ SHA-256 mismatch")
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
    raw = dec.decompress(xz, max_length=MAX_RAW + 1)
    if not dec.eof or dec.unused_data or dec.check != lzma.CHECK_CRC32:
        raise ValueError("XZ CRC32/EOF validation failed")
    if len(raw) != raw_len or digest(raw) != raw_sha:
        raise ValueError("Raw length/SHA-256 mismatch")
    if len(raw) < 16 or struct.unpack_from("<Q", raw, 8)[0] != LINK_ADDRESS:
        raise ValueError("Embedded 64-bit U-Boot link address mismatch")
    if FIP_XZ_START + xz_len > FIP_END:
        raise ValueError("Compressed BL33 does not fit OEM FIP reserved area")
    return {"raw": raw, "xz": xz}


def encode(raw):
    if not 16 <= len(raw) <= MAX_RAW:
        raise ValueError("Raw BL33 size out of bounds")
    if struct.unpack_from("<Q", raw, 8)[0] != LINK_ADDRESS:
        raise ValueError("Raw BL33 does not encode link address 0x41e00000")
    xz = lzma.compress(raw, format=lzma.FORMAT_XZ,
                       check=lzma.CHECK_CRC32, preset=9)
    if not 0 < len(xz) <= MAX_XZ:
        raise ValueError("Compressed BL33 too large")
    package = HEADER.pack(MAGIC, VERSION, HEADER_SIZE, BOARD,
                          len(xz), len(raw), digest(xz), digest(raw),
                          LINK_ADDRESS, 0) + xz
    parsed = decode(package)
    if parsed["raw"] != raw or parsed["xz"] != xz:
        raise ValueError("WMABL33 package round-trip failed")
    return package


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("input", type=Path, nargs="?")
    cli.add_argument("output", type=Path, nargs="?")
    cli.add_argument("--verify", type=Path,
                     help="Validate existing WMABL33 package instead of packing raw BL33")
    cli.add_argument("--audit", type=Path)
    cli.add_argument("--experimental", action="store_true")
    args = cli.parse_args()
    if args.verify:
        if args.input or args.output:
            cli.error("--verify does not take positional input/output")
        package = args.verify.read_bytes()
        parsed = decode(package)
        mode = "verify"
    else:
        if not args.input or not args.output:
            cli.error("Raw input and packaged output required")
        raw = args.input.read_bytes()
        package = encode(raw)
        parsed = decode(package)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(package)
        mode = "pack"

    report = {
        "mode": mode,
        "format": "WMABL33 v1",
        "magic": "WMABL33\\0",
        "board": BOARD.rstrip(b"\0").decode("ascii"),
        "header_size": HEADER_SIZE,
        "link_address": hex(LINK_ADDRESS),
        "xz_crc": "CRC32",
        "raw_size": len(parsed["raw"]),
        "xz_size": len(parsed["xz"]),
        "package_size": len(package),
        "raw_sha256": digest(parsed["raw"]).hex(),
        "xz_sha256": digest(parsed["xz"]).hex(),
        "package_sha256": digest(package).hex(),
        "fip_compressed_end": hex(FIP_XZ_START + len(parsed["xz"])),
        "fits_oem_fip_window": True,
        "hardware_validated": False,
        "status": "EXPERIMENTAL / NOT FOR FLASH" if args.experimental
                  else "FORMAT CHECK ONLY / NOT HARDWARE VALIDATED"
    }
    if args.audit:
        args.audit.parent.mkdir(parents=True, exist_ok=True)
        args.audit.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
