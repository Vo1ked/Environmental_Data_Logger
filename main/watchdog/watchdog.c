#include "watchdog.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"

static const char *const channel_names[APP_WATCHDOG_CHANNEL_COUNT] = {"sensor", "flash_writer", "display", "uart", "sleep_handshake"};

/* Call with lock held. A late reply/progress notification must not erase a fault. */
static void check_deadline(app_watchdog_t *watchdog, app_watchdog_channel_t channel, uint64_t now) {
	const app_watchdog_entry_t *entry = &watchdog->entries[channel];
	if (entry->active && now >= entry->deadline_ms)
		watchdog->failed_mask |= UINT32_C(1) << channel;
}

esp_err_t app_watchdog_init(app_watchdog_t *watchdog, TaskHandle_t manager_task) {
	*watchdog = (app_watchdog_t){.lock = portMUX_INITIALIZER_UNLOCKED};
	const esp_task_wdt_config_t config = {.timeout_ms = CONFIG_ESP_TASK_WDT_TIMEOUT_S * 1000U, .idle_core_mask = (UINT32_C(1) << portNUM_PROCESSORS) - 1U, .trigger_panic = true};
	esp_err_t result = esp_task_wdt_reconfigure(&config);
	if (result == ESP_ERR_INVALID_STATE)
		result = esp_task_wdt_init(&config);
	if (result == ESP_OK)
		result = esp_task_wdt_add(manager_task);
	return result;
}

void app_watchdog_begin(app_watchdog_t *watchdog, app_watchdog_channel_t channel, uint32_t timeout_ms) {
	portENTER_CRITICAL(&watchdog->lock);
	const uint64_t now = (uint64_t)esp_timer_get_time() / 1000U;
	check_deadline(watchdog, channel, now);
	/* Retrying a pending request must not continually move its deadline. */
	if (!watchdog->entries[channel].active)
		watchdog->entries[channel] = (app_watchdog_entry_t){.deadline_ms = now + timeout_ms, .timeout_ms = timeout_ms, .active = true};
	portEXIT_CRITICAL(&watchdog->lock);
}

void app_watchdog_progress(app_watchdog_t *watchdog, app_watchdog_channel_t channel) {
	portENTER_CRITICAL(&watchdog->lock);
	const uint64_t now = (uint64_t)esp_timer_get_time() / 1000U;
	check_deadline(watchdog, channel, now);
	app_watchdog_entry_t *entry = &watchdog->entries[channel];
	if (entry->active && !(watchdog->failed_mask & (UINT32_C(1) << channel)))
		entry->deadline_ms = now + entry->timeout_ms;
	portEXIT_CRITICAL(&watchdog->lock);
}

void app_watchdog_end(app_watchdog_t *watchdog, app_watchdog_channel_t channel) {
	portENTER_CRITICAL(&watchdog->lock);
	check_deadline(watchdog, channel, (uint64_t)esp_timer_get_time() / 1000U);
	watchdog->entries[channel].active = false;
	portEXIT_CRITICAL(&watchdog->lock);
}

bool app_watchdog_check(app_watchdog_t *watchdog) {
	portENTER_CRITICAL(&watchdog->lock);
	const uint64_t now = (uint64_t)esp_timer_get_time() / 1000U;
	for (unsigned channel = 0; channel < APP_WATCHDOG_CHANNEL_COUNT; ++channel)
		check_deadline(watchdog, (app_watchdog_channel_t)channel, now);
	const bool healthy = watchdog->failed_mask == 0;
	portEXIT_CRITICAL(&watchdog->lock);
	if (healthy)
		ESP_ERROR_CHECK(esp_task_wdt_reset());
	return healthy;
}

void app_watchdog_wait_for_reset(app_watchdog_t *watchdog) {
	portENTER_CRITICAL(&watchdog->lock);
	const uint32_t failed_mask = watchdog->failed_mask;
	portEXIT_CRITICAL(&watchdog->lock);
	/* Use the system console; the asynchronous logger/UART may be the failed worker. */
	for (unsigned channel = 0; channel < APP_WATCHDOG_CHANNEL_COUNT; ++channel)
		if (failed_mask & (UINT32_C(1) << channel))
			ESP_LOGE("watchdog", "Deadline exceeded: %s; Manager stopped feeding TWDT, waiting for panic/reset", channel_names[channel]);
	/* Keep Idle tasks runnable: this proves the subscribed Manager causes the reset. */
	for (;;)
		vTaskDelay(pdMS_TO_TICKS(100));
}
