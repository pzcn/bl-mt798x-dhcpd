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

def patch_before(s, needle, extra):
    if s.count(needle) != 1:
        raise RuntimeError("Unsupported upstream API: " + needle)
    return s.replace(needle, extra + needle, 1)

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

    # The previous 2025.07 build may have saved an incomplete environment
    # to ubootenv/ubootenv2. UBI import reports success even without bootcmd.
    # Do NOT erase or overwrite these volumes: restore only missing runtime
    # boot variables and never call env_save() here.
    board = tree / "board/mediatek/mt7981/mt7981_rfb.c"
    board_text = board.read_text(encoding="utf-8")
    board_anchor = "\tenv_relocate();\n\treturn 0;\n"
    repair = (
        "\tenv_relocate();\n"
        "\t/* WMA301_SAFE_BOOTCMD_FALLBACK: in-memory recovery for old UBI env. */\n"
        "\tif (!env_get(\"bootcmd\") || !*env_get(\"bootcmd\")) {\n"
        "\t\tputs(\"WMA301: no bootcmd in UBI env; enabling RAM-only boot fallback\\n\");\n"
        "\t\tif (!env_get(\"loadaddr\"))\n"
        "\t\t\tenv_set(\"loadaddr\", \"0x46000000\");\n"
        "\t\tif (!env_get(\"btnchk_key\"))\n"
        "\t\t\tenv_set(\"btnchk_key\", \"reset,mesh\");\n"
        "\t\tif (!env_get(\"check_buttons\"))\n"
        "\t\t\tenv_set(\"check_buttons\", \"btnchk\");\n"
        "\t\tif (!env_get(\"boot_production\"))\n"
        "\t\t\tenv_set(\"boot_production\", \"ubi part ubi && ubi read $loadaddr fit && bootm $loadaddr\");\n"
        "\t\tif (!env_get(\"boot_recovery\"))\n"
        "\t\t\tenv_set(\"boot_recovery\", \"ubi part ubi && ubi read $loadaddr recovery && bootm $loadaddr\");\n"
        "\t\tenv_set(\"bootcmd\",\n"
        "\t\t\t\"run check_buttons ; run boot_production ; run boot_recovery ; httpd\");\n"
        "\t}\n"
        "\treturn 0;\n"
    )
    if board_text.count(board_anchor) != 1:
        raise RuntimeError("MT7981 board_late_init signature changed")
    board.write_text(board_text.replace(board_anchor, repair, 1), encoding="utf-8")
    print("Installed WMA301 bootcmd fallback (RAM only, no flash writes)")

    # Reuse the existing V4 Web design with 2026.10 resource registration.
    ui_src = HERE / "fsdata-wma301"
    ui_dst = tree / "failsafe/embedded/fsdata-wma301"
    required_ui = {"Makefile", "embed.S", "index.html", "main.js",
                   "style.css", "favicon.svg", "initramfs.html",
                   "fip.html", "bl2.html"}
    if not required_ui.issubset({p.name for p in ui_src.iterdir()}):
        raise RuntimeError("Missing WMA301 V4 UI sources")
    ui_dst.mkdir(exist_ok=True)
    for item in ui_src.iterdir():
        if item.is_file():
            (ui_dst / item.name).write_bytes(item.read_bytes())
    print("Installed WMA301 V4 Web assets:", len(list(ui_src.iterdir())))

    kpath = tree / "failsafe/Kconfig"
    config_text = kpath.read_text()
    config_text = patch_before(
        config_text, "config WEBUI_FAILSAFE_UI_BRUTALISM\n",
        'config WEBUI_FAILSAFE_UI_WMA301\n'
        '\tbool "WMA301 V4 light/dark recovery UI"\n'
        '\thelp\n'
        '\t  WMA301 V2 single-page recovery UI, based on the Toolbox styling.\n'
        '\t  This experiment disables persistent flash writes.\n\n')
    kpath.write_text(config_text)
    embedmk = tree / "failsafe/embedded/Makefile"
    embed_txt = embedmk.read_text()
    embed_txt = patch_once(
        embed_txt,
        "obj-$(CONFIG_WEBUI_FAILSAFE_UI_BRUTALISM) += fsdata-brutalism/\n",
        "obj-$(CONFIG_WEBUI_FAILSAFE_UI_WMA301) += fsdata-wma301/\n")
    embedmk.write_text(embed_txt)

    # The 2026.10 page inventory does not register favicon.svg for custom
    # styles. Register only this static SVG; do not expose theme writes.
    core_file = tree / "failsafe/core.c"
    core = core_file.read_text()
    core = patch_before(core,
        "/*\n * A registered JS URI is the name of the embedded asset",
        '#if IS_ENABLED(CONFIG_WEBUI_FAILSAFE_UI_WMA301)\n'
        'static void wma301_favicon_handler(enum httpd_uri_handler_status status,\n'
        '\t\tstruct httpd_request *request,\n'
        '\t\tstruct httpd_response *response)\n'
        '{\n'
        '\tif (status != HTTP_CB_NEW)\n'
        '\t\treturn;\n'
        '\tif (failsafe_output_file(response, "favicon.svg", "image/svg+xml"))\n'
        '\t\tnot_found_handler(status, request, response);\n'
        '}\n'
        '#endif\n\n')
    core = patch_once(core,
        '\thttpd_register_uri_handler(inst, "/style.css", &style_handler, NULL);\n',
        '#if IS_ENABLED(CONFIG_WEBUI_FAILSAFE_UI_WMA301)\n'
        '\thttpd_register_uri_handler(inst, "/favicon.svg",\n'
        '\t\t\t\t   &wma301_favicon_handler, NULL);\n'
        '#endif\n')
    core_file.write_text(core)

    # Rebooting "to failsafe" writes the boot environment in the new
    # upstream even when all advanced Web features are off. Disable it.
    upgrade_file = tree / "failsafe/modules/upgrade.c"
    upgrade = upgrade_file.read_text()
    marker = "WMA301_PREVIEW_DISABLE_PERSISTENT_FAILSAFE_REBOOT"
    start = upgrade.index("void reboot_failsafe_handler(")
    loc = upgrade.index("\tif (status == HTTP_CB_NEW) {\n", start)
    upgrade = upgrade[:loc] + (
        '\tif (status == HTTP_CB_NEW) {\n'
        '#if IS_ENABLED(CONFIG_WEBUI_FAILSAFE_UI_WMA301)\n'
        '\t\t/* ' + marker + ': prevents env_save() from this endpoint. */\n'
        '\t\tfailsafe_http_reply_text(response, 403,\n'
        '\t\t\t"WMA301 experimental: persistent failsafe reboot disabled");\n'
        '\t\treturn;\n'
        '#endif\n'
    ) + upgrade[loc + len("\tif (status == HTTP_CB_NEW) {\n"):]
    if upgrade.count(marker) != 1:
        raise RuntimeError("Cannot safely guard persistent reboot route")
    upgrade_file.write_text(upgrade)
    print("Registered V4 UI and blocked persistent reboot endpoint")

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
        "MTK_TELNETD", "NETCONSOLE", "WEBUI_FAILSAFE_I18N",
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
    ui = tree / "failsafe/embedded/fsdata-wma301"
    if not (ui / "main.js").is_file() or not (ui / "favicon.svg").is_file():
        raise RuntimeError("WMA301 V4 UI files not installed")
    if "实验版禁止写入 Flash" not in (ui / "main.js").read_text():
        raise RuntimeError("V4 frontend flash guards missing")
    if "favicon.svg" not in (tree / "failsafe/core.c").read_text():
        raise RuntimeError("V4 favicon route is missing")
    if (tree / "failsafe/modules/upgrade.c").read_text().count(
            "WMA301_PREVIEW_DISABLE_PERSISTENT_FAILSAFE_REBOOT") != 1:
        raise RuntimeError("Persistent reboot endpoint is not guarded")
    if "WEBUI_FAILSAFE_UI_WMA301" not in (tree / "failsafe/Kconfig").read_text():
        raise RuntimeError("WMA301 UI Kconfig choice is missing")
    if "fsdata-wma301/" not in (tree / "failsafe/embedded/Makefile").read_text():
        raise RuntimeError("WMA301 UI embedding rule is missing")
    board = (tree / "board/mediatek/mt7981/mt7981_rfb.c").read_text()
    if board.count("WMA301_SAFE_BOOTCMD_FALLBACK") != 1:
        raise RuntimeError("Missing RAM-only missing-bootcmd migration")
    if "env_save()" in board or "saveenv" in board:
        raise RuntimeError("Board boot migration must never save environment")
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
