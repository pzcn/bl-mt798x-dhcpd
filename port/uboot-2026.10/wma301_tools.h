/* SPDX-License-Identifier: GPL-2.0 */
#ifndef WMA301_TOOLS_H
#define WMA301_TOOLS_H
struct httpd_instance;
int wma301_ubi_env_guard(void);
void wma301_tools_register_handlers(struct httpd_instance *inst);
#endif
