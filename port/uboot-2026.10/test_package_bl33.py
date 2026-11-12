"""Offline WMABL33 v1 format contract tests; never writes flash."""
import importlib.util
import lzma
import struct
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("package_bl33.py")
SPEC = importlib.util.spec_from_file_location("package_bl33", SCRIPT)
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


def make_raw():
    raw = bytearray(bytes(range(256)) * 4)
    struct.pack_into("<Q", raw, 8, P.LINK_ADDRESS)
    return bytes(raw)


class WMABL33Tests(unittest.TestCase):
    def test_roundtrip_and_header(self):
        raw = make_raw()
        package = P.encode(raw)
        self.assertEqual(package[:8], b"WMABL33\0")
        self.assertEqual(struct.unpack_from("<II", package, 8), (1, 128))
        self.assertEqual(package[16:48], P.BOARD)
        self.assertEqual(P.decode(package)["raw"], raw)
        self.assertEqual(P.HEADER.size, 128)
        self.assertEqual(package[128:136], bytes.fromhex("fd377a585a000001"))

    def test_reject_corruptions(self):
        good = P.encode(make_raw())
        variants = [
            good[:127],
            b"BadMagic" + good[8:],
            good[:8] + struct.pack("<I", 2) + good[12:],
            good[:12] + struct.pack("<I", 64) + good[16:],
            good[:16] + b"other-board".ljust(32, b"\0") + good[48:],
            good[:48] + struct.pack("<I", 1) + good[52:],
            good[:56] + bytes([good[56] ^ 1]) + good[57:],
            good[:88] + bytes([good[88] ^ 1]) + good[89:],
            good[:120] + struct.pack("<I", 0x42000000) + good[124:],
            good[:124] + struct.pack("<I", 1) + good[128:],
            good + b"junk",
            good[:-8],
        ]
        for idx, bad in enumerate(variants):
            with self.subTest(case=idx), self.assertRaises((ValueError, lzma.LZMAError)):
                P.decode(bad)

    def test_reject_crc64_with_valid_hashes(self):
        raw = make_raw()
        xz = lzma.compress(raw, format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC64)
        p = P.HEADER.pack(P.MAGIC, 1, 128, P.BOARD, len(xz), len(raw),
                          P.digest(xz), P.digest(raw), P.LINK_ADDRESS, 0) + xz
        with self.assertRaises(ValueError):
            P.decode(p)

    def test_reject_wrong_embedded_address(self):
        raw = bytearray(make_raw())
        struct.pack_into("<Q", raw, 8, 0x42000000)
        with self.assertRaises(ValueError):
            P.encode(bytes(raw))


if __name__ == "__main__":
    unittest.main()
