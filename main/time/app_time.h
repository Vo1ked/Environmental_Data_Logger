#pragma once
#include "volk_core/devices/rts_ds1307.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

bool app_time_from_rtc(const rts_ds1307_time_t *rtc, uint64_t *timestamp);
bool app_time_to_rtc(uint64_t timestamp, rts_ds1307_time_t *rtc);
bool app_time_parse(const char *text, uint64_t *timestamp);
void app_time_format(uint64_t timestamp, char *text, size_t capacity, bool local);
void app_time_format_uart(uint64_t timestamp, char *text, size_t capacity);
