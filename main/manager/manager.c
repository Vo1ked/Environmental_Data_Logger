#include "app.h"
#include "esp_log.h"
#include "esp_sleep.h"
#include "esp_system.h"
#include "time/app_time.h"
#include <inttypes.h>
#include <stdio.h>

typedef struct manager_t {
	app_sample_t sample;
	app_storage_status_t storage;
	bool logging, loaded, uart_ready, oled_ready;
	bool sensor_busy, display_busy, flash_busy, pausing, dirty;
	uint64_t next_sample, next_log, next_sleep_attempt;
	uint32_t sleeps, sleep_errors, missed_cycles, skipped_logs;
} manager_t;

static void supervise(app_t *app) {
	if (!app_watchdog_check(&app->watchdog))
		app_watchdog_wait_for_reset(&app->watchdog);
}

static const char *mode(const manager_t *manager) { return manager->storage.error ? "ERROR" : manager->storage.full ? "FULL" : manager->logging ? "ON" : "OFF"; }

static void console_status(const manager_t *manager) {
	char time[40] = "TIME unavailable", climate[80] = "T = -- C H = --% P = -- mmHg";
	if (manager->sample.rtc_valid)
		app_time_format_uart(manager->sample.record.timestamp, time, sizeof(time));
	if (manager->sample.climate_valid)
		snprintf(climate, sizeof(climate), "T = %.1f C H = %.1f%% P = %" PRIu32 " mmHg", manager->sample.record.temperature / 100.0, manager->sample.record.humidity / 100.0, manager->sample.record.pressure);
	ESP_LOGI("status", "%s: %s; RTC=%s BME280=%s OLED=%s; LOG %s; saved=%" PRIu32 " RAM=%" PRIu32 "/%u; flash=%s; sleep=%" PRIu32, time, climate, manager->sample.rtc_valid ? "OK" : "ERROR", manager->sample.climate_valid ? "OK" : "ERROR", manager->oled_ready ? "OK" : "ERROR", mode(manager), manager->storage.records, manager->storage.buffered, APP_RECORDS_PER_SECTOR,
			 esp_err_to_name(manager->storage.error), manager->sleeps);
}

static void status(app_t *app, const manager_t *manager) {
	/* Console backpressure must not delay worker replies and their deadlines. */
	app_print(app, 0, "WDT=ON; timeout=%u s; panic=ON; reset reason=%d\r\n", (unsigned)CONFIG_ESP_TASK_WDT_TIMEOUT_S, (int)esp_reset_reason());
	app_print(app, 0, "LOG %s; N=%u min; saved=%" PRIu32 "; RAM=%" PRIu32 "/%u; occupied=%" PRIu32 "/%" PRIu32 " B; invalid=%" PRIu32 "; flash=%s\r\n", mode(manager), APP_LOG_INTERVAL_MINUTES, manager->storage.records, manager->storage.buffered, APP_RECORDS_PER_SECTOR, manager->storage.used_bytes, manager->storage.size, manager->storage.invalid_records, esp_err_to_name(manager->storage.error));
	app_print(app, 0, "RTC=%s BME280=%s OLED=%s; Light Sleep=%" PRIu32 "; sleep errors=%" PRIu32 "; missed cycles=%" PRIu32 "; skipped logs=%" PRIu32 "; busy sensor/display/flash=%u/%u/%u\r\n", manager->sample.rtc_valid ? "OK" : "ERROR", manager->sample.climate_valid ? "OK" : "ERROR", manager->oled_ready ? "OK" : "ERROR", manager->sleeps, manager->sleep_errors, manager->missed_cycles,
			  manager->skipped_logs, manager->sensor_busy, manager->display_busy, manager->flash_busy);
	if (manager->sample.rtc_valid) {
		char time[40];
		app_time_format_uart(manager->sample.record.timestamp, time, sizeof(time));
		app_print(app, 0, "%s%s; T=%.2f C; H=%.2f %%; P=%" PRIu32 " mmHg%s\r\n", manager->sample.archived ? "ARCHIVE " : "", time, manager->sample.record.temperature / 100.0, manager->sample.record.humidity / 100.0, manager->sample.record.pressure, manager->sample.climate_valid ? "" : " (climate invalid)");
	}
}

