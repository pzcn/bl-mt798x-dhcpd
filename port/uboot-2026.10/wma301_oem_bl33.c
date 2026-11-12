// SPDX-License-Identifier: GPL-2.0
/*
 * Replace only the BL33 inside a vendor (OEM) FIP, keeping vendor BL31.
 *
 * Update package ("BL33 update", produced by CI), little endian:
 *   0x00  char  magic[8]      "WMABL33\0"
 *   0x08  u32   version       1
 *   0x0c  u32   header_size   128
 *   0x10  char  board[32]     WMA301_OEM_BL33_BOARD, NUL padded
 *   0x30  u32   xz_size
 *   0x34  u32   raw_size
 *   0x38  u8    xz_sha256[32]
 *   0x58  u8    raw_sha256[32]
 *   0x78  u32   link_addr     CONFIG_TEXT_BASE (low 32 bits)
 *   0x7c  u32   reserved      0
 *   0x80  xz stream (CRC32 check) of the raw u-boot.bin
 *
 * The FIP on flash must contain exactly two entries (BL31, BL33). The new
 * FIP is: original TOC header, BL31 (unchanged bytes), new BL33 xz.
 * The "fip" partition is normally read-only; it is written through its
 * parent (master) MTD device. Every written byte is read back and compared;
 * on failure the original FIP is written back and verified.
 */

#include <errno.h>
#include <malloc.h>
#include <linux/kernel.h>
#include <linux/mtd/mtd.h>
#include <linux/string.h>
#include <linux/sizes.h>
#include <u-boot/sha256.h>
#include <u-boot/uuid.h>
#include <mtd.h>
#include <env.h>
#include <xz/unxz.h>
#include "wma301_oem_bl33.h"

#define PKG_MAGIC		"WMABL33"
#define WMA301_OEM_BL33_BOARD "tplink,wma301-v2"
#define PKG_HDR_SIZE		128
#define FIP_PART_NAME		"fip"
#define FIP_TOC_NAME		0xaa640001
#define FIP_TOC_START		0x88
#define MAX_BL33_RAW		SZ_2M
#define MAX_FIP_PART		SZ_2M

/* Work buffers above the load address (failsafe upload buffer is elsewhere) */
#define BUF_RAW_OFF		0x1000000
#define BUF_OLD_OFF		(BUF_RAW_OFF + MAX_BL33_RAW)
#define BUF_NEW_OFF		(BUF_OLD_OFF + MAX_FIP_PART)
#define BUF_RDB_OFF		(BUF_NEW_OFF + MAX_FIP_PART)

/* BL31 / BL33 UUIDs as stored in the TOC (little-endian GUID layout) */
static const u8 uuid_bl31[16] = {
	0x47, 0xd4, 0x08, 0x6d, 0x4c, 0xfe, 0x98, 0x46,
	0x9b, 0x95, 0x29, 0x50, 0xcb, 0xbd, 0x5a, 0x00 };
static const u8 uuid_bl33[16] = {
	0xd6, 0xd0, 0xee, 0xa7, 0xfc, 0xea, 0xd5, 0x4b,
	0x97, 0x82, 0x99, 0x34, 0xf2, 0x34, 0xb6, 0xe4 };

struct pkg_hdr {
	char magic[8];
	u32 version;
	u32 header_size;
	char board[32];
	u32 xz_size;
	u32 raw_size;
	u8 xz_sha256[32];
	u8 raw_sha256[32];
	u32 link_addr;
	u32 reserved;
} __packed;

struct toc_entry_raw {
	u8 uuid[16];
	u64 offset;
	u64 size;
	u64 flags;
} __packed;

static u8 *work_buf(ulong off)
{
	return (u8 *)(ulong)(CONFIG_SYS_LOAD_ADDR + off);
}

