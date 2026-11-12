"""Static regression contract for WMA301 V2 2025 -> 2026.10 migration.

These tests touch only source text. They do not access a device or NAND.
"""
from pathlib import Path
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


class LegacyBootTests(unittest.TestCase):
    def test_saved_mtkboardboot_migrates_without_flash(self):
        self.assertIn('strstr(bootcmd, "mtkboardboot")', BOARD)
        self.assertIn('env_set("bootcmd", WMA301_BOOTCMD)', BOARD)
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

    def test_mesh_safe_menu(self):
        self.assertIn('if button mesh; then bootmenu 30; else btnchk; fi', BOARD)
        self.assertIn('Start Web failsafe=httpd', BOARD)
        self.assertIn('TFTP RAM boot (no flash write)', BOARD)
        self.assertNotIn('mtd erase', BOARD)
        self.assertNotIn('mtd write', BOARD)
        self.assertIn('CONFIG_CMD_BUTTON=y', CONFIG)
        self.assertIn('CONFIG_CMD_BOOTMENU=y', CONFIG)
        self.assertIn('bootmenu_3=Start Web failsafe=httpd', ENV)

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

    def test_deliberate_firmware_web_limit(self):
        self.assertIn('sysupgrade.itb', WEB)
        self.assertIn('sysupgrade.itb', README)
        self.assertIn('Web', README)
        self.assertIn('ubootenv', README)
        self.assertIn('ubootenv2', README)
        self.assertIn('precheck(file, "fip"', WEB)


if __name__ == '__main__':
    unittest.main()
