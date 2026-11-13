// SPDX-License-Identifier: GPL-2.0
/*
 * WMA301 V2 Web recovery helpers (U-Boot 2026.10).
 *
 *   GET  /wma301/health        read-only NAND / UBI status
 *   GET  /wma301/fitinfo       read-only header of the installed FIT
 *   POST /wma301/fitcheck      read the whole "fit" volume, verify FIT hashes
 *   POST /wma301/reset-config  confirm=RESET: recreate "rootfs_data" only
 *
 * Plus wma301_ubi_env_guard(), called before every Web firmware write.
 *
 * Nothing here touches bl2, fip, reserved, factory_info, art or config.
 * The only write is removing/recreating the OpenWrt overlay volume.
 */
#include <command.h>
#include <errno.h>
#include <image.h>
#include <malloc.h>
#include <mapmem.h>
#include <mtd.h>
#include <ubi_uboot.h>
#include <linux/err.h>
#include <linux/kernel.h>
#include <linux/libfdt.h>
#include <linux/mtd/mtd.h>
#include <linux/string.h>
#include <net/mtk_httpd.h>
#include <failsafe/error.h>
#include <failsafe/helpers.h>
#include "wma301_tools.h"

#define WMA301_JSON_SZ        2048
/* Scratch RAM for /wma301/fitcheck: above the upload buffer (0x44000000),
 * the RAM-boot address (0x46000000) and the BL33 writer (0x47000000+). */
#define WMA301_SCRATCH        0x48000000UL
#define WMA301_SCRATCH_MAX    0x04000000UL	/* 64 MiB */
#define WMA301_FIT_HDR_MAX    0x10000

static int wma301_ubi_ready(void)
{
	if (ubi_devices[0])
		return 0;
	return run_command("ubi part ubi", 0) ? -EIO : 0;
}

int wma301_ubi_env_guard(void)
{
	if (wma301_ubi_ready())
		return failsafe_error(-EIO, "WMA301: cannot attach UBI");
	if (!ubi_find_volume("ubootenv") || !ubi_find_volume("ubootenv2"))
		return failsafe_error(-ENOSPC,
			"WMA301: ubootenv/ubootenv2 missing; reboot once so "
			"U-Boot recreates them before flashing firmware");
	return 0;
}

/* Copy s into a JSON string body, dropping quotes, backslashes, controls. */
static void wma301_json_clean(char *dst, size_t n, const char *s)
{
	size_t i = 0;

	for (; s && *s && i + 1 < n; s++) {
		unsigned char c = *s;

		if (c < 0x20 || c == '"' || c == '\\')
			continue;
		dst[i++] = c;
	}
	dst[i] = '\0';
}

static void wma301_reply_json(struct httpd_response *response, char *buf)
{
	failsafe_http_reply_json_alloc(response, 200, buf, buf);
}

/* ------------------------------------------------------------ health -- */

static int wma301_chip_bad_blocks(void)
{
	struct mtd_info *mtd;
	u64 off;
	int bad = 0;

	mtd_probe_devices();
	mtd = get_mtd_device_nm("spi-nand0");
	if (IS_ERR_OR_NULL(mtd))
		return -1;
	for (off = 0; off < mtd->size; off += mtd->erasesize)
		if (mtd_block_isbad(mtd, off) > 0)
			bad++;
	put_mtd_device(mtd);
	return bad;
}

static void wma301_health_handler(enum httpd_uri_handler_status status,
				  struct httpd_request *request,
				  struct httpd_response *response)
{
	struct ubi_device *ubi = NULL;
	char *buf, name[UBI_VOL_NAME_MAX + 1];
	int len, i, n = 0;

	if (status == HTTP_CB_CLOSED) {
		free(response->session_data);
		return;
	}
	if (status != HTTP_CB_NEW)
		return;

	buf = malloc(WMA301_JSON_SZ);
	if (!buf) {
		failsafe_http_reply_text(response, 500, "out of memory");
		return;
	}
	len = buf_appendf(buf, WMA301_JSON_SZ, 0, "{\"chip_bad_blocks\":%d",
			  wma301_chip_bad_blocks());

	if (wma301_ubi_ready() || !(ubi = ubi_devices[0])) {
		len = buf_appendf(buf, WMA301_JSON_SZ, len, ",\"ubi\":null}");
		wma301_reply_json(response, buf);
		return;
	}

