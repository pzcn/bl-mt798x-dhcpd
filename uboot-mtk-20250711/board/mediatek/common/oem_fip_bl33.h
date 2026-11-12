/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Replace only the BL33 (U-Boot) inside a vendor FIP, keeping the vendor
 * BL31 byte-for-byte. Used by boards that must keep a vendor BL2/BL31
 * (e.g. TP-Link WMA301 V2.0). Update package format: see oem_fip_bl33.c.
 */
#ifndef _OEM_FIP_BL33_H_
#define _OEM_FIP_BL33_H_

#include "upgrade_helper.h"

int oem_fip_bl33_validate(void *priv, const struct data_part_entry *dpe,
			  const void *data, size_t size);
int oem_fip_bl33_write(void *priv, const struct data_part_entry *dpe,
		       const void *data, size_t size);

#endif /* _OEM_FIP_BL33_H_ */
