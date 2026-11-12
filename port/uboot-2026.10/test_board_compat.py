"""Static regression contract for WMA301 V2 2025 -> 2026.10 migration.

These tests touch only source text. They do not access a device or NAND.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent
BOARD = (ROOT / "wma301_board_compat.c").read_text()
DTS = (ROOT / "mt7981_tplink_wma301v2_experimental.dts").read_text()
CONFIG = (ROOT / "mt7981_tplink_wma301v2_experimental_defconfig").read_text()
ENV = (ROOT / "mt7981_tplink_wma301v2_experimental_env").read_text()
WEB = (ROOT / "fsdata-wma301/main.js").read_text()
README = (ROOT / "README.md").read_text()
WRITER = (ROOT / "wma301_oem_bl33.c").read_text()
APPLY = (ROOT / "apply.py").read_text()
BACKUP = (ROOT / "wma301_backup.c").read_text()


class LegacyBootTests(unittest.TestCase):
    def test_saved_mtkboardboot_migrates_without_flash(self):
        self.assertIn('strstr(bootcmd, "mtkboardboot")', BOARD)
        self.assertIn('env_set("bootcmd", WMA301_BOOTCMD)', BOARD)
        self.assertIn('strstr(bootcmd, "run check_buttons")', BOARD)
        self.assertIn('#define WMA301_BOOTCMD "run boot_production ; run boot_recovery ; httpd"', BOARD)
        self.assertIn('bootcmd=run boot_production ; run boot_recovery ; httpd', ENV)
        self.assertNotIn('bootcmd=run check_buttons', ENV)
        self.assertIn('wma301_board_runtime_init();', APPLY)
        self.assertNotIn('env_save(', BOARD)
        self.assertNotIn('saveenv', BOARD)
        self.assertIn('env_set("wma301_bl33_update_enable", NULL)', BOARD)

    def test_factory_mac(self):
        self.assertIn('get_mtd_device_nm("factory_info")', BOARD)
        self.assertIn('mtd_read(mtd, 0x1c, sizeof(mac)', BOARD)
        self.assertIn('is_valid_ethaddr(mac)', BOARD)
        self.assertIn('eth_env_set_enetaddr("ethaddr", mac)', BOARD)
        self.assertIn('# CONFIG_NET_RANDOM_ETHADDR is not set', CONFIG)

    def test_reset_and_mesh_boot_web_without_serial(self):
        # The 2026.10 btnchk accepts an explicit Reset label.
        self.assertIn('env_set("btnchk_key", "reset,mesh")', BOARD)
        self.assertIn('btnchk_key=reset,mesh', ENV)
        self.assertNotIn('env_set("check_buttons"', BOARD)
        self.assertNotIn('WMA301_CHECK_BUTTONS', BOARD)
        self.assertNotRegex(ENV, r"(?m)^check_buttons=")
        self.assertIn('strstr(bootcmd, "run check_buttons")', BOARD)  # legacy migration only
        self.assertNotIn('if button mesh; then bootmenu', BOARD)
        self.assertNotIn('if button mesh; then bootmenu', ENV)
        self.assertNotIn('check_buttons=bootmenu', ENV)
        # The manual menu remains available via "bootmenu" in the TTL console.
        self.assertIn('Start Web failsafe=httpd', BOARD)
        self.assertIn('TFTP RAM boot (no flash write)', BOARD)
        self.assertNotIn('mtd erase', BOARD)
        self.assertNotIn('mtd write', BOARD)
        self.assertIn('CONFIG_CMD_BUTTON=y', CONFIG)
        self.assertIn('CONFIG_CMD_BOOTMENU=y', CONFIG)
        self.assertIn('bootmenu_3=Start Web failsafe=httpd', ENV)
        self.assertIn('bootmenu_default=0', ENV)
        self.assertIn('CONFIG_WEBUI_FAILSAFE_LED=y', CONFIG)
        self.assertIn('failsafe_led_idle=red:status on', ENV)
        self.assertIn('failsafe_led_ready=green:status blink 1000', ENV)

    def test_boot_compat_module_not_tied_to_ui_selection(self):
        self.assertIn('obj-y += wma301_board_compat.o', APPLY)
        self.assertIn('obj-$(CONFIG_MTK_WEB_FAILSAFE) += wma301_oem_bl33.o', APPLY)
        self.assertNotIn('obj-$(CONFIG_WEBUI_FAILSAFE_UI_WMA301) += wma301_board_compat.o', APPLY)

    def test_led_and_button_polarity(self):
        for gpio in (14, 15):
            self.assertIn(f'gpios = <&pio {gpio} GPIO_ACTIVE_HIGH>;', DTS)
        for gpio in (0, 1):
            self.assertIn(f'gpios = <&pio {gpio} GPIO_ACTIVE_LOW>;', DTS)

    def test_fip_layout_and_flash_window(self):
        self.assertIn('label = "fip"; reg = <0x20000 0x3a0000>;', DTS)
        self.assertIn('MAX_OEM_FIP_WRITABLE\t0x60000', WRITER)
        self.assertIn('stock-size FIP exceeds three blocks', WRITER)
        self.assertIn('0x20000', WEB)
        self.assertNotIn('0x200000', WEB)
        self.assertNotIn('0x200000', README)

    def test_read_only_backup_partitions_and_mac_format(self):
        allowlist = BACKUP.split('static const struct wma301_part allowed[] = {', 1)[1].split('};', 1)[0]
        rows = re.findall(r'\{\s*"([^"]+)"\s*,\s*0x([0-9a-fA-F]+)\s*,\s*0x([0-9a-fA-F]+)\s*\}', allowlist)
        actual = [(name, int(offset, 16), int(size, 16)) for name, offset, size in rows]
        expected = [
            ("bl2", 0x000000, 0x020000),
            ("fip", 0x020000, 0x3a0000),
            ("reserved", 0x3c0000, 0x040000),
            ("factory_info", 0x400000, 0x080000),
            ("art", 0x480000, 0x080000),
            ("config", 0x500000, 0x200000),
        ]
        self.assertEqual(actual, expected)
        self.assertIn('mtd_read(session->mtd', BACKUP)
        self.assertIn('WMA301_BACKUP_CHUNK   (16 * 1024)', BACKUP)
        for forbidden in ("mtd_write(", "mtd_erase(", "flash_open_target("):
            self.assertNotIn(forbidden, BACKUP)
        self.assertIn('mtd->size != part->size', BACKUP)
        self.assertIn('mtd->offset != part->offset', BACKUP)
        self.assertIn('mtd->erasesize != WMA301_ERASE_BYTES', BACKUP)
        self.assertIn('String((S.sys && S.sys.mac)', WEB)
        self.assertIn('.toUpperCase();', WEB)
        self.assertIn('reserved', README)

    def test_deliberate_firmware_web_limit(self):
        self.assertIn('sysupgrade.itb', WEB)
        self.assertIn('sysupgrade.itb', README)
        self.assertIn('Web', README)
        self.assertIn('ubootenv', README)
        self.assertIn('ubootenv2', README)
        self.assertIn('precheck(file, "fip"', WEB)


if __name__ == '__main__':
    unittest.main()
