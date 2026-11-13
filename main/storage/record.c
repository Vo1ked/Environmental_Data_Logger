#include "record.h"

bool record_valid(const app_record_t *record) { return record->timestamp >= UINT64_C(946684800) && record->timestamp < UINT64_C(4102444800) && record->temperature >= -4000 && record->temperature <= 8500 && record->humidity <= 10000 && record->pressure >= 225 && record->pressure <= 826; }

bool record_erased(const uint8_t *bytes, size_t size) {
	for (size_t i = 0; i < size; ++i)
		if (bytes[i] != 0xff)
			return false;
	return true;
}

static void put_le(uint8_t *bytes, uint64_t value, unsigned size) {
	for (unsigned i = 0; i < size; ++i)
		bytes[i] = (uint8_t)(value >> (8U * i));
}
static uint64_t get_le(const uint8_t *bytes, unsigned size) {
	uint64_t value = 0;
	for (unsigned i = 0; i < size; ++i)
		value |= (uint64_t)bytes[i] << (8U * i);
	return value;
}

void record_encode(const app_record_t *record, uint8_t bytes[APP_RECORD_SIZE]) {
	put_le(bytes, record->timestamp, 8);
	put_le(bytes + 8, (uint16_t)record->temperature, 2);
	put_le(bytes + 10, record->humidity, 2);
	put_le(bytes + 12, record->pressure, 4);
}

bool record_decode(const uint8_t bytes[APP_RECORD_SIZE], app_record_t *record) {
	const uint16_t temperature = (uint16_t)get_le(bytes + 8, 2);
	*record = (app_record_t){.timestamp = get_le(bytes, 8), .temperature = (int16_t)(temperature <= INT16_MAX ? (int32_t)temperature : (int32_t)temperature - 65536), .humidity = (uint16_t)get_le(bytes + 10, 2), .pressure = (uint32_t)get_le(bytes + 12, 4)};
	return record_valid(record);
}
