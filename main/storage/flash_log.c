#include "app.h"
#include "esp_partition.h"
#include "record.h"
#include "time/app_time.h"
#include <inttypes.h>
#include <string.h>

typedef struct flash_state_t {
	const esp_partition_t *partition;
	app_watchdog_t *watchdog;
	app_storage_status_t status;
	/* The only sector-sized log buffer: reused by startup scan and accumulation. */
	uint8_t buffer[APP_FLASH_SECTOR_SIZE];
} flash_state_t;

static bool scan(flash_state_t *state) {
	state->status = (app_storage_status_t){0};
	state->partition = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, APP_PARTITION_LABEL);
	if (!state->partition) {
		state->status.error = ESP_ERR_NOT_FOUND;
		return false;
	}
	state->status.size = state->partition->size;
	if (state->partition->encrypted || state->partition->erase_size != APP_FLASH_SECTOR_SIZE || !state->status.size || state->status.size % APP_FLASH_SECTOR_SIZE) {
		state->status.error = ESP_ERR_INVALID_SIZE;
		return false;
	}
	for (uint32_t offset = 0; offset < state->status.size; offset += APP_FLASH_SECTOR_SIZE) {
		state->status.error = esp_partition_read(state->partition, offset, state->buffer, sizeof(state->buffer));
		if (state->status.error != ESP_OK)
			return false;
		if (!record_erased(state->buffer, sizeof(state->buffer)))
			state->status.used_bytes = offset + APP_FLASH_SECTOR_SIZE;
		for (unsigned slot = 0; slot < APP_RECORDS_PER_SECTOR; ++slot) {
			const uint8_t *bytes = state->buffer + slot * APP_RECORD_SIZE;
			if (record_erased(bytes, APP_RECORD_SIZE))
				continue;
			app_record_t record;
			if (!record_decode(bytes, &record)) {
				++state->status.invalid_records;
				continue;
			}
			++state->status.records;
			state->status.last = record;
			state->status.last_valid = true;
		}
		app_watchdog_progress(state->watchdog, APP_WATCHDOG_FLASH);
		vTaskDelay(1);
	}
	memset(state->buffer, 0xff, sizeof(state->buffer));
	state->status.full = state->status.used_bytes >= state->status.size;
	return true;
}

static bool commit(flash_state_t *state) {
	if (state->status.error != ESP_OK)
		return false;
	if (!state->status.buffered)
		return true;
	if (state->status.full || state->status.used_bytes + APP_FLASH_SECTOR_SIZE > state->status.size)
		return false;
	/* Never erase implicitly. Check the destination is unused, then program one
	 * whole sector; a torn/failed write stops logging until an explicit erase. */
	uint8_t check[APP_RECORD_SIZE];
	for (unsigned i = 0; i < APP_FLASH_SECTOR_SIZE; i += sizeof(check)) {
		state->status.error = esp_partition_read(state->partition, state->status.used_bytes + i, check, sizeof(check));
		if (state->status.error == ESP_OK && !record_erased(check, sizeof(check)))
			state->status.error = ESP_ERR_INVALID_STATE;
		if (state->status.error != ESP_OK)
			return false;
		app_watchdog_progress(state->watchdog, APP_WATCHDOG_FLASH);
	}
	state->status.error = esp_partition_write(state->partition, state->status.used_bytes, state->buffer, sizeof(state->buffer));
	if (state->status.error != ESP_OK)
		return false;
	app_watchdog_progress(state->watchdog, APP_WATCHDOG_FLASH);
	for (unsigned i = 0; i < APP_FLASH_SECTOR_SIZE; i += sizeof(check)) {
		state->status.error = esp_partition_read(state->partition, state->status.used_bytes + i, check, sizeof(check));
		if (state->status.error == ESP_OK && memcmp(check, state->buffer + i, sizeof(check)))
			state->status.error = ESP_FAIL;
		if (state->status.error != ESP_OK)
			return false;
		app_watchdog_progress(state->watchdog, APP_WATCHDOG_FLASH);
	}
	state->status.last_valid = record_decode(state->buffer + (state->status.buffered - 1U) * APP_RECORD_SIZE, &state->status.last);
	state->status.records += state->status.buffered;
	state->status.buffered = 0;
	state->status.used_bytes += APP_FLASH_SECTOR_SIZE;
	state->status.full = state->status.used_bytes == state->status.size;
	memset(state->buffer, 0xff, sizeof(state->buffer));
	return true;
}

static bool append(flash_state_t *state, const app_record_t *record) {
	if (state->status.error != ESP_OK || state->status.full || state->status.buffered >= APP_RECORDS_PER_SECTOR || !record_valid(record))
		return false;
	record_encode(record, state->buffer + state->status.buffered * APP_RECORD_SIZE);
	++state->status.buffered;
	return state->status.buffered < APP_RECORDS_PER_SECTOR || commit(state);
}

static bool erase(flash_state_t *state) {
	if (!state->partition || state->partition->encrypted || state->partition->erase_size != APP_FLASH_SECTOR_SIZE || !state->partition->size || state->partition->size % APP_FLASH_SECTOR_SIZE)
		return false;
	for (uint32_t offset = 0; offset < state->partition->size; offset += APP_FLASH_SECTOR_SIZE) {
		state->status.error = esp_partition_erase_range(state->partition, offset, APP_FLASH_SECTOR_SIZE);
		if (state->status.error != ESP_OK)
			return false;
		app_watchdog_progress(state->watchdog, APP_WATCHDOG_FLASH);
		vTaskDelay(1);
	}
	return scan(state);
}

static bool read_records(app_t *app, flash_state_t *state, const flash_request_t *request) {
	if (!state->partition || state->status.error != ESP_OK || !request->count || request->count > APP_READ_MAX_RECORDS)
		return false;
	const uint32_t first = request->first == UINT32_MAX ? (state->status.records > request->count ? state->status.records - request->count : 0) : request->first;
	uint32_t index = 0, printed = 0;
	uint8_t bytes[APP_RECORD_SIZE];
	for (uint32_t offset = 0; offset < state->status.used_bytes && printed < request->count; offset += APP_RECORD_SIZE) {
		if (offset % 1024U == 0)
			vTaskDelay(1);
		state->status.error = esp_partition_read(state->partition, offset, bytes, sizeof(bytes));
		if (state->status.error != ESP_OK)
			return false;
		app_watchdog_progress(state->watchdog, APP_WATCHDOG_FLASH);
		app_record_t record;
		if (!record_decode(bytes, &record))
			continue;
		if (index++ < first)
			continue;
		char time[40];
		app_time_format_uart(record.timestamp, time, sizeof(time));
		if (!app_print(app, pdMS_TO_TICKS(500), "%" PRIu32 ", %s: T = %.1f C H = %.1f%% P = %" PRIu32 " mmHg\r\n", index - 1U, time, record.temperature / 100.0, record.humidity / 100.0, record.pressure))
			return false;
		++printed;
		vTaskDelay(1);
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