	len = buf_appendf(buf, WMA301_JSON_SZ, len,
		",\"ubi\":{\"good_pebs\":%d,\"bad_pebs\":%d,\"corr_pebs\":%d,"
		"\"spare_pebs\":%d,\"avail_pebs\":%d,\"max_ec\":%d,\"mean_ec\":%d,"
		"\"peb_size\":%d,\"volumes\":[",
		ubi->good_peb_count, ubi->bad_peb_count, ubi->corr_peb_count,
		ubi->beb_rsvd_pebs, ubi->avail_pebs, ubi->max_ec, ubi->mean_ec,
		ubi->peb_size);
	for (i = 0; i < ubi->vtbl_slots; i++) {
		struct ubi_volume *vol = ubi->volumes[i];

		if (!vol)
			continue;
		wma301_json_clean(name, sizeof(name), vol->name);
		len = buf_appendf(buf, WMA301_JSON_SZ, len,
			"%s{\"id\":%d,\"name\":\"%s\",\"size\":%llu,\"used\":%llu,"
			"\"static\":%s}",
			n++ ? "," : "", i, name,
			(unsigned long long)vol->reserved_pebs * vol->usable_leb_size,
			(unsigned long long)vol->used_bytes,
			vol->vol_type == UBI_STATIC_VOLUME ? "true" : "false");
	}
	len = buf_appendf(buf, WMA301_JSON_SZ, len, "]}}");
	wma301_reply_json(response, buf);
}

/* ----------------------------------------------------------- fitinfo -- */

static int wma301_fit_append_info(char *buf, int len, const void *fit)
{
	char clean[160], *desc;
	time_t ts;
	int conf, node, images;
	const char *def;

	if (!fit_get_desc(fit, 0, &desc)) {
		wma301_json_clean(clean, sizeof(clean), desc);
		len = buf_appendf(buf, WMA301_JSON_SZ, len,
				  ",\"description\":\"%s\"", clean);
	}
	if (!fit_get_timestamp(fit, 0, &ts))
		len = buf_appendf(buf, WMA301_JSON_SZ, len,
				  ",\"timestamp\":%llu", (unsigned long long)ts);

	conf = fdt_path_offset(fit, FIT_CONFS_PATH);
	def = conf >= 0 ? fdt_getprop(fit, conf, FIT_DEFAULT_PROP, NULL) : NULL;
	node = def ? fdt_subnode_offset(fit, conf, def) : -1;
	if (node >= 0 && !fit_get_desc(fit, node, &desc)) {
		wma301_json_clean(clean, sizeof(clean), desc);
		len = buf_appendf(buf, WMA301_JSON_SZ, len,
				  ",\"config\":\"%s\"", clean);
	}

	images = fdt_path_offset(fit, FIT_IMAGES_PATH);
	if (images >= 0) {
		int n = 0;

		len = buf_appendf(buf, WMA301_JSON_SZ, len, ",\"images\":[");
		fdt_for_each_subnode(node, fit, images) {
			const char *type = fdt_getprop(fit, node, FIT_TYPE_PROP, NULL);

			clean[0] = '\0';
			if (!fit_get_desc(fit, node, &desc))
				wma301_json_clean(clean, sizeof(clean), desc);
			len = buf_appendf(buf, WMA301_JSON_SZ, len,
				"%s{\"type\":\"%s\",\"description\":\"%s\"}",
				n++ ? "," : "", type ? type : "", clean);
		}
		len = buf_appendf(buf, WMA301_JSON_SZ, len, "]");
	}
	return len;
}

static void wma301_fitinfo_handler(enum httpd_uri_handler_status status,
				   struct httpd_request *request,
				   struct httpd_response *response)
{
	struct ubi_volume *vol = NULL;
	char *buf;
	void *hdr;
	u32 total;
	int len;

	if (status == HTTP_CB_CLOSED) {
		free(response->session_data);
		return;
	}
	if (status != HTTP_CB_NEW)
		return;

	buf = malloc(WMA301_JSON_SZ);
	hdr = malloc(WMA301_FIT_HDR_MAX);
	if (!buf || !hdr) {
		free(buf);
		free(hdr);
		failsafe_http_reply_text(response, 500, "out of memory");
		return;
	}

	if (wma301_ubi_ready() || !(vol = ubi_find_volume("fit")) ||
	    vol->used_bytes < 64) {
		len = buf_appendf(buf, WMA301_JSON_SZ, 0, "{\"present\":false}");
		goto out;
	}
	len = buf_appendf(buf, WMA301_JSON_SZ, 0,
			  "{\"present\":true,\"volume_bytes\":%llu",
			  (unsigned long long)vol->used_bytes);

	if (ubi_volume_read("fit", hdr, 0, 64) ||
	    fdt_check_header(hdr)) {
		len = buf_appendf(buf, WMA301_JSON_SZ, len,
				  ",\"error\":\"not a FIT image\"}");
		goto out;
	}
	total = fdt_totalsize(hdr);
	if (total > WMA301_FIT_HDR_MAX || total > vol->used_bytes ||
	    ubi_volume_read("fit", hdr, 0, total)) {
		len = buf_appendf(buf, WMA301_JSON_SZ, len,
				  ",\"error\":\"cannot read FIT header\"}");
		goto out;
	}
	len = wma301_fit_append_info(buf, len, hdr);
	len = buf_appendf(buf, WMA301_JSON_SZ, len, "}");
out:
	free(hdr);
	wma301_reply_json(response, buf);
}

/* ---------------------------------------------------------- fitcheck -- */

