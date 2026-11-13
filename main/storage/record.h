#pragma once
#include "app_config.h"
#include "app_types.h"
#include <stddef.h>

bool record_valid(const app_record_t *record);
void record_encode(const app_record_t *record, uint8_t bytes[APP_RECORD_SIZE]);
bool record_decode(const uint8_t bytes[APP_RECORD_SIZE], app_record_t *record);
bool record_erased(const uint8_t *bytes, size_t size);
