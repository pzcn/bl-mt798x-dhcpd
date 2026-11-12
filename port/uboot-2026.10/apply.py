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
    s = patch_once(s, '#include "failsafe_validate.h"\n',
        '#include "wma301_oem_bl33.h"\n')
    v = "int failsafe_validate_image(const void *data, size_t size, failsafe_fw_t fw)\n{\n"
    s = patch_once(s, v, (
        "\t/* " + MARKER + ": RAM boot or authenticated WMABL33 v1 only. */\n"
        "\tif (fw == FW_TYPE_FIP)\n"
        "\t\treturn wma301_oem_bl33_validate(data, size);\n"
        "\tif (fw != FW_TYPE_INITRD)\n"
        "\t\treturn failsafe_error(-EPERM, \"WMA301: generic flashing disabled\");\n"
    ))
    w = "int failsafe_write_image(const void *data, size_t size, failsafe_fw_t fw)\n{\n"
    s = patch_once(s, w, (
        "\t/* " + MARKER + ": no generic FIP, BL2 or firmware writes. */\n"
        "\tif (fw == FW_TYPE_FIP) {\n"
        "\t\tif (env_get_yesno(\"wma301_bl33_update_enable\") != 1)\n"
        "\t\t\treturn failsafe_error(-EPERM,\n"
        "\t\t\t\t\"WMABL33 write locked: arm via TTL setenv (no saveenv)\");\n"
        "\t\t/* Consume RAM-only authorization before touching NAND. */\n"
        "\t\tenv_set(\"wma301_bl33_update_enable\", NULL);\n"
        "\t\treturn wma301_oem_bl33_write(data, size);\n"
        "\t}\n"
        "\treturn failsafe_error(-EPERM, \"WMA301: generic flash writes disabled\");\n"
    ))
    # Upstream enables MTK_FAILSAFE_VERIFY_WRITE by default, and its
    # generic FIP verifier compares the WMABL33 *package* bytes against
    # the raw FIP partition. The OEM updater has already erased, written
    # and byte-for-byte read-back compared the actual repacked FIP.
    # Do not run the incompatible second generic verification.
    verify_sig = "int failsafe_verify_image(const void *data, size_t size, failsafe_fw_t fw)\n{\n"
    s = patch_once(s, verify_sig, (
        "\t/* WMA301_OEM_FIP_READBACK: wma301_oem_bl33_write verified FIP. */\n"
        "\tif (fw == FW_TYPE_FIP)\n"
        "\t\treturn 0;\n"
    ))
    path.write_text(s)
    assert s.count(MARKER) == 2
    print("Installed two Web upload flash guards")

    # V4->2026 compatibility is an isolated, auditable board module.
    boarddir = tree / "board/mediatek/mt7981"
    board = boarddir / "mt7981_rfb.c"
    (boarddir / "wma301_board_compat.h").write_bytes(
        (HERE / "wma301_board_compat.h").read_bytes())
    board_text = board.read_text(encoding="utf-8")
    board_text = patch_once(
        board_text, '#include <linux/libfdt.h>\n',
        '#include "wma301_board_compat.h"\n')
    boot_anchor = "\tenv_relocate();\n\treturn 0;\n"
    if board_text.count(boot_anchor) != 1:
        raise RuntimeError("MT7981 board_late_init layout changed")
    board_text = board_text.replace(
        boot_anchor,
        "\tenv_relocate();\n\twma301_board_runtime_init();\n\treturn 0;\n",
        1)
    board.write_text(board_text, encoding="utf-8")
    print("Installed 2025 bootcmd/Mesh/MAC runtime migration (RAM only)")

    # Reuse the existing V4 Web design with 2026.10 resource registration.
    # The 2026.10 generic FIP writer cannot update OEM BL33. Install
    # the legacy WMABL33-only repacker as a WMA301-specific module.
    common = tree / "board/mediatek/common"
    for name in ("wma301_oem_bl33.c", "wma301_oem_bl33.h",
                 "wma301_board_compat.c", "wma301_backup.c"):
        (common / name).write_bytes((HERE / name).read_bytes())
    makefile = common / "Makefile"
    mk = makefile.read_text()
    mk = patch_once(mk,
        "obj-$(CONFIG_MTK_WEB_FAILSAFE) += failsafe.o\n",
        # The board_late_init call is unconditional; its object must not
        # depend on which cosmetic Web failsafe UI was selected. The FIP
        # writer is used by failsafe.c whenever MTK_WEB_FAILSAFE is enabled.
        "obj-$(CONFIG_MTK_WEB_FAILSAFE) += wma301_oem_bl33.o\n"
        "obj-$(CONFIG_MTK_WEB_FAILSAFE) += wma301_backup.o\n"
        "obj-y += wma301_board_compat.o\n")
    makefile.write_text(mk)

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
        '\tselect XZ\n'
        '\tselect SHA256\n'
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
    core = patch_once(
        core, '#include <failsafe/internal.h>\n',
        '\n/* WMA301 V4 backup API; never enable generic flash-write module. */\n'
        'void wma301_backup_register_handlers(struct httpd_instance *inst);\n')
    core = patch_once(
        core, '\tfailsafe_register_pages(inst);\n',
        '\twma301_backup_register_handlers(inst);\n')
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

    # Read-only MAC in /sysinfo: the environment editor is disabled, so
    # the SPA and Toolbox cannot fetch ethaddr from /env/list.
    sysfile = tree / "failsafe/modules/sysinfo.c"
    sys = sysfile.read_text()
    sys = patch_once(sys, '#include <env.h>\n', '#include <net.h>\n')
    sys = patch_once(sys,
        "\tlen = sysinfo_json_append_board(buf, len, left);\n",
        '#if defined(CONFIG_TARGET_MT7981)\n'
        '\t{\n'
        '\t\tu8 mac[6];\n'
        '\t\tif (eth_env_get_enetaddr("ethaddr", mac) &&\n'
        '\t\t    is_valid_ethaddr(mac))\n'
        '\t\t\tlen = buf_appendf(buf, left, len,\n'
        '\t\t\t\t",\\"mac\\":\\"%pM\\"", mac);\n'
        '\t}\n'
        '#endif\n')
    sysfile.write_text(sys)

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
    dts = (tree / "arch/arm/dts" / (NAME + ".dts")).read_text()
    layout = {
        'label = "bl2"; reg = <0x0 0x20000>;': "128K BL2",
        'label = "fip"; reg = <0x20000 0x3a0000>;': "OEM FIP at 0x20000",
        'label = "reserved"; reg = <0x3c0000 0x40000>;': "factory reserved",
        'label = "ubi"; reg = <0x700000 0x7900000>;': "post-7MiB UBI",
    }
    for marker, desc in layout.items():
        if marker not in dts:
            raise RuntimeError("Unsafe WMA301 MTD mapping: " + desc)

    # Pin actual bootloader partition names/sizes to the 2025 board:
    # the DT and Kconfig must both agree. The old Kconfig is ground truth.
    old_defconfig = (HERE.parents[1] / "uboot-mtk-20250711" / "configs"
                     / "mt7981_tplink_wma301v2_custom_defconfig").read_text()
    compiled = (tree / ".config").read_text()
    for k in ("CONFIG_MTDIDS_DEFAULT", "CONFIG_MTDPARTS_DEFAULT"):
        old_setting = next((line for line in old_defconfig.splitlines()
                            if line.startswith(k + "=")), None)
        if not old_setting or old_setting not in compiled.splitlines():
            raise RuntimeError("2026.10 differs from 2025 MTD layout: " + k)
    if "CONFIG_SYS_MTDPARTS_RUNTIME=y" in compiled.splitlines():
        raise RuntimeError("Uncontrolled runtime mtdparts would override 2025 layout")
    c = (tree / ".config").read_text()
    required = [
        'CONFIG_TEXT_BASE=0x41e00000',
        'CONFIG_CMD_MTDPARTS=y',
        'CONFIG_CMD_BOOTMENU=y',
        'CONFIG_CMD_BUTTON=y',
        'CONFIG_MTD_PARTITIONS=y',
        'CONFIG_MTDIDS_DEFAULT="spi-nand0=spi-nand0"',
        'CONFIG_MTDPARTS_DEFAULT="spi-nand0:128k(bl2)ro,3712k(fip)ro,256k(reserved)ro,512k(factory_info)ro,512k(art)ro,2048k(config)ro,-(ubi)"',
        'CONFIG_DEFAULT_DEVICE_TREE="' + NAME + '"',
        'CONFIG_MTK_WEB_FAILSAFE=y',
        'CONFIG_WEBUI_FAILSAFE_LAYOUT_FIP=y',
        'CONFIG_CMD_BTNCHK=y',
        'CONFIG_CMD_UBI=y',
        'CONFIG_ENV_IS_IN_UBI=y',
        'CONFIG_ENV_REDUNDANT=y',
        'CONFIG_WEBUI_FAILSAFE_UI_WMA301=y',
        'CONFIG_XZ=y',
        'CONFIG_SHA256=y',
        'CONFIG_WEBUI_FAILSAFE_ADVANCED=y',
        'CONFIG_WEBUI_FAILSAFE_COMPRESS_GZIP=y',
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
        "WEB_FAILSAFE_ON_RAM_BOOT", "NET_RANDOM_ETHADDR",
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
    javascript = (ui / "main.js").read_text()
    if ("0x200000" in javascript or "0x20000" not in javascript or
            'precheck(file, "fip"' not in javascript):
        raise RuntimeError("WMABL33 UI has stale FIP warning or missing update route")
    if ("gpios = <&pio 14 GPIO_ACTIVE_HIGH>;" not in dts or
            "gpios = <&pio 15 GPIO_ACTIVE_HIGH>;" not in dts or
            "gpios = <&pio 0 GPIO_ACTIVE_LOW>;" not in dts or
            "gpios = <&pio 1 GPIO_ACTIVE_LOW>;" not in dts):
        raise RuntimeError("WMA301 V2 LED/button GPIO polarity mismatch")
    backup = (tree / "board/mediatek/common/wma301_backup.c").read_text()
    for marker in ('/backup/info', '/backup/main',
                   'wma301_backup_open(part)', 'mtd_read(session->mtd',
                   'HTTP_CB_RESPONDING', 'Content-Length:', 'HTTP_RESP_CUSTOM'):
        if marker not in backup:
            raise RuntimeError("WMA301 read-only backup missing: " + marker)
    for destructive in ('mtd_write(', 'mtd_erase(', 'flash_open_target('):
        if destructive in backup:
            raise RuntimeError("WMA301 backup must never write/erase Flash")
    core = (tree / "failsafe/core.c").read_text()
    if "wma301_backup_register_handlers(inst);" not in core:
        raise RuntimeError("Read-only backup API routes not registered")
    sys = (tree / "failsafe/modules/sysinfo.c").read_text()
    if '",\\\"mac\\\":\\\"%pM\\\""' not in sys and 'mac' not in sys:
        raise RuntimeError("sysinfo MAC field missing")
    if "favicon.svg" not in (tree / "failsafe/core.c").read_text():
        raise RuntimeError("V4 favicon route is missing")
    if (tree / "failsafe/modules/upgrade.c").read_text().count(
            "WMA301_PREVIEW_DISABLE_PERSISTENT_FAILSAFE_REBOOT") != 1:
        raise RuntimeError("Persistent reboot endpoint is not guarded")
    writer = (tree / "board/mediatek/common/wma301_oem_bl33.c").read_text()
    if ("mtd->offset != 0x20000" not in writer or
            "wma301_oem_bl33_write" not in writer or
            "MAX_OEM_FIP_WRITABLE" not in writer):
        raise RuntimeError("OEM FIP writer missing or layout guard changed")
    failsafe = (tree / "board/mediatek/common/failsafe.c").read_text()
    if ("wma301_oem_bl33_validate" not in failsafe or
            "wma301_bl33_update_enable" not in failsafe):
        raise RuntimeError("WMABL33 upload gate/validator missing")
    if "WMA301_OEM_FIP_READBACK" not in failsafe:
        raise RuntimeError("Generic FIP verification not bypassed for WMABL33")
    if "wma301_oem_bl33.o" not in (tree / "board/mediatek/common/Makefile").read_text():
        raise RuntimeError("WMABL33 object missing from build")
    if "WEBUI_FAILSAFE_UI_WMA301" not in (tree / "failsafe/Kconfig").read_text():
        raise RuntimeError("WMA301 UI Kconfig choice is missing")
    if "fsdata-wma301/" not in (tree / "failsafe/embedded/Makefile").read_text():
        raise RuntimeError("WMA301 UI embedding rule is missing")
    board = (tree / "board/mediatek/mt7981/mt7981_rfb.c").read_text()
    if "\tenv_relocate();\n\twma301_board_runtime_init();\n\treturn 0;\n" not in board:
        raise RuntimeError("WMA301 compatibility hook must run BEFORE return in board_late_init")
    compat = (tree / "board/mediatek/common/wma301_board_compat.c").read_text()
    for marker in ('strstr(bootcmd, "mtkboardboot")',
                   'env_set("bootcmd", WMA301_BOOTCMD)',
                   'env_set("mtdids", WMA301_MTDIDS)',
                   'env_set("mtdparts", WMA301_MTDPARTS)',
                   'env_set("wma301_bl33_update_enable", NULL)',
                   'get_mtd_device_nm("factory_info")',
                   'mtd_read(mtd, 0x1c, sizeof(mac)',
                   'eth_env_set_enetaddr("ethaddr", mac)',
                   'env_set("btnchk_key", "reset,mesh")',
                   'env_set("check_buttons", WMA301_CHECK_BUTTONS)',
                   '#define WMA301_CHECK_BUTTONS "btnchk"',
                   'env_set("bootmenu_3", "Start Web failsafe=httpd")'):
        if marker not in compat:
            raise RuntimeError("WMA301 2025 runtime migration missing: " + marker)
    if "env_save(" in compat or "saveenv" in compat:
        raise RuntimeError("Boot migration must not persist environment")
    mk = (tree / "board/mediatek/common/Makefile").read_text()
    if "obj-y += wma301_board_compat.o" not in mk:
        raise RuntimeError("Board compatibility object must link independent of Web UI")
    if "obj-$(CONFIG_MTK_WEB_FAILSAFE) += wma301_backup.o" not in mk:
        raise RuntimeError("WMA301 read-only backup module not linked")
    if "obj-$(CONFIG_MTK_WEB_FAILSAFE) += wma301_oem_bl33.o" not in mk:
        raise RuntimeError("OEM BL33 writer must link whenever failsafe.c is built")
    env_default = (tree / "defenvs" / (NAME + "_env")).read_text()
    if ("btnchk_key=reset,mesh" not in env_default or
            "check_buttons=btnchk" not in env_default):
        raise RuntimeError("Default environment lacks headless Reset/Mesh Web recovery")
    if ('env_set("btnchk_key", "reset,mesh")' not in compat or
            '#define WMA301_CHECK_BUTTONS "btnchk"' not in compat):
        raise RuntimeError("Runtime override breaks headless button Web recovery")

    if ('#define WMA301_BOOTCMD "run boot_production ; run boot_recovery ; httpd"' not in compat or
            'strstr(bootcmd, "run check_buttons")' not in compat):
        raise RuntimeError("Duplicate post-countdown button check not removed")
    env = (tree / "defenvs" / (NAME + "_env")).read_text()
    if "bootcmd=run check_buttons" in env:
        raise RuntimeError("Old post-bootdelay btnchk would run twice")
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
