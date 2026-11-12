// SPDX-License-Identifier: GPL-2.0
/*
 * Copyright (C) 2022 MediaTek Inc. All Rights Reserved.
 *
 * Author: Weijie Gao <weijie.gao@mediatek.com>
 */

#include <hang.h>
#include "bootmenu_common.h"
#include "autoboot_helper.h"
#include "mtd_helper.h"
#ifdef CONFIG_MTK_UPGRADE_OEM_FIP_BL33
#include "oem_fip_bl33.h"
#endif
#ifdef CONFIG_MTK_MAC_FROM_MTD
#include <env.h>
#include <net.h>
#include <linux/mtd/mtd.h>
#endif

#ifdef CONFIG_MTK_UPGRADE_FW_ONLY
static const struct data_part_entry mtd_parts[] = {
	{
		.name = "Firmware",
		.abbr = "fw",
		.env_name = "bootfile",
		.post_action = UPGRADE_ACTION_BOOT,
		.validate = generic_mtd_validate_fw,
		.write = generic_mtd_write_fw,
	},
#ifdef CONFIG_MTK_UPGRADE_OEM_FIP_BL33
	{
		.name = "U-Boot (BL33 in vendor FIP)",
		.abbr = "fip",
		.env_name = "bootfile.bl33",
		.post_action = UPGRADE_ACTION_REBOOT,
		.validate = oem_fip_bl33_validate,
		.write = oem_fip_bl33_write,
	},
#endif
};
#else
static const struct data_part_entry mtd_parts[] = {
	{
		.name = "ATF BL2",
		.abbr = "bl2",
		.env_name = "bootfile.bl2",
		.validate = generic_validate_bl2,
		.write = generic_mtd_write_bl2,
	},
	{
		.name = "ATF FIP",
		.abbr = "fip",
		.env_name = "bootfile.fip",
		.validate = generic_validate_fip,
		.write = generic_mtd_write_fip,
		.post_action = UPGRADE_ACTION_CUSTOM,
		//.do_post_action = generic_invalidate_env,
	},
#ifdef CONFIG_MTK_FIP_SUPPORT
	{
		.name = "BL31 of ATF FIP",
		.abbr = "bl31",
		.env_name = "bootfile.bl31",
		.validate = generic_validate_bl31,
		.write = generic_mtd_update_bl31,
		.post_action = UPGRADE_ACTION_CUSTOM,
	},
	{
		.name = "BL33 of ATF FIP",
		.abbr = "bl33",
		.env_name = "bootfile.bl33",
		.validate = generic_validate_bl33,
		.write = generic_mtd_update_bl33,
		.post_action = UPGRADE_ACTION_CUSTOM,
		//.do_post_action = generic_invalidate_env,
	},
#endif
#ifdef CONFIG_MTK_CHAINLOAD_BL
	{
		.name = "Next stage bootloader",
		.abbr = "nextbl",
		.env_name = "bootfile.nextbl",
		.validate = generic_validate_next_bl,
#ifdef CONFIG_MTK_NEXT_BL_IN_UBI
		.write = generic_ubi_write_next_bl,
#else
		.write = generic_mtd_write_next_bl,
#endif
	},
#endif
	{
		.name = "Firmware",
		.abbr = "fw",
		.env_name = "bootfile",
		.post_action = UPGRADE_ACTION_BOOT,
		.validate = generic_mtd_validate_fw,
		.write = generic_mtd_write_fw,
	},
	{
		.name = "Factory",
		.abbr = "factory",
		.env_name = "bootfile.factory",
		.write = generic_mtd_write_factory,
	},
	{
		.name = "Single image",
		.abbr = "simg",
		.env_name = "bootfile.simg",
		.validate = generic_validate_simg,
		.write = generic_mtd_write_simg,
	},
};
#endif /* CONFIG_MTK_UPGRADE_FW_ONLY */

void board_upgrade_data_parts(const struct data_part_entry **dpes, u32 *count)
{
	*dpes = mtd_parts;
	*count = ARRAY_SIZE(mtd_parts);
}

int board_boot_default(bool do_boot)
{
	return generic_mtd_boot_image(do_boot);
}

#ifdef CONFIG_MTK_CHAINLOAD_BL
int board_chainload_default(bool do_boot)
{
#ifdef CONFIG_MTK_NEXT_BL_IN_UBI
	return generic_ubi_boot_next_bl(do_boot);
#else
	return generic_mtd_boot_next_bl(do_boot);
#endif
}
#endif