static int check_pkg(const void *data, size_t size, const struct pkg_hdr **ret)
{
	const struct pkg_hdr *h = data;
	static const u8 xz_head[8] = { 0xfd, '7', 'z', 'X', 'Z', 0x00, 0x00, 0x01 };
	static const char board_id[32] = WMA301_OEM_BL33_BOARD;
	u8 sum[SHA256_SUM_LEN];
	const u8 *xz;
	u8 *raw = work_buf(BUF_RAW_OFF);
	size_t out_len = 0;

	if (size < PKG_HDR_SIZE || memcmp(h->magic, PKG_MAGIC, 8)) {
		printf("BL33 update: not a WMABL33 package (use *_BL33_UPDATE.bin)\n");
		return -EINVAL;
	}
	if (h->version != 1 || h->header_size != PKG_HDR_SIZE || h->reserved) {
		printf("BL33 update: unsupported package version\n");
		return -EINVAL;
	}
	if (memcmp(h->board, board_id, sizeof(h->board))) {
		printf("BL33 update: package is for '%.32s', this board is '%s'\n",
		       h->board, WMA301_OEM_BL33_BOARD);
		return -EINVAL;
	}
	if ((u64)h->xz_size + PKG_HDR_SIZE != size ||
	    h->xz_size < sizeof(xz_head) || h->raw_size < 16 ||
	    h->raw_size > MAX_BL33_RAW || h->link_addr != (u32)CONFIG_TEXT_BASE) {
		printf("BL33 update: bad sizes or link address\n");
		return -EINVAL;
	}
	xz = (const u8 *)data + PKG_HDR_SIZE;
	if (memcmp(xz, xz_head, sizeof(xz_head))) {
		printf("BL33 update: payload is not an xz stream with CRC32 check\n");
		return -EINVAL;
	}
	sha256_csum_wd(xz, h->xz_size, sum, SZ_64K);
	if (memcmp(sum, h->xz_sha256, sizeof(sum))) {
		printf("BL33 update: xz sha256 mismatch (file damaged)\n");
		return -EINVAL;
	}
	if (unxz(xz, h->xz_size, &out_len, raw, MAX_BL33_RAW) != UNXZ_OK ||
	    out_len != h->raw_size) {
		printf("BL33 update: xz decompression failed\n");
		return -EINVAL;
	}
	sha256_csum_wd(raw, out_len, sum, SZ_64K);
	if (memcmp(sum, h->raw_sha256, sizeof(sum)) ||
	    *(u64 *)(raw + 8) != (u64)CONFIG_TEXT_BASE) {
		printf("BL33 update: decompressed U-Boot check failed\n");
		return -EINVAL;
	}
	*ret = h;
	return 0;
}

/* Read the fip partition and locate BL31; returns bytes used by the old FIP */
static int read_old_fip(struct mtd_info **retmtd, u8 *buf, u64 *bl31_off,
			u64 *bl31_size, u64 *used)
{
	const struct toc_entry_raw *e;
	struct mtd_info *mtd;
	size_t retlen;
	u64 end = 0;
	int ret, i, n31 = 0, n33 = 0;

	mtd_probe_devices();
	mtd = get_mtd_device_nm(FIP_PART_NAME);
	if (IS_ERR_OR_NULL(mtd)) {
		printf("BL33 update: partition '%s' not found\n", FIP_PART_NAME);
		return -ENODEV;
	}
	if (!mtd->parent || mtd->size != MAX_FIP_PART ||
	    mtd->offset != 0x200000 || mtd->erasesize != SZ_128K ||
	    mtd->parent->size != SZ_128M) {
		printf("BL33 update: unexpected '%s' partition\n", FIP_PART_NAME);
		put_mtd_device(mtd);
		return -EINVAL;
	}
	ret = mtd_read(mtd, 0, mtd->size, &retlen, buf);
	if ((ret && !mtd_is_bitflip(ret)) || retlen != mtd->size) {
		printf("BL33 update: failed to read FIP (%d)\n", ret);
		put_mtd_device(mtd);
		return -EIO;
	}
	if (*(u32 *)buf != FIP_TOC_NAME) {
		printf("BL33 update: no FIP TOC on flash\n");
		put_mtd_device(mtd);
		return -EINVAL;
	}
	for (i = 0; i < 8; i++) {
		e = (const void *)(buf + 16 + i * sizeof(*e));
		if (!memchr_inv(e->uuid, 0, 16))
			break;
		if (e->offset > mtd->size || e->size > mtd->size - e->offset) {
			put_mtd_device(mtd);
			return -EINVAL;
		}
		if (!memcmp(e->uuid, uuid_bl31, 16)) {
			*bl31_off = e->offset;
			*bl31_size = e->size;
			n31++;
		} else if (!memcmp(e->uuid, uuid_bl33, 16)) {
			n33++;
		} else {
			printf("BL33 update: FIP has an unexpected entry, refusing\n");
			put_mtd_device(mtd);
			return -EINVAL;
		}
		end = max(end, e->offset + e->size);
	}
	if (n31 != 1 || n33 != 1 || *bl31_off != FIP_TOC_START ||
	    !*bl31_size ||
	    memcmp(((const struct toc_entry_raw *)(buf + 16))[0].uuid,
		   uuid_bl31, 16) ||
	    memcmp(((const struct toc_entry_raw *)(buf + 16))[1].uuid,
		   uuid_bl33, 16)) {
		printf("BL33 update: FIP is not the expected BL31+BL33 layout\n");
		put_mtd_device(mtd);
		return -EINVAL;
	}
	*used = end;
	*retmtd = mtd;
	return 0;
}

