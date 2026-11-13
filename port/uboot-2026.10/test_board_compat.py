"""Static regression contract for WMA301 V2 2025 -> 2026.10 migration.

These tests touch only source text. They do not access a device or NAND.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent
BOARD = (ROOT / "wma301_board_compat.c").read_text()
DTS = (ROOT / "mt7981_tplink_wma301v2.dts").read_text()
CONFIG = (ROOT / "mt7981_tplink_wma301v2_defconfig").read_text()
ENV = (ROOT / "mt7981_tplink_wma301v2_env").read_text()
WEB = (ROOT / "fsdata-wma301/main.js").read_text()
README = (ROOT / "README.md").read_text()
WRITER = (ROOT / "wma301_oem_bl33.c").read_text()
APPLY = (ROOT / "apply.py").read_text()
TOOLS = (ROOT / "wma301_tools.c").read_text()
BACKUP = (ROOT / "wma301_backup.c").read_text()


class LegacyBootTests(unittest.TestCase):
    def test_saved_mtkboardboot_migrates_without_flash(self):
        self.assertIn('strstr(bootcmd, "mtkboardboot")', BOARD)
        self.assertIn('env_set("bootcmd", WMA301_BOOTCMD)', BOARD)
        self.assertIn('strstr(bootcmd, "run check_buttons")', BOARD)
        self.assertIn('#define WMA301_BOOTCMD "run boot_production ; httpd"', BOARD)
        self.assertIn('bootcmd=run boot_production ; httpd\n', ENV)
        # There is no "recovery" volume in the WMA301 UBI layout.
        self.assertIn('strstr(bootcmd, "boot_recovery")', BOARD)
        self.assertIn('env_set("boot_recovery", NULL)', BOARD)
        self.assertNotIn('boot_recovery', ENV)
        self.assertNotIn('bootcmd=run check_buttons', ENV)
        self.assertIn('wma301_board_runtime_init();', APPLY)
        self.assertNotIn('env_save(', BOARD)
        self.assertNotIn('saveenv', BOARD)
        self.assertNotIn('wma301_bl33_update_enable', BOARD)

    def test_factory_mac(self):
        self.assertIn('get_mtd_device_nm("factory_info")', BOARD)
        self.assertIn('mtd_read(mtd, 0x1c, sizeof(mac)', BOARD)
        self.assertIn('is_valid_ethaddr(mac)', BOARD)
        # eth_env_set_enetaddr() returns -EEXIST when ethaddr already exists
        self.assertNotIn('eth_env_set_enetaddr("ethaddr", mac)', BOARD)
        self.assertIn('env_set("ethaddr", str)', BOARD)
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
        self.assertIn('TFTP RAM boot (no flash write)', BOARD)
        self.assertNotIn('mtd erase', BOARD)
        self.assertNotIn('mtd write', BOARD)
        self.assertIn('CONFIG_CMD_BUTTON=y', CONFIG)
        self.assertIn('CONFIG_CMD_BOOTMENU=y', CONFIG)
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

    def test_spi_nand_clock_52mhz_and_4ma_drive(self):
        # 8 mA left ~1 page per 7000 with corrupt on-die ECC parity on the
        # ESMT SPI-NAND; 4 mA (as in the 2025 build) fixes it at 52 MHz.
        self.assertIn('spi-max-frequency = <52000000>;', DTS)
        self.assertNotIn('spi-max-frequency = <26000000>;', DTS)
        self.assertEqual(DTS.count('drive-strength = <MTK_DRIVE_4mA>;'), 2)
        self.assertNotIn('MTK_DRIVE_8mA', DTS)

    def test_single_boot_menu(self):
        self.assertIn('CONFIG_AUTOBOOT_MENU_SHOW=y', CONFIG)
        self.assertIn('bootmenu_0=Boot system=run bootcmd', ENV)
        self.assertIn('env_set("bootmenu_0", "Boot system=run bootcmd")', BOARD)
        self.assertIn('bootmenu_1=Web failsafe (http://192.168.1.1)=httpd', ENV)
        self.assertIn('net_abort_wait=0', ENV)
        self.assertIn('env_set("net_abort_wait", "0")', BOARD)
        self.assertNotRegex(ENV, r"(?m)^bootmenu_4=")

    def test_web_ui_entry_point_is_called(self):
        # Without the final boot() call the SPA stays at "正在加载…".
        self.assertTrue(WEB.rstrip().endswith("boot();"))

    def test_fip_layout_and_flash_window(self):
        self.assertIn('label = "fip"; reg = <0x20000 0x3a0000>;', DTS)
        self.assertIn('MAX_OEM_FIP_WRITABLE\t0x60000', WRITER)
        self.assertIn('stock-size FIP exceeds three blocks', WRITER)
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

    def test_web_write_policy(self):
        # UBI "fit" firmware, WMABL33 and RAM boot only; never BL2 / raw FIP.
        self.assertIn('if (fw == FW_TYPE_FW) {', APPLY)
        self.assertIn('wma301_ubi_env_guard()', APPLY)
        self.assertIn('only firmware or WMABL33 can be written', APPLY)
        self.assertIn('ubi_find_volume("ubootenv")', TOOLS)
        self.assertIn('ubi_find_volume("ubootenv2")', TOOLS)
        for name in ('failsafe_validate', 'failsafe_strict_model', 'failsafe_verify'):
            self.assertIn(f'env_set("{name}", NULL)', BOARD)
        self.assertIn('precheck(f, "firmware"', WEB)
        self.assertIn('precheck(f, "initramfs"', WEB)
        self.assertIn('precheck(file, "fip"', WEB)
        self.assertIn('写入期间请勿断电', WEB)

    def test_tools_are_read_only_except_overlay_reset(self):
        for route in ('/wma301/health', '/wma301/fitinfo', '/wma301/fitcheck', '/wma301/reset-config'):
            self.assertIn(f'"{route}"', TOOLS)
            self.assertIn(route, WEB)
        self.assertIn('strcmp(confirm->data, "RESET")', TOOLS)
        self.assertIn('"ubi remove rootfs_data"', TOOLS)
        for forbidden in ('mtd_write(', 'mtd_erase(', 'ubi remove fit', 'env_save(', 'saveenv'):
            self.assertNotIn(forbidden, TOOLS)
        self.assertIn('fit_all_image_verify(fit)', TOOLS)

    def test_reboot_to_failsafe_allowed(self):
        self.assertNotIn('WMA301_PREVIEW_DISABLE_PERSISTENT_FAILSAFE_REBOOT', APPLY)
        self.assertIn('"/reboot-failsafe"', WEB)
        self.assertIn('doBoot("failsafe")', WEB)

    def test_web_backup_and_cleanup(self):
        self.assertIn('function sha256(', WEB)
        self.assertIn('备份全部分区', WEB)
        self.assertIn('flagSet(backupKey()', WEB)
        self.assertIn('Yuzhii0718/uboot-airoha-mediatek</a>', WEB)
        self.assertNotIn('hanwckf', WEB)
        for gone in ('VIEWS.env', 'VIEWS.ubi', 'VIEWS.console', '/env/list', '/console/exec', '/ubi/remove'):
            self.assertNotIn(gone, WEB)

if __name__ == '__main__':
    unittest.main()