#ifdef CONFIG_MTK_UPGRADE_FW_ONLY
static const struct bootmenu_entry mtd_bootmenu_entries[] = {
	{
		.desc = "Startup system (Default)",
		.cmd = "mtkboardboot"
	},
	{
		.desc = "Upgrade firmware",
		.cmd = "mtkupgrade fw"
	},
#ifdef CONFIG_MTK_UPGRADE_OEM_FIP_BL33
	{
		.desc = "Upgrade U-Boot (BL33 only, vendor BL31 kept)",
		.cmd = "mtkupgrade fip"
	},
#endif
	{
		.desc = "Load image",
		.cmd = "mtkload"
	},
#ifdef CONFIG_MTK_WEB_FAILSAFE
	{
		.desc = "Start Web failsafe",
		.cmd = "httpd"
	},
#endif
};
#else
static const struct bootmenu_entry mtd_bootmenu_entries[] = {
#ifdef CONFIG_MTK_AUTO_CHAINLOAD_BL
	{
		.desc = "Chainload next-stage bootloader (Default)",
		.cmd = "mtkchainload"
	},
	{
		.desc = "Startup system",
		.cmd = "mtkboardboot"
	},
#else
	{
		.desc = "Startup system (Default)",
		.cmd = "mtkboardboot"
	},
#endif
	{
		.desc = "Upgrade firmware",
		.cmd = "mtkupgrade fw"
	},
	{
		.desc = "Upgrade ATF BL2",
		.cmd = "mtkupgrade bl2"
	},
	{
		.desc = "Upgrade ATF FIP",
		.cmd = "mtkupgrade fip"
	},
#ifdef CONFIG_MTK_FIP_SUPPORT
	{
		.desc = "  Upgrade ATF BL31 only",
		.cmd = "mtkupgrade bl31"
	},
	{
		.desc = "  Upgrade bootloader only",
		.cmd = "mtkupgrade bl33"
	},
#endif
	{
		.desc = "Upgrade single image",
		.cmd = "mtkupgrade simg"
	},
#ifdef CONFIG_MTK_CHAINLOAD_BL
	{
		.desc = "Upgrade next-stage bootloader",
		.cmd = "mtkupgrade nextbl"
	},
#ifndef CONFIG_MTK_AUTO_CHAINLOAD_BL
	{
		.desc = "Chainload next-stage bootloader",
		.cmd = "mtkchainload"
	},
#endif
#endif
	{
		.desc = "Load image",
		.cmd = "mtkload"
	},
#ifdef CONFIG_MTK_WEB_FAILSAFE
	{
		.desc = "Start Web failsafe",
		.cmd = "httpd"
	},
#endif
	{
		.desc = "Change boot configuration",
		.cmd = "mtkbootconf"
	},
};
#endif /* CONFIG_MTK_UPGRADE_FW_ONLY */

void board_bootmenu_entries(const struct bootmenu_entry **menu, u32 *count)
{
	*menu = mtd_bootmenu_entries;
	*count = ARRAY_SIZE(mtd_bootmenu_entries);
}

void default_boot_set_defaults(void *fdt)
{
#ifdef CONFIG_MTD_VERIFY_FDT
	int ret;

	ret = mtd_verify_linux_fdt(fdt);
	if (ret) {
#ifdef CONFIG_MTD_VERIFY_FDT_WARN_ONLY
		printf("\nWarning: FDT verification failed, continue booting as requested\n\n");
#else
		hang();
#endif
	}
#endif
	mtd_boot_set_defaults(fdt);
}

#ifdef CONFIG_MTK_MAC_FROM_MTD
static void mtk_mac_from_mtd(void)
{
	const char *part = CONFIG_MTK_MAC_MTD_PART;
	const char *cur = env_get("ethaddr");
	struct mtd_info *mtd;
	u8 mac[ARP_HLEN], old[ARP_HLEN];
	size_t retlen = 0;
	int ret;

	if (env_get_yesno("mac_from_mtd") == 0)
		return;

	gen_mtd_probe_devices();
	mtd = get_mtd_device_nm(part);
	if (IS_ERR_OR_NULL(mtd)) {
		printf("MAC: partition '%s' not found\n", part);
		return;
	}
	ret = mtd_read(mtd, CONFIG_MTK_MAC_MTD_OFFSET, ARP_HLEN, &retlen, mac);
	put_mtd_device(mtd);
	if ((ret && !mtd_is_bitflip(ret)) || retlen != ARP_HLEN) {
		printf("MAC: failed to read %s+0x%x (%d)\n", part,
		       CONFIG_MTK_MAC_MTD_OFFSET, ret);
		return;
	}
	if (!is_valid_ethaddr(mac)) {
		printf("MAC: invalid address %pM in %s+0x%x\n", mac, part,
		       CONFIG_MTK_MAC_MTD_OFFSET);
		return;
	}
	if (cur && eth_env_get_enetaddr("ethaddr", old) &&
	    !memcmp(old, mac, ARP_HLEN))
		return;
	eth_env_set_enetaddr("ethaddr", mac);
	printf("MAC: %pM (from %s+0x%x)\n", mac, part, CONFIG_MTK_MAC_MTD_OFFSET);
}
#endif

int board_late_init(void)
{
#ifdef CONFIG_MTK_MAC_FROM_MTD
	mtk_mac_from_mtd();
#endif
	return 0;
}