static void wma301_fitcheck_handler(enum httpd_uri_handler_status status,
				    struct httpd_request *request,
				    struct httpd_response *response)
{
	struct ubi_volume *vol = NULL;
	unsigned long size;
	void *fit;
	char *buf;
	int len, ret;

	if (status == HTTP_CB_CLOSED) {
		free(response->session_data);
		return;
	}
	if (status != HTTP_CB_NEW)
		return;
	if (request->method != HTTP_POST) {
		failsafe_http_reply_text(response, 405, "POST required");
		return;
	}

	buf = malloc(WMA301_JSON_SZ);
	if (!buf) {
		failsafe_http_reply_text(response, 500, "out of memory");
		return;
	}
	if (wma301_ubi_ready() || !(vol = ubi_find_volume("fit")) ||
	    !vol->used_bytes) {
		len = buf_appendf(buf, WMA301_JSON_SZ, 0,
				  "{\"present\":false,\"ok\":false}");
		goto out;
	}
	size = vol->used_bytes;
	if (size > WMA301_SCRATCH_MAX) {
		len = buf_appendf(buf, WMA301_JSON_SZ, 0,
			"{\"present\":true,\"ok\":false,\"stage\":\"size\","
			"\"error\":\"fit volume larger than 64 MiB\"}");
		goto out;
	}

	fit = map_sysmem(WMA301_SCRATCH, size);
	printf("WMA301: reading fit volume (%lu bytes) for integrity check\n",
	       size);
	ret = ubi_volume_read("fit", fit, 0, size);
	if (ret) {
		len = buf_appendf(buf, WMA301_JSON_SZ, 0,
			"{\"present\":true,\"ok\":false,\"stage\":\"read\","
			"\"bytes\":%lu,\"error\":\"NAND read failed (%d)\"}",
			size, ret);
		goto unmap;
	}
	if (fit_check_format(fit, size)) {
		len = buf_appendf(buf, WMA301_JSON_SZ, 0,
			"{\"present\":true,\"ok\":false,\"stage\":\"format\","
			"\"bytes\":%lu,\"error\":\"not a valid FIT image\"}", size);
		goto unmap;
	}
	if (!fit_all_image_verify(fit)) {
		len = buf_appendf(buf, WMA301_JSON_SZ, 0,
			"{\"present\":true,\"ok\":false,\"stage\":\"hash\","
			"\"bytes\":%lu,\"error\":\"image hash mismatch\"", size);
		len = wma301_fit_append_info(buf, len, fit);
		len = buf_appendf(buf, WMA301_JSON_SZ, len, "}");
		goto unmap;
	}
	len = buf_appendf(buf, WMA301_JSON_SZ, 0,
			  "{\"present\":true,\"ok\":true,\"bytes\":%lu", size);
	len = wma301_fit_append_info(buf, len, fit);
	len = buf_appendf(buf, WMA301_JSON_SZ, len, "}");
unmap:
	unmap_sysmem(fit);
out:
	wma301_reply_json(response, buf);
}

/* ------------------------------------------------------ reset-config -- */

static void wma301_reset_config_handler(enum httpd_uri_handler_status status,
					struct httpd_request *request,
					struct httpd_response *response)
{
	struct httpd_form_value *confirm;
	int ret;

	if (status != HTTP_CB_NEW)
		return;
	if (request->method != HTTP_POST) {
		failsafe_http_reply_text(response, 405, "POST required");
		return;
	}
	confirm = httpd_request_find_value(request, "confirm");
	if (!confirm || !confirm->data || strcmp(confirm->data, "RESET")) {
		failsafe_http_reply_text(response, 400, "confirm=RESET required");
		return;
	}
	ret = wma301_ubi_env_guard();
	if (ret) {
		failsafe_http_reply_text(response, 409, failsafe_error_msg());
		return;
	}
	if (ubi_find_volume("rootfs_data") &&
	    run_command("ubi remove rootfs_data", 0)) {
		failsafe_http_reply_text(response, 500,
					 "cannot remove rootfs_data");
		return;
	}
	if (run_command("ubi create rootfs_data - dynamic", 0)) {
		failsafe_http_reply_text(response, 500,
					 "cannot create rootfs_data");
		return;
	}
	puts("WMA301: rootfs_data recreated (OpenWrt settings cleared)\n");
	failsafe_http_reply_text(response, 200, "success");
}

void wma301_tools_register_handlers(struct httpd_instance *inst)
{
	httpd_register_uri_handler(inst, "/wma301/health",
				   &wma301_health_handler, NULL);
	httpd_register_uri_handler(inst, "/wma301/fitinfo",
				   &wma301_fitinfo_handler, NULL);
	httpd_register_uri_handler(inst, "/wma301/fitcheck",
				   &wma301_fitcheck_handler, NULL);
	httpd_register_uri_handler(inst, "/wma301/reset-config",
				   &wma301_reset_config_handler, NULL);
}
