#!/usr/bin/env python3
"""Apply WMA301 V2 overlay to pinned U-Boot 2026.10 source."""
import argparse
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
NAME = "mt7981_tplink_wma301v2_experimental"
MARKER = "WMA301_PREVIEW_READ_ONLY_UPLOADS"

def patch_once(s, needle, extra):
    if s.count(needle) != 1:
        raise RuntimeError("Unsupported upstream API: " + needle)
    return s.replace(needle, needle + extra, 1)

def install(tree):
    for suffix, subdir in [(".dts", "arch/arm/dts"),
                           ("_defconfig", "configs"),
                           ("_env", "defenvs")]:
        dest = tree / subdir / (NAME + suffix)
        if not dest.parent.is_dir():
            raise RuntimeError("Unknown upstream source layout: " + str(dest))
        dest.write_bytes((HERE / (NAME + suffix)).read_bytes())
        print("Installed", dest.relative_to(tree))
    path = tree / "board/mediatek/common/failsafe.c"
    s = path.read_text()
    if MARKER in s:
        raise RuntimeError("Already patched")
    v = "int failsafe_validate_image(const void *data, size_t size, failsafe_fw_t fw)\n{\n"
    s = patch_once(s, v, (
        "\t/* " + MARKER + ": RAM boot only. */\n"
        "\tif (fw != FW_TYPE_INITRD)\n"
        "\t\treturn failsafe_error(-EPERM, \"WMA301 preview: flash uploads disabled\");\n"
    ))
    w = "int failsafe_write_image(const void *data, size_t size, failsafe_fw_t fw)\n{\n"
    s = patch_once(s, w, (
        "\t/* " + MARKER + ": refuse all persistent Web writes. */\n"
        "\treturn failsafe_error(-EPERM, \"WMA301 preview: flash writes disabled\");\n"
    ))
    path.write_text(s)
    assert s.count(MARKER) == 2
    print("Installed two Web upload flash guards")

def verify(tree):
    c = (tree / ".config").read_text()
    required = [
        'CONFIG_TEXT_BASE=0x41e00000',
        'CONFIG_DEFAULT_DEVICE_TREE="' + NAME + '"',
        'CONFIG_MTK_WEB_FAILSAFE=y',
        'CONFIG_WEBUI_FAILSAFE_LAYOUT_FIP=y',
        'CONFIG_CMD_BTNCHK=y',
        'CONFIG_CMD_UBI=y',
        'CONFIG_ENV_IS_IN_UBI=y',
        'CONFIG_ENV_REDUNDANT=y',
        'CONFIG_ENV_SIZE=0x1f000',
        'CONFIG_ENV_UBI_PART="ubi"',
        'CONFIG_ENV_UBI_VOLUME="ubootenv"',
        'CONFIG_ENV_UBI_VOLUME_REDUND="ubootenv2"',
        'CONFIG_ENV_DEFAULT_ENV_TEXT_FILE="defenvs/' + NAME + '_env"',
    ]
    for line in required:
        if line not in c.splitlines():
            raise RuntimeError("Missing required option: " + line)
    denied = [
        "MTK_TELNETD", "NETCONSOLE", "WEBUI_FAILSAFE_ADVANCED",
        "WEBUI_FAILSAFE_ENV", "WEBUI_FAILSAFE_UBI",
        "WEBUI_FAILSAFE_CONSOLE", "WEBUI_FAILSAFE_FLASH",
        "WEBUI_FAILSAFE_FLASH_LAYOUT", "WEBUI_FAILSAFE_SIMG",
        "WEBUI_FAILSAFE_NAND_RAW", "WEBUI_FAILSAFE_GPT",
        "WEB_FAILSAFE_ON_RAM_BOOT",
    ]
    for key in denied:
        if re.search(r"^CONFIG_" + key + r"=y$", c, re.M):
            raise RuntimeError("Unsafe option: " + key)
    s = (tree / "board/mediatek/common/failsafe.c").read_text()
    if s.count(MARKER) != 2:
        raise RuntimeError("Missing Web flash guards")
    env = (tree / "defenvs" / (NAME + "_env")).read_text()
    for word in ("mtd erase", "mtd write", "ubi write", "ubi remove",
                 "saveenv", "snand_write"):
        if word in env:
            raise RuntimeError("Dangerous boot command: " + word)
    print("WMA301 U-Boot 2026.10 static safety checks passed")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    verify(args.upstream) if args.verify else install(args.upstream)
