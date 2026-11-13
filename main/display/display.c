#include "app.h"
#include "font.h"
#include "time/app_time.h"
#include "volk_core/devices/oled_SSD1306.h"
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

static void text(oled_SSD1306_t *oled, int x, int y, const char *value, unsigned scale) {
	for (; *value && x < 128; ++value, x += 6 * (int)scale) {
		const uint8_t *columns = glyph_columns(*value);
		for (unsigned column = 0; column < 5; ++column)
			for (unsigned row = 0; row < 7; ++row) {
				if (!(columns[column] & (1U << row)))
					continue;
				for (unsigned dx = 0; dx < scale; ++dx)
					for (unsigned dy = 0; dy < scale; ++dy) {
						int px = x + (int)(column * scale + dx), py = y + (int)(row * scale + dy);
						if (px >= 0 && px < 128 && py >= 0 && py < 64)
							oled_SSD1306_set_pixel(oled, (uint8_t)px, (uint8_t)py, true);
					}
			}
	}
}

static void draw(oled_SSD1306_t *oled, const display_request_t *view) {
	char line[32], date[24] = "---- -- -- --:--:--";
	const app_sample_t *sample = &view->sample;
	const char *mode = view->storage.error ? "ERROR" : view->storage.full ? "FULL" : view->logging ? "ON" : "OFF";
	oled_SSD1306_clear(oled, false);
	snprintf(line, sizeof(line), "LOG %s  RAM:%" PRIu32, mode, view->storage.buffered);
	text(oled, 0, 0, line, 1);
	if (sample->rtc_valid)
		app_time_format(sample->record.timestamp, date, sizeof(date), true);
	snprintf(line, sizeof(line), "%.10s %s", date, sample->archived ? "ARCHIVE" : sample->rtc_valid ? "" : "RTC ERR");
	text(oled, 0, 8, line, 1);
	/* Keep large time digits below the yellow band (rows 0..15). */
	text(oled, 16, 18, sample->rtc_valid ? date + 11 : "--:--:--", 2);
	if (sample->climate_valid) {
		snprintf(line, sizeof(line), "T:%.2f C H:%.1f%%", sample->record.temperature / 100.0, sample->record.humidity / 100.0);
		text(oled, 0, 36, line, 1);
		snprintf(line, sizeof(line), "P:%" PRIu32 " mmHg", sample->record.pressure);
	} else {
		text(oled, 0, 36, "BME280 ERROR", 1);
		snprintf(line, sizeof(line), "T:-- H:-- P:--");
	}
	text(oled, 0, 45, line, 1);
	snprintf(line, sizeof(line), "%" PRIu32 "/%" PRIu32 " KiB  N:%u m", view->storage.used_bytes / 1024, view->storage.size / 1024, APP_LOG_INTERVAL_MINUTES);
	text(oled, 0, 56, line, 1);
}

void display_task(void *argument) {
	app_t *app = argument;
	static oled_SSD1306_t oled;
	bool available = false;
	uint64_t retry_at = 0;
	ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
	display_request_t view;
	for (;;) {
		xQueueReceive(app->display_requests, &view, portMAX_DELAY);
		app_event_t reply = {.kind = EVENT_DISPLAY};
		if (app_now_ms() >= retry_at && xSemaphoreTake(app->i2c_mutex, pdMS_TO_TICKS(250)) == pdTRUE) {
			if (!available && app_i2c_ready(app)) {
				if (!oled.initialized || oled_SSD1306_deinit(&oled) == I2C_RESULT_OK) {
					const oled_SSD1306_config_t config = {.bus = &app->i2c, .address = CONFIG_EDL_OLED_ADDRESS, .height = 64};
					available = oled_SSD1306_init(&oled, &config) == I2C_RESULT_OK;
					if (available)
						available = oled_SSD1306_set_contrast(&oled, CONFIG_EDL_OLED_CONTRAST) == I2C_RESULT_OK;
				}
			}
			if (available) {
				draw(&oled, &view);
				available = oled_SSD1306_update(&oled) == I2C_RESULT_OK;
			}
			xSemaphoreGive(app->i2c_mutex);
			if (!available)
				retry_at = app_now_ms() + 5000;
			reply.success = available;
		}
		app_post(app, &reply);
	}
}
