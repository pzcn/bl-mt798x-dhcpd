"""Negative tests ensure the binary envelope validator rejects corrupt fields."""

import hashlib
import lzma
import struct
import unittest

from scripts.verify_wma301_bl33_update import (
    BOARD, HEADER_SIZE, LINK_ADDRESS, MAX_BL33_RAW, verify_update_package
)


def make_pkg(raw=None, check=lzma.CHECK_CRC32):
    if raw is None:
        raw = bytearray(range(256))
        struct.pack_into("<Q", raw, 8, LINK_ADDRESS)
    raw = bytes(raw)
    xz = lzma.compress(raw, format=lzma.FORMAT_XZ, check=check, preset=0)
    header = struct.pack(
        "<8sII32sII32s32sII", b"WMABL33\x00", 1, HEADER_SIZE,
        BOARD.ljust(32, b"\x00"), len(xz), len(raw),
        hashlib.sha256(xz).digest(), hashlib.sha256(raw).digest(),
        LINK_ADDRESS, 0
    )
    assert len(header) == HEADER_SIZE
    return header + xz


def modify(package, offset, payload):
    a = bytearray(package)
    a[offset:offset + len(payload)] = payload
    return bytes(a)


class PackageValidationTests(unittest.TestCase):
    def setUp(self):
        self.pkg = make_pkg()

    def test_good_envelope_and_reference_payloads(self):
        report = verify_update_package(self.pkg)
        self.assertEqual(report["verification"], "PASS (offline format only)")
        raw = lzma.decompress(self.pkg[128:])
        verify_update_package(self.pkg, raw_reference=raw, xz_reference=self.pkg[128:])

    def test_each_header_field_rejected_when_corrupted(self):
        bad = {
            "magic": modify(self.pkg, 0x00, b"BADBL33!"),
            "version": modify(self.pkg, 0x08, struct.pack("<I", 2)),
            "header_size": modify(self.pkg, 0x0c, struct.pack("<I", 64)),
            "board": modify(self.pkg, 0x10, b"other-router"),
            "board_padding": modify(self.pkg, 0x2f, b"x"),
            "xz_size": modify(self.pkg, 0x30, struct.pack("<I", 1)),
            "raw_size": modify(self.pkg, 0x34, struct.pack("<I", 200)),
            "empty_raw": modify(self.pkg, 0x34, struct.pack("<I", 0)),
            "oversized_raw": modify(self.pkg, 0x34, struct.pack("<I", MAX_BL33_RAW+1)),
            "XZ_hash": modify(self.pkg, 0x38, b"\x00"),
            "raw_hash": modify(self.pkg, 0x58, b"\x00"),
            "link_addr": modify(self.pkg, 0x78, struct.pack("<I", 0x42000000)),
            "reserved": modify(self.pkg, 0x7c, struct.pack("<I", 1)),
            "XZ_header": modify(self.pkg, 0x80, b"\x00"),
            "trailing_payload": self.pkg + b"garbage",
            "short_header": self.pkg[:127],
        }
        for name, pkg in bad.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                verify_update_package(pkg)

    def test_crc64_stream_rejected_even_with_valid_hashes(self):
        with self.assertRaises(ValueError):
            verify_update_package(make_pkg(check=lzma.CHECK_CRC64))

    def test_embedded_link_address_rejected_even_with_valid_hashes(self):
        raw = bytearray(range(256))
        struct.pack_into("<Q", raw, 8, 0x42000000)
        with self.assertRaisesRegex(ValueError, "embedded BL33 link address"):
            verify_update_package(make_pkg(raw))

    def test_expected_input_bytes_rejected_if_different(self):
        raw = lzma.decompress(self.pkg[128:])
        with self.assertRaises(ValueError):
            verify_update_package(self.pkg, raw_reference=raw + b"x")
        with self.assertRaises(ValueError):
            verify_update_package(self.pkg, xz_reference=self.pkg[128:] + b"x")


if __name__ == "__main__":
    unittest.main()