static bool request_flash(app_t *app, manager_t *manager, const flash_request_t *request) {
	if (manager->flash_busy)
		return false;
	/* Arm before dispatch: the other core may start processing immediately. */
	app_watchdog_begin(&app->watchdog, APP_WATCHDOG_FLASH, APP_WATCHDOG_FLASH_MS);
	if (xQueueSend(app->flash_requests, request, 0) != pdTRUE) {
		app_watchdog_end(&app->watchdog, APP_WATCHDOG_FLASH);
		return false;
	}
	manager->flash_busy = true;
	return true;
}

static bool request_sensor(app_t *app, manager_t *manager, const sensor_request_t *request) {
	if (manager->sensor_busy)
		return false;
	app_watchdog_begin(&app->watchdog, APP_WATCHDOG_SENSOR, APP_WATCHDOG_SENSOR_MS);
	if (xQueueSend(app->sensor_requests, request, 0) != pdTRUE) {
		app_watchdog_end(&app->watchdog, APP_WATCHDOG_SENSOR);
		return false;
	}
	manager->sensor_busy = true;
	return true;
}

static void command(app_t *app, manager_t *manager, const app_command_t *command) {
	if (command->kind == APP_HELP) {
		app_print(app, 0, "status | log on | log off | flush | erase | read [first count]\r\ntime set YYYY-MM-DDTHH:MM:SSZ | help\r\nread: last 16 by default, count 1..256, saved entries only. erase deletes logdata and RAM.\r\n");
		return;
	}
	if (command->kind == APP_STATUS) {
		status(app, manager);
		return;
	}
	if (!manager->loaded) {
		app_print(app, 0, "BUSY: startup scan\r\n");
		return;
	}
	if (command->kind == APP_LOG_OFF) {
		manager->logging = false;
		manager->dirty = true;
		app_print(app, 0, "OK: logging OFF; RAM retained, use flush before power-off\r\n");
		return;
	}
	if (command->kind == APP_LOG_ON) {
		if (manager->storage.error || manager->storage.full) {
			app_print(app, 0, "ERROR: storage unavailable/full; inspect status, read or erase\r\n");
			return;
		}
		if (manager->flash_busy) {
			app_print(app, 0, "BUSY: flash operation; retry log on\r\n");
			return;
		}
		if (!manager->logging)
			manager->next_log = app_now_ms() + APP_LOG_INTERVAL_MINUTES * UINT64_C(60000);
		manager->logging = true;
		manager->dirty = true;
		app_print(app, 0, "OK: logging ON\r\n");
		return;
	}
	if (command->kind == APP_TIME_SET) {
		const sensor_request_t request = {.operation = SENSOR_SET_TIME, .timestamp = command->timestamp};
		if (!request_sensor(app, manager, &request))
			app_print(app, 0, "BUSY: sensor operation; retry time set\r\n");
		return;
	}
	flash_request_t request = {.operation = command->kind == APP_ERASE ? FLASH_ERASE : command->kind == APP_READ ? FLASH_READ : FLASH_FLUSH, .first = command->first, .count = command->count};
	if (!request_flash(app, manager, &request)) {
		app_print(app, 0, "BUSY: flash operation; retry command\r\n");
		return;
	}
	if (request.operation == FLASH_ERASE) {
		manager->logging = false;
		manager->dirty = true;
	}
}

static void sensor_result(app_t *app, manager_t *manager, const app_event_t *event) {
	app_watchdog_end(&app->watchdog, APP_WATCHDOG_SENSOR);
	supervise(app);
	manager->sensor_busy = false;
	if (event->data.sensor.operation == SENSOR_SET_TIME) {
		app_print(app, 0, "%s: time set (UTC)\r\n", event->success ? "OK" : "ERROR");
		manager->next_sample = app_now_ms();
		return;
	}
	const bool changed = manager->sample.rtc_valid != event->data.sensor.sample.rtc_valid || manager->sample.climate_valid != event->data.sensor.sample.climate_valid;
	manager->sample = event->data.sensor.sample;
	manager->dirty = true;
	console_status(manager);
	if (changed)
		logger_log(&app->logger, "app", event->success ? "RTC and BME280 available" : "Sensor unavailable; invalid fields are not archived");
	const uint64_t now = app_now_ms();
	if (manager->logging && now >= manager->next_log) {
		manager->next_log += ((now - manager->next_log) / (APP_LOG_INTERVAL_MINUTES * UINT64_C(60000)) + 1) * APP_LOG_INTERVAL_MINUTES * UINT64_C(60000);
		const flash_request_t request = {.operation = FLASH_APPEND, .record = manager->sample.record};
		if (!event->success || !request_flash(app, manager, &request)) {
			++manager->skipped_logs;
			logger_warning(&app->logger, "app", "Log interval skipped: invalid measurement or storage busy");
		}
	}
}

