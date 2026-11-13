#include "app.h"
#include "esp_partition.h"
#include "record.h"
#include "time/app_time.h"
#include <inttypes.h>
#include <string.h>

#define DAY_MAGIC UINT32_C(0x324c4445)
#define DAY_COMMITTED UINT32_C(0x51a7c0de)

typedef struct day_slot_t {
	uint32_t day, used, records;
	bool valid;
} day_slot_t;

typedef struct flash_state_t {
	const esp_partition_t *partition;
	app_watchdog_t *watchdog;
	app_storage_status_t status;
	day_slot_t slots[APP_ARCHIVE_DAYS];
	int active;
	uint8_t buffer[APP_BUFFER_SIZE];
} flash_state_t;

static void progress(flash_state_t *state) {
	app_watchdog_progress(state->watchdog, APP_WATCHDOG_FLASH);
	vTaskDelay(1);
}

static bool read_bytes(flash_state_t *state, uint32_t offset, void *bytes, size_t size) {
	state->status.error = esp_partition_read(state->partition, offset, bytes, size);
	return state->status.error == ESP_OK;
}

static void totals(flash_state_t *state) {
	state->status.records = 0;
	state->status.used_bytes = 0;
	for (unsigned i = 0; i < APP_ARCHIVE_DAYS; ++i) {
		if (!state->slots[i].valid)
			continue;
		state->status.records += state->slots[i].records;
		state->status.used_bytes += APP_DAY_SLOT_SIZE;
	}
}

static bool header_valid(const uint32_t header[8], unsigned slot) { return header[0] == DAY_MAGIC && header[1] == 2 && header[2] >= 10957 && header[2] < 47482 && header[2] % APP_ARCHIVE_DAYS == slot && header[3] == ~header[2] && header[4] == APP_DAY_SLOT_SIZE && header[5] == APP_RECORD_SIZE && header[6] == record_crc32((const uint8_t *)header, 24) && header[7] == DAY_COMMITTED; }

static bool scan(flash_state_t *state) {
	state->status = (app_storage_status_t){0};
	memset(state->slots, 0, sizeof(state->slots));
	state->active = -1;
	state->partition = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, APP_PARTITION_LABEL);
	if (!state->partition) {
		state->status.error = ESP_ERR_NOT_FOUND;
		return false;
	}
	state->status.size = state->partition->size;
	if (state->partition->encrypted || state->partition->erase_size != APP_FLASH_SECTOR_SIZE || state->status.size != APP_ARCHIVE_DAYS * APP_DAY_SLOT_SIZE) {
		state->status.error = ESP_ERR_INVALID_SIZE;
		return false;
	}
	/* Legacy records start with a 64-bit UTC timestamp; never erase them implicitly. */
	uint64_t first;
	if (!read_bytes(state, 0, &first, sizeof(first)))
		return false;
	if (first >= UINT64_C(946684800) && first < UINT64_C(4102444800)) {
		state->status.error = ESP_ERR_NOT_SUPPORTED;
		return false;
	}
	uint32_t newest = 0;
	for (unsigned slot = 0; slot < APP_ARCHIVE_DAYS; ++slot) {
		uint32_t header[8];
		if (!read_bytes(state, slot * APP_DAY_SLOT_SIZE, header, sizeof(header)))
			return false;
		if (!header_valid(header, slot)) {
			if (!record_erased((const uint8_t *)header, sizeof(header)))
				++state->status.invalid_records;
			continue;
		}
		state->slots[slot] = (day_slot_t){.day = header[2], .valid = true};
		if (header[2] > newest) {
			newest = header[2];
			state->active = (int)slot;
		}
	}
	for (unsigned slot = 0; slot < APP_ARCHIVE_DAYS; ++slot) {
		day_slot_t *day = &state->slots[slot];
		if (!day->valid)
			continue;
		/* Old days after a clock jump are ignored even if power failed during cleanup. */
		if (day->day + APP_ARCHIVE_DAYS <= newest) {
			day->valid = false;
			continue;
		}
		uint64_t previous = 0;
		for (unsigned sector = 0; sector < APP_DAY_SLOT_SIZE; sector += APP_BUFFER_SIZE) {
			if (!read_bytes(state, slot * APP_DAY_SLOT_SIZE + sector, state->buffer, sizeof(state->buffer)))
				return false;
			for (unsigned pos = sector ? 0 : APP_DAY_HEADER_SIZE; pos < APP_BUFFER_SIZE; pos += APP_RECORD_SIZE) {
				const uint8_t *bytes = state->buffer + pos;
				if (record_erased(bytes, APP_RECORD_SIZE))
					continue;
				day->used = (sector + pos - APP_DAY_HEADER_SIZE) / APP_RECORD_SIZE + 1;
				app_record_t record;
				if (!record_decode(bytes, &record) || record.timestamp / 86400U != day->day || (previous && record.timestamp / APP_LOG_INTERVAL_SECONDS <= previous / APP_LOG_INTERVAL_SECONDS)) {
					++state->status.invalid_records;
					continue;
				}
				previous = record.timestamp;
				++day->records;
				if (!state->status.last_valid || record.timestamp > state->status.last.timestamp) {
					state->status.last = record;
					state->status.last_valid = true;
				}
			}
			progress(state);
		}
	}
	totals(state);
	memset(state->buffer, 0xff, sizeof(state->buffer));
	return true;
}

