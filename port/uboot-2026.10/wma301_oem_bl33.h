/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _WMA301_OEM_BL33_H_
#define _WMA301_OEM_BL33_H_
#include <stddef.h>
int wma301_oem_bl33_validate(const void *data, size_t size);
int wma301_oem_bl33_write(const void *data, size_t size);
#endif