static void flash_result(app_t *app, manager_t *manager, const app_event_t *event) {
	app_watchdog_end(&app->watchdog, APP_WATCHDOG_FLASH);
	supervise(app);
	manager->flash_busy = false;
	const bool was_full = manager->storage.full;
	manager->storage = event->data.flash.status;
	manager->dirty = true;
	if (event->data.flash.operation == FLASH_SCAN) {
		manager->loaded = true;
		if (manager->storage.last_valid) {
			manager->sample = (app_sample_t){.record = manager->storage.last, .rtc_valid = true, .climate_valid = true, .archived = true};
			manager->next_sample = app_now_ms() + 1500;
			app_print(app, 0, "Archive restored; showing last saved measurement\r\n");
		}
		logger_log(&app->logger, "app", "Startup scan complete; type status for storage details");
	} else if (event->data.flash.operation != FLASH_APPEND) {
		const char *operation = event->data.flash.operation == FLASH_ERASE ? "erase; logging remains OFF" : event->data.flash.operation == FLASH_FLUSH ? "flush" : "read";
		app_print(app, 0, "%s: %s; saved=%" PRIu32 ", RAM=%" PRIu32 "\r\n", event->success ? "OK" : "ERROR", operation, manager->storage.records, manager->storage.buffered);
		if (event->data.flash.operation == FLASH_ERASE && event->success && manager->sample.archived)
			manager->sample = (app_sample_t){0};
	}
	if (manager->storage.error || manager->storage.full)
		manager->logging = false;
	if (!event->success && event->data.flash.operation != FLASH_READ) {
		manager->logging = false;
		logger_error(&app->logger, "app", "Storage operation failed; logging stopped, RAM retained where possible");
	}
	if (manager->storage.full && !was_full)
		logger_warning(&app->logger, "app", "FLASH FULL: logging stopped; old records preserved");
}

static void finish_sleep(app_t *app, manager_t *manager, bool paused) {
	app_watchdog_end(&app->watchdog, APP_WATCHDOG_SLEEP);
	supervise(app);
	manager->pausing = false;
	manager->next_sleep_attempt = app_now_ms() + 1000;
	if (!paused)
		return;
	/* UART has acknowledged its blocking wait. Suspend only its heartbeat;
	 * Manager remains subscribed to TWDT throughout sleep entry and exit. */
	app_watchdog_end(&app->watchdog, APP_WATCHDOG_UART);
	supervise(app);
	uart_control_t resume = UART_RESUME_TIMER;
	uint64_t now = app_now_ms();
	if (manager->uart_ready && !manager->sensor_busy && !manager->display_busy && !manager->flash_busy && !manager->dirty && uxQueueMessagesWaiting(app->events) == 0 && uxQueueMessagesWaiting(app->uart_output) == 0 && manager->next_sample > now + 5) {
		uint64_t duration = manager->next_sample - now;
		if (duration > APP_MAX_SLEEP_MS)
			duration = APP_MAX_SLEEP_MS;
		esp_err_t result = esp_sleep_enable_timer_wakeup(duration * 1000);
		if (result == ESP_OK)
			result = esp_light_sleep_start();
		if (result == ESP_OK) {
			++manager->sleeps;
			if (esp_sleep_get_wakeup_causes() & (1U << ESP_SLEEP_WAKEUP_UART1))
				resume = UART_RESUME_INPUT;
		} else {
			++manager->sleep_errors;
		}
		manager->next_sleep_attempt = result == ESP_OK ? app_now_ms() : app_now_ms() + 5000;
	}
	app_watchdog_begin(&app->watchdog, APP_WATCHDOG_UART, APP_WATCHDOG_UART_MS);
	/* A bounded failed resume is still detected by the missing UART heartbeat. */
	if (xQueueSend(app->uart_controls, &resume, pdMS_TO_TICKS(100)) != pdTRUE)
		ESP_LOGE("watchdog", "UART resume queue blocked");
	supervise(app);
}

