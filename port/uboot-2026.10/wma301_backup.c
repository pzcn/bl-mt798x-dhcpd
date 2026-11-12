// SPDX-License-Identifier: GPL-2.0
/*
 * WMA301 v2 standalone, READ-ONLY Web backup API.
 *
 * Retains the V4 wire contract:
 *   GET  /backup/info
 *   POST /backup/main (mode=part, storage=mtd, target=<allowlisted>)
 *
 * Intentionally independent of WEBUI_FAILSAFE_FLASH, which exposes
 * unneeded erase/write/restore operations on this board.
 */
#include <errno.h>
#include <malloc.h>
#include <mtd.h>
#include <linux/err.h>
#include <linux/kernel.h>
#include <linux/mtd/mtd.h>
#include <linux/string.h>
#include <net/mtk_httpd.h>
#include <failsafe/helpers.h>

#define WMA301_NAND_BYTES     0x8000000ULL
#define WMA301_ERASE_BYTES    0x20000U
#define WMA301_BACKUP_CHUNK   (16 * 1024)

struct wma301_part {
	const char *name;
	u64 offset;
	u32 size;
};

/* No full-chip, raw NAND/OOB, UBI, or arbitrary address/range access. */
static const struct wma301_part allowed[] = {
	{ "bl2",          0x000000, 0x020000 },
	{ "fip",          0x020000, 0x3a0000 },
	{ "reserved",     0x3c0000, 0x040000 },
	{ "factory_info", 0x400000, 0x080000 },
	{ "art",          0x480000, 0x080000 },
	{ "config",       0x500000, 0x200000 },
};

struct wma301_backup_session {
	struct mtd_info *mtd;
	u32 cursor;
	u32 limit;
	size_t header_size;
	char header[256];
	u8 chunk[WMA301_BACKUP_CHUNK];
};

/* Only name AND exact known geometry may select an MTD child device. */
static struct mtd_info *wma301_backup_open(const struct wma301_part *part)
{
	struct mtd_info *mtd;

	mtd = get_mtd_device_nm(part->name);
	if (IS_ERR_OR_NULL(mtd))
		return NULL;

	if (!mtd->parent ||
	    mtd->parent->size != WMA301_NAND_BYTES ||
	    mtd->size != part->size ||
	    mtd->offset != part->offset ||
	    mtd->erasesize != WMA301_ERASE_BYTES) {
		put_mtd_device(mtd);
		return NULL;
	}

	return mtd;
}

static void wma301_backup_info_handler(enum httpd_uri_handler_status status,
				       struct httpd_request *request,
				       struct httpd_response *response)
{
	char *buf;
	int len, i, count = 0;

	if (status == HTTP_CB_CLOSED) {
		free(response->session_data);
		return;
	}
	if (status != HTTP_CB_NEW)
		return;
	if (request->method != HTTP_GET) {
		failsafe_http_reply_text(response, 405, "GET required");
		return;
	}

	buf = malloc(1536);
	if (!buf) {
		failsafe_http_reply_text(response, 500, "out of memory");
		return;
	}

	mtd_probe_devices();
	len = buf_appendf(buf, 1536, 0,
			  "{\"mtd\":{\"present\":true,\"parts\":[");
	for (i = 0; i < ARRAY_SIZE(allowed); i++) {
		const struct wma301_part *part = &allowed[i];
		struct mtd_info *mtd = wma301_backup_open(part);

		if (!mtd)
			continue;

		len = buf_appendf(buf, 1536, len,
				  "%s{\"name\":\"%s\",\"size\":%u,\"master\":false}",
				  count++ ? "," : "", part->name, part->size);
		put_mtd_device(mtd);
	}
	len = buf_appendf(buf, 1536, len, "]}}");

	/* Keep exactly the V4 JSON keys required by the Toolbox. */
	failsafe_http_reply_json_alloc(response, 200, buf, buf);
}

