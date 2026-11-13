#pragma once
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdbool.h>
#include <stdint.h>

typedef enum app_watchdog_channel_t { APP_WATCHDOG_SENSOR, APP_WATCHDOG_FLASH, APP_WATCHDOG_DISPLAY, APP_WATCHDOG_UART, APP_WATCHDOG_SLEEP, APP_WATCHDOG_CHANNEL_COUNT } app_watchdog_channel_t;

typedef struct app_watchdog_entry_t {
	uint64_t deadline_ms;
	uint32_t timeout_ms;
	bool active;
} app_watchdog_entry_t;

typedef struct app_watchdog_t {
	portMUX_TYPE lock;
	app_watchdog_entry_t entries[APP_WATCHDOG_CHANNEL_COUNT];
	uint32_t failed_mask;
} app_watchdog_t;

/* Initialize before releasing worker start notifications. Only Manager feeds TWDT. */
esp_err_t app_watchdog_init(app_watchdog_t *watchdog, TaskHandle_t manager_task);
void app_watchdog_begin(app_watchdog_t *watchdog, app_watchdog_channel_t channel, uint32_t timeout_ms);
void app_watchdog_progress(app_watchdog_t *watchdog, app_watchdog_channel_t channel);
void app_watchdog_end(app_watchdog_t *watchdog, app_watchdog_channel_t channel);
/* Manager only: latch overdue channels and feed TWDT only while all are healthy. */
bool app_watchdog_check(app_watchdog_t *watchdog);
/* Manager only: stop new work and wait awake for the actual TWDT panic/reset. */
void app_watchdog_wait_for_reset(app_watchdog_t *watchdog);