void manager_task(void *argument) {
	app_t *app = argument;
	ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
	manager_t manager = {.logging = true, .next_sample = app_now_ms(), .next_log = app_now_ms() + APP_LOG_INTERVAL_MINUTES * UINT64_C(60000)};
	const flash_request_t initial = {.operation = FLASH_SCAN};
	ESP_ERROR_CHECK(request_flash(app, &manager, &initial) ? ESP_OK : ESP_FAIL);
	for (;;) {
		/* Must run even during startup scan and UART sleep handshake. */
		supervise(app);
		app_event_t event;
		if (xQueueReceive(app->events, &event, pdMS_TO_TICKS(20)) == pdTRUE) {
			switch (event.kind) {
			case EVENT_SENSOR:
				sensor_result(app, &manager, &event);
				break;
			case EVENT_FLASH:
				flash_result(app, &manager, &event);
				break;
			case EVENT_COMMAND:
				command(app, &manager, &event.data.command);
				break;
			case EVENT_UART_STARTED:
				manager.uart_ready = event.success;
				break;
			case EVENT_UART_PAUSED:
				finish_sleep(app, &manager, event.success);
				break;
			case EVENT_DISPLAY:
				app_watchdog_end(&app->watchdog, APP_WATCHDOG_DISPLAY);
				supervise(app);
				manager.display_busy = false;
				if (manager.oled_ready != event.success)
					logger_log(&app->logger, "app", event.success ? "OLED available" : "OLED unavailable; other tasks continue");
				manager.oled_ready = event.success;
				break;
			}
		}
		supervise(app);
		if (manager.pausing || !manager.loaded)
			continue;
		const uint64_t now = app_now_ms();
		if (now >= manager.next_sample) {
			const uint64_t periods = (now - manager.next_sample) / APP_SAMPLE_PERIOD_MS + 1;
			manager.next_sample += periods * APP_SAMPLE_PERIOD_MS;
			manager.missed_cycles += (uint32_t)(periods - 1);
			const sensor_request_t request = {.operation = SENSOR_SAMPLE};
			if (!request_sensor(app, &manager, &request))
				++manager.missed_cycles;
		}
		if (manager.dirty && !manager.display_busy) {
			const display_request_t view = {.sample = manager.sample, .storage = manager.storage, .logging = manager.logging};
			app_watchdog_begin(&app->watchdog, APP_WATCHDOG_DISPLAY, APP_WATCHDOG_DISPLAY_MS);
			if (xQueueSend(app->display_requests, &view, 0) == pdTRUE) {
				manager.display_busy = true;
				manager.dirty = false;
			} else {
				app_watchdog_end(&app->watchdog, APP_WATCHDOG_DISPLAY);
			}
		}
		const bool idle = !manager.sensor_busy && !manager.display_busy && !manager.flash_busy && !manager.dirty;
		if (idle && manager.uart_ready && now >= manager.next_sleep_attempt && manager.next_sample > now + 20 && !uxQueueMessagesWaiting(app->events)) {
			/* With workers idle no producer can race the logger barrier. Complete
			 * an older timed-out marker first, then establish a fresh boundary. */
			bool flushed = logger_flush(&app->logger, pdMS_TO_TICKS(100));
			if (flushed)
				flushed = logger_flush(&app->logger, pdMS_TO_TICKS(100));
			if (flushed) {
				const uart_control_t control = UART_PREPARE_SLEEP;
				app_watchdog_begin(&app->watchdog, APP_WATCHDOG_SLEEP, APP_WATCHDOG_SLEEP_MS);
				manager.pausing = xQueueSend(app->uart_controls, &control, 0) == pdTRUE;
				if (!manager.pausing)
					app_watchdog_end(&app->watchdog, APP_WATCHDOG_SLEEP);
			}
			if (!manager.pausing)
				manager.next_sleep_attempt = now + 1000;
		}
	}
}