static size_t build_new_fip(const u8 *old, u64 bl31_size, const u8 *xz,
			    size_t xz_size, u8 *out)
{
	struct toc_entry_raw *e;
	size_t end = FIP_TOC_START + bl31_size + xz_size;

	memcpy(out, old, 16);				/* TOC header */
	memset(out + 16, 0, FIP_TOC_START - 16);
	e = (void *)(out + 16);
	memcpy(e[0].uuid, uuid_bl31, 16);
	e[0].offset = FIP_TOC_START;
	e[0].size = bl31_size;
	e[0].flags = ((const struct toc_entry_raw *)(old + 16))[0].flags;
	memcpy(e[1].uuid, uuid_bl33, 16);
	e[1].offset = FIP_TOC_START + bl31_size;
	e[1].size = xz_size;
	e[1].flags = ((const struct toc_entry_raw *)(old + 16))[1].flags;
	e[2].offset = end;				/* fiptool-style terminator */
	memcpy(out + FIP_TOC_START, old + FIP_TOC_START, bl31_size);
	memcpy(out + FIP_TOC_START + bl31_size, xz, xz_size);
	return end;
}

static int program(struct mtd_info *master, u64 base, const u8 *data, u64 len,
		   u8 *rdback)
{
	struct erase_info ei;
	size_t retlen;
	int ret;

	memset(&ei, 0, sizeof(ei));
	ei.mtd = master;
	ei.addr = base;
	ei.len = len;
	ret = mtd_erase(master, &ei);
	if (ret)
		return ret;
	ret = mtd_write(master, base, len, &retlen, data);
	if (ret || retlen != len)
		return ret ? ret : -EIO;
	ret = mtd_read(master, base, len, &retlen, rdback);
	if ((ret && !mtd_is_bitflip(ret)) || retlen != len)
		return -EIO;
	return memcmp(rdback, data, len) ? -EIO : 0;
}

int wma301_oem_bl33_validate(const void *data, size_t size)
{
	const struct pkg_hdr *h;
	struct mtd_info *mtd;
	u64 bl31_off, bl31_size, used;
	int ret;

	ret = check_pkg(data, size, &h);
	if (ret)
		return ret;
	ret = read_old_fip(&mtd, work_buf(BUF_OLD_OFF), &bl31_off, &bl31_size, &used);
	if (ret)
		return ret;
	if (FIP_TOC_START + bl31_size + h->xz_size > mtd->size) {
		printf("BL33 update: new FIP does not fit the '%s' partition\n", FIP_PART_NAME);
		ret = -E2BIG;
	}
	put_mtd_device(mtd);
	return ret;
}

int wma301_oem_bl33_write(const void *data, size_t size)
{
	u8 *old = work_buf(BUF_OLD_OFF), *new = work_buf(BUF_NEW_OFF);
	u8 *rdb = work_buf(BUF_RDB_OFF);
	const struct pkg_hdr *h;
	struct mtd_info *mtd, *master;
	u64 bl31_off, bl31_size, used, len, base, off;
	size_t new_len;
	int ret;

	ret = check_pkg(data, size, &h);
	if (ret)
		return ret;
	ret = read_old_fip(&mtd, old, &bl31_off, &bl31_size, &used);
	if (ret)
		return ret;
	master = mtd->parent;
	base = mtd->offset;

	if (FIP_TOC_START + bl31_size + h->xz_size > mtd->size) {
		ret = -E2BIG;
		goto out;
	}
	new_len = build_new_fip(old, bl31_size, (const u8 *)data + PKG_HDR_SIZE,
				h->xz_size, new);
	len = ALIGN(max((u64)new_len, used), mtd->erasesize);
	if (len > mtd->size) {
		ret = -E2BIG;
		goto out;
	}
	memset(new + new_len, 0xff, len - new_len);
	if (!memcmp(new, old, len)) {
		printf("BL33 update: identical to the installed U-Boot, nothing to do\n");
		ret = 0;
		goto out;
	}
	for (off = 0; off < len; off += mtd->erasesize) {
		if (mtd_block_isbad(master, base + off)) {
			printf("BL33 update: bad block at 0x%llx, refusing\n", base + off);
			ret = -EIO;
			goto out;
		}
	}

	printf("BL33 update: writing FIP 0x%llx..0x%llx (BL31 kept, %u bytes BL33)\n",
	       base, base + len, h->xz_size);
	printf("BL33 update: DO NOT POWER OFF\n");
	ret = program(master, base, new, len, rdb);
	if (ret)
		ret = program(master, base, new, len, rdb);	/* one retry */
	if (!ret) {
		printf("BL33 update: written and verified\n");
		goto out;
	}

	printf("BL33 update: write failed (%d), restoring the previous FIP\n", ret);
	if (!program(master, base, old, len, rdb)) {
		printf("BL33 update: previous FIP restored and verified\n");
		ret = -EIO;
	} else {
		printf("BL33 update: RESTORE FAILED - do not power off; TTL rescue needed\n");
		ret = -EIO;
	}
out:
	put_mtd_device(mtd);
	return ret;
}
