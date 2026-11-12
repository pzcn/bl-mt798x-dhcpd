// SPDX-License-Identifier: GPL-2.0
/*
 * WMA301 V2 compatibility for U-Boot 2026.10.
 * RAM-only 2025 environment migration, safe Mesh bootmenu and factory MAC.
 */
#include <env.h>
#include <net.h>
#include <mtd.h>
#include <linux/err.h>
#include <linux/mtd/mtd.h>
#include <linux/string.h>
#include <stdio.h>
#include "../mt7981/wma301_board_compat.h"

#define WMA301_MTDIDS "spi-nand0=spi-nand0"
#define WMA301_MTDPARTS "spi-nand0:128k(bl2)ro,3712k(fip)ro,256k(reserved)ro,512k(factory_info)ro,512k(art)ro,2048k(config)ro,-(ubi)"
#define WMA301_BOOTCMD "run boot_production ; run boot_recovery ; httpd"

static void wma301_repair_2025_env(void)
{
	const char *bootcmd = env_get("bootcmd");
	const char *script;
	char var[24];
	unsigned int i;

	/* 2025 saved bootcmd=mtkboardboot is not a command in 2026.10. */
	if (!bootcmd || !*bootcmd || strstr(bootcmd, "mtkboardboot") ||
	    strstr(bootcmd, "run check_buttons")) {
		puts("WMA301: replacing legacy mtkboardboot in RAM\n");
		env_set("bootcmd", WMA301_BOOTCMD);
	}
	if (!env_get("loadaddr"))
		env_set("loadaddr", "0x46000000");
	if (!env_get("ipaddr"))
		env_set("ipaddr", "192.168.1.1");
	if (!env_get("netmask"))
		env_set("netmask", "255.255.255.0");
	if (!env_get("serverip"))
		env_set("serverip", "192.168.1.2");
	if (!env_get("bootfile"))
		env_set("bootfile", "wma301-initramfs-recovery.itb");
	script = env_get("boot_production");
	if (!script || !*script || strstr(script, "mtkboardboot"))
		env_set("boot_production",
			"ubi part ubi && ubi read $loadaddr fit && bootm $loadaddr");
	script = env_get("boot_recovery");
	if (!script || !*script || strstr(script, "mtkboardboot"))
		env_set("boot_recovery",
			"ubi part ubi && ubi read $loadaddr recovery && bootm $loadaddr");
	script = env_get("boot_tftp");
	if (!script || !*script || strstr(script, "mtkboardboot"))
		env_set("boot_tftp",
			"tftpboot $loadaddr $bootfile && bootm $loadaddr");

	/*
	 * Upstream common/main.c already executes btnchk BEFORE the
	 * bootdelay_process() countdown. Do not duplicate it in bootcmd or
	 * preboot. The 2026.10 btnchk excludes Reset only from its default list;
	 * explicitly configured "reset,mesh" checks both labels.
	 * Holding either for four seconds starts HTTP failsafe, even with
	 * no serial cable. Upstream Reset may also select default env.
	 */
	env_set("btnchk_key", "reset,mesh");
	
	/* Manual serial bootmenu only; never divert button recovery into a menu. */
	env_set("bootmenu_default", "0");
	env_set("bootmenu_delay", "30");
	env_set("bootmenu_0", "Boot installed FIT from UBI=run boot_production");
	env_set("bootmenu_1", "Boot recovery FIT from UBI=run boot_recovery");
	env_set("bootmenu_2", "TFTP RAM boot (no flash write)=run boot_tftp");
	env_set("bootmenu_3", "Start Web failsafe=httpd");
	env_set("bootmenu_4", "Reboot=reset");
	for (i = 5; i < 20; i++) {
		snprintf(var, sizeof(var), "bootmenu_%u", i);
		env_set(var, NULL);
	}
}

static void wma301_mac_from_mtd(void)
{
	struct mtd_info *mtd;
	u8 mac[6], current[6];
	char str[ARP_HLEN_ASCII + 1];
	size_t len = 0;
	int ret;

	if (env_get_yesno("mac_from_mtd") == 0)
		return;

	mtd_probe_devices();
	mtd = get_mtd_device_nm("factory_info");
	if (IS_ERR_OR_NULL(mtd)) {
		puts("WMA301: factory_info not found, retaining existing MAC\n");
		return;
	}
	if (mtd->size < 0x1c + sizeof(mac)) {
		put_mtd_device(mtd);
		puts("WMA301: factory_info unexpectedly short\n");
		return;
	}
	ret = mtd_read(mtd, 0x1c, sizeof(mac), &len, mac);
	put_mtd_device(mtd);
	if ((ret && !mtd_is_bitflip(ret)) || len != sizeof(mac) ||
	    !is_valid_ethaddr(mac)) {
		puts("WMA301: factory MAC read/validation failed\n");
		return;
	}
	if (eth_env_get_enetaddr("ethaddr", current) &&
	    !memcmp(current, mac, sizeof(mac)))
		return;
	/*
	 * eth_env_set_enetaddr() refuses to replace an existing ethaddr
	 * (-EEXIST), e.g. the random MAC saved by the 2025 build. Use
	 * env_set() directly; ethaddr access is "any" (ENV_OVERWRITE).
	 */
	snprintf(str, sizeof(str), "%pM", mac);
	ret = env_set("ethaddr", str);
	if (ret)
		printf("WMA301: failed to set factory MAC %s (%d)\n", str, ret);
	else
		printf("WMA301: MAC %s from factory_info+0x1c (RAM only)\n", str);
}

void wma301_board_runtime_init(void)
{
	/* Align the active MTD map with 2025 despite any saved UBI variables. */
	env_set("mtdids", WMA301_MTDIDS);
	env_set("mtdparts", WMA301_MTDPARTS);
	/* Never honor or persist a previously saved flash-write arm. */
	env_set("wma301_bl33_update_enable", NULL);
	wma301_repair_2025_env();
	wma301_mac_from_mtd();
}