static bool erase_slot(flash_state_t *state, unsigned slot) {
	/* Retire the header sector before touching the remaining sectors of the day. */
	for (unsigned offset = 0; offset < APP_DAY_SLOT_SIZE; offset += APP_FLASH_SECTOR_SIZE) {
		state->status.error = esp_partition_erase_range(state->partition, slot * APP_DAY_SLOT_SIZE + offset, APP_FLASH_SECTOR_SIZE);
		if (state->status.error != ESP_OK)
			return false;
		progress(state);
	}
	state->slots[slot] = (day_slot_t){0};
	return true;
}

static bool commit(flash_state_t *state) {
	if (state->status.error != ESP_OK)
		return false;
	if (!state->status.buffered)
		return true;
	if (state->active < 0 || state->active >= (int)APP_ARCHIVE_DAYS || !state->slots[state->active].valid || state->status.buffered > APP_BUFFER_RECORDS || state->slots[state->active].used + state->status.buffered > APP_DAY_RECORD_CAPACITY) {
		state->status.error = ESP_ERR_INVALID_STATE;
		return false;
	}
	day_slot_t *day = &state->slots[state->active];
	const uint32_t offset = (unsigned)state->active * APP_DAY_SLOT_SIZE + APP_DAY_HEADER_SIZE + day->used * APP_RECORD_SIZE;
	const uint32_t size = state->status.buffered * APP_RECORD_SIZE;
	uint8_t check[APP_RECORD_SIZE];
	/* Never program previously occupied bytes, including a torn record. */
	for (uint32_t pos = 0; pos < size; pos += sizeof(check)) {
		if (!read_bytes(state, offset + pos, check, sizeof(check)))
			return false;
		if (!record_erased(check, sizeof(check))) {
			state->status.error = ESP_ERR_INVALID_STATE;
			return false;
		}
		if (pos % 1024U == 0)
			progress(state);
	}
	state->status.error = esp_partition_write(state->partition, offset, state->buffer, size);
	if (state->status.error != ESP_OK)
		return false;
	for (uint32_t pos = 0; pos < size; pos += sizeof(check)) {
		if (!read_bytes(state, offset + pos, check, sizeof(check)))
			return false;
		if (memcmp(check, state->buffer + pos, sizeof(check))) {
			state->status.error = ESP_FAIL;
			return false;
		}
		if (pos % 1024U == 0)
			progress(state);
	}
	day->used += state->status.buffered;
	day->records += state->status.buffered;
	state->status.last_valid = record_decode(state->buffer + size - APP_RECORD_SIZE, &state->status.last);
	state->status.buffered = 0;
	memset(state->buffer, 0xff, sizeof(state->buffer));
	totals(state);
	progress(state);
	return true;
}

static bool open_day(flash_state_t *state, uint32_t day) {
	if (!commit(state))
		return false;
	const unsigned slot = day % APP_ARCHIVE_DAYS;
	if (!erase_slot(state, slot))
		return false;
	uint32_t header[8] = {DAY_MAGIC, 2, day, ~day, APP_DAY_SLOT_SIZE, APP_RECORD_SIZE, 0, DAY_COMMITTED};
	header[6] = record_crc32((const uint8_t *)header, 24);
	const uint32_t offset = slot * APP_DAY_SLOT_SIZE;
	state->status.error = esp_partition_write(state->partition, offset, header, 28);
	if (state->status.error != ESP_OK)
		return false;
	state->status.error = esp_partition_write(state->partition, offset + 28, &header[7], 4);
	if (state->status.error != ESP_OK)
		return false;
	uint32_t check[8];
	if (!read_bytes(state, offset, check, sizeof(check)))
		return false;
	if (memcmp(header, check, sizeof(header))) {
		state->status.error = ESP_FAIL;
		return false;
	}
	state->slots[slot] = (day_slot_t){.day = day, .valid = true};
	state->active = (int)slot;
	for (unsigned i = 0; i < APP_ARCHIVE_DAYS; ++i)
		if (state->slots[i].valid && state->slots[i].day + APP_ARCHIVE_DAYS <= day && !erase_slot(state, i))
			return false;
	if (state->status.last_valid && state->status.last.timestamp / 86400U + APP_ARCHIVE_DAYS <= day)
		state->status.last_valid = false;
	totals(state);
	return true;
}