static void wma301_backup_main_handler(enum httpd_uri_handler_status status,
				       struct httpd_request *request,
				       struct httpd_response *response)
{
	struct wma301_backup_session *session;
	struct httpd_form_value *mode, *storage, *target;
	const struct wma301_part *part = NULL;
	int i, ret;
	size_t got = 0, to_read;

	if (status == HTTP_CB_CLOSED) {
		session = response->session_data;
		if (session) {
			if (session->mtd)
				put_mtd_device(session->mtd);
			free(session);
			response->session_data = NULL;
		}
		return;
	}

	if (status == HTTP_CB_NEW) {
		if (request->method != HTTP_POST) {
			failsafe_http_reply_text(response, 405, "POST required");
			return;
		}
		mode = httpd_request_find_value(request, "mode");
		storage = httpd_request_find_value(request, "storage");
		target = httpd_request_find_value(request, "target");
		if (!mode || !mode->data || strcmp(mode->data, "part") ||
		    !storage || !storage->data || strcmp(storage->data, "mtd") ||
		    !target || !target->data ||
		    httpd_request_find_value(request, "start") ||
		    httpd_request_find_value(request, "end") ||
		    httpd_request_find_value(request, "raw")) {
			failsafe_http_reply_text(response, 400,
						 "Only named MTD partition backup is allowed");
			return;
		}
		for (i = 0; i < ARRAY_SIZE(allowed); i++) {
			if (!strcmp(allowed[i].name, target->data)) {
				part = &allowed[i];
				break;
			}
		}
		if (!part) {
			failsafe_http_reply_text(response, 403,
						 "MTD partition not in read-only allowlist");
			return;
		}

		session = calloc(1, sizeof(*session));
		if (!session) {
			failsafe_http_reply_text(response, 500, "out of memory");
			return;
		}
		mtd_probe_devices();
		session->mtd = wma301_backup_open(part);
		if (!session->mtd) {
			free(session);
			failsafe_http_reply_text(response, 404,
						 "MTD partition missing or geometry mismatch");
			return;
		}
		session->limit = part->size;

		ret = snprintf(session->header, sizeof(session->header),
			       "HTTP/1.1 200 OK\r\n"
			       "Content-Type: application/octet-stream\r\n"
			       "Content-Length: %u\r\n"
			       "Content-Disposition: attachment; filename=\"WMA301_%s.bin\"\r\n"
			       "Cache-Control: no-store\r\n"
			       "Connection: close\r\n"
			       "\r\n",
			       part->size, part->name);
		if (ret <= 0 || ret >= sizeof(session->header)) {
			put_mtd_device(session->mtd);
			free(session);
			failsafe_http_reply_text(response, 500, "header overflow");
			return;
		}
		session->header_size = ret;
		response->session_data = session;
		response->status = HTTP_RESP_CUSTOM;
		response->data = session->header;
		response->size = session->header_size;
		return;
	}

	if (status != HTTP_CB_RESPONDING)
		return;

	session = response->session_data;
	if (!session) {
		response->status = HTTP_RESP_NONE;
		return;
	}
	if (session->cursor == session->limit) {
		response->status = HTTP_RESP_NONE;
		return;
	}

	to_read = min_t(size_t, WMA301_BACKUP_CHUNK,
			session->limit - session->cursor);
	ret = mtd_read(session->mtd, session->cursor, to_read,
		       &got, session->chunk);
	if ((ret && !mtd_is_bitflip(ret)) || got != to_read) {
		printf("WMA301 backup: MTD read failed at 0x%x, err=%d, got=%zu\n",
		       session->cursor, ret, got);
		/* Early close causes the client to detect Content-Length mismatch. */
		response->status = HTTP_RESP_NONE;
		return;
	}

	session->cursor += got;
	response->status = HTTP_RESP_CUSTOM;
	response->data = (const char *)session->chunk;
	response->size = got;
}

void wma301_backup_register_handlers(struct httpd_instance *inst)
{
	httpd_register_uri_handler(inst, "/backup/info",
				   &wma301_backup_info_handler, NULL);
	httpd_register_uri_handler(inst, "/backup/main",
				   &wma301_backup_main_handler, NULL);
}