static bool append(flash_state_t *state, const app_record_t *record) {
	if (state->status.error != ESP_OK || !record_valid(record))
		return false;
	const uint32_t day = (uint32_t)(record->timestamp / 86400U);
	if (state->active >= 0 && day < state->slots[state->active].day)
		return false;
	app_record_t last = state->status.last;
	bool have_last = state->status.last_valid;
	if (state->status.buffered)
		have_last = record_decode(state->buffer + (state->status.buffered - 1) * APP_RECORD_SIZE, &last);
	if (have_last && record->timestamp / APP_LOG_INTERVAL_SECONDS <= last.timestamp / APP_LOG_INTERVAL_SECONDS)
		return record->timestamp / APP_LOG_INTERVAL_SECONDS == last.timestamp / APP_LOG_INTERVAL_SECONDS;
	if ((state->active < 0 || day != state->slots[state->active].day) && !open_day(state, day))
		return false;
	day_slot_t *active = &state->slots[state->active];
	if (active->used + state->status.buffered >= APP_DAY_RECORD_CAPACITY) {
		state->status.error = ESP_ERR_NO_MEM;
		return false;
	}
	record_encode(record, state->buffer + state->status.buffered * APP_RECORD_SIZE);
	++state->status.buffered;
	return (state->status.buffered < APP_BUFFER_RECORDS && active->used + state->status.buffered < APP_DAY_RECORD_CAPACITY) || commit(state);
}

static bool erase(flash_state_t *state) {
	if (!state->partition || state->partition->encrypted || state->partition->size != APP_ARCHIVE_DAYS * APP_DAY_SLOT_SIZE || state->partition->erase_size != APP_FLASH_SECTOR_SIZE)
		return false;
	for (unsigned slot = 0; slot < APP_ARCHIVE_DAYS; ++slot)
		if (!erase_slot(state, slot))
			return false;
	return scan(state);
}

static bool read_records(app_t *app, flash_state_t *state, const flash_request_t *request) {
	if (!state->partition || state->status.error != ESP_OK || !request->count || request->count > APP_READ_MAX_RECORDS)
		return false;
	const uint32_t first = request->first == UINT32_MAX ? (state->status.records > request->count ? state->status.records - request->count : 0) : request->first;
	uint32_t index = 0, printed = 0;
	if (state->active >= 0) {
		const uint32_t newest = state->slots[state->active].day;
		for (unsigned age = APP_ARCHIVE_DAYS; age > 0 && printed < request->count; --age) {
			const uint32_t day = newest - (age - 1);
			const unsigned slot = day % APP_ARCHIVE_DAYS;
			const day_slot_t *entry = &state->slots[slot];
			if (!entry->valid || entry->day != day)
				continue;
			if (index + entry->records <= first) {
				index += entry->records;
				continue;
			}
			uint64_t previous = 0;
			for (unsigned pos = 0; pos < entry->used && printed < request->count; ++pos) {
				uint8_t bytes[APP_RECORD_SIZE];
				if (!read_bytes(state, slot * APP_DAY_SLOT_SIZE + APP_DAY_HEADER_SIZE + pos * APP_RECORD_SIZE, bytes, sizeof(bytes)))
					return false;
				if (pos % 64U == 0)
					progress(state);
				app_record_t record;
				if (!record_decode(bytes, &record) || record.timestamp / 86400U != day || (previous && record.timestamp / APP_LOG_INTERVAL_SECONDS <= previous / APP_LOG_INTERVAL_SECONDS))
					continue;
				previous = record.timestamp;
				if (index++ < first)
					continue;
				char time[40];
				app_time_format_uart(record.timestamp, time, sizeof(time));
				if (!app_print(app, pdMS_TO_TICKS(500), "%" PRIu32 ", %s: T = %.1f C H = %.1f%% P = %" PRIu32 " mmHg\r\n", index - 1, time, record.temperature / 100.0, record.humidity / 100.0, record.pressure))
					return false;
				++printed;
				progress(state);
			}
		}
	}
	return app_print(app, pdMS_TO_TICKS(500), "READ END: %" PRIu32 " record(s); RAM entries excluded\r\n", printed);
}

void flash_task(void *argument) {
	app_t *app = argument;
	static flash_state_t state;
	ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
	state.watchdog = &app->watchdog;
	flash_request_t request;
	for (;;) {
		xQueueReceive(app->flash_requests, &request, portMAX_DELAY);
		app_event_t reply = {.kind = EVENT_FLASH};
		switch (request.operation) {
		case FLASH_SCAN:
			reply.success = scan(&state);
			break;
		case FLASH_APPEND:
			reply.success = append(&state, &request.record);
			break;
		case FLASH_FLUSH:
			reply.success = commit(&state);
			break;
		case FLASH_ERASE:
			reply.success = erase(&state);
			break;
		case FLASH_READ:
			reply.success = read_records(app, &state, &request);
			break;
		}
		reply.data.flash.operation = request.operation;
		reply.data.flash.status = state.status;
		app_post(app, &reply);
	}
}
