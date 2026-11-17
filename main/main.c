#include "app.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_system.h"
#include "volk_core/timing/time_counter_esp.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

uint64_t app_now_ms(void) {
	const time_counter_t clock = time_counter_esp_create();
	return clock.get_milliseconds(clock.context);
}

void app_post(app_t *app, const app_event_t *event) { (void)xQueueSend(app->events, event, portMAX_DELAY); }

bool app_print(app_t *app, TickType_t timeout, const char *format, ...) {
	app_text_t message;
	va_list arguments;
	va_start(arguments, format);
	const int length = vsnprintf(message.text, sizeof(message.text), format, arguments);
	va_end(arguments);
	if (length < 0)
		return false;
	if ((size_t)length >= sizeof(message.text)) {
		message.text[sizeof(message.text) - 3] = '\r';
		message.text[sizeof(message.text) - 2] = '\n';
	}
	return xQueueSend(app->uart_output, &message, timeout) == pdTRUE;
}

static void diagnostic_sender(void *context, log_message_type_t type, const char *tag, const char *text) {
	(void)context;
	static const char *const levels[] = {"LOG", "WARN", "ERROR"};
	const unsigned level = (unsigned)type <= LOG_MESSAGE_TYPE_ERROR ? (unsigned)type : LOG_MESSAGE_TYPE_ERROR;
	printf("[%s][%s] %s\n", levels[level], tag, text);
}

bool app_i2c_ready(app_t *app) {
	if (app->i2c.initialized)
		return true;
	i2c_setup_t config = i2c_default_configuration(i2c_esp_create(&app->i2c_hardware, I2C_NUM_0, CONFIG_EDL_SDA_GPIO, CONFIG_EDL_SCL_GPIO));
	config.timeout_ms = 25;
	config.enable_logs = false;
	return i2c_init(&app->i2c, &config) == I2C_RESULT_OK;
}

static bool pins_valid(void) {
	const int outputs[] = {CONFIG_EDL_SDA_GPIO, CONFIG_EDL_SCL_GPIO, CONFIG_EDL_MOSI_GPIO, CONFIG_EDL_SCLK_GPIO, CONFIG_EDL_CS_GPIO, CONFIG_EDL_UART_TX_GPIO};
	const int pins[] = {CONFIG_EDL_SDA_GPIO, CONFIG_EDL_SCL_GPIO, CONFIG_EDL_MOSI_GPIO, CONFIG_EDL_SCLK_GPIO, CONFIG_EDL_CS_GPIO, CONFIG_EDL_UART_TX_GPIO, CONFIG_EDL_MISO_GPIO, CONFIG_EDL_UART_RX_GPIO};
	for (size_t i = 0; i < sizeof(outputs) / sizeof(outputs[0]); ++i)
		if (!GPIO_IS_VALID_OUTPUT_GPIO(outputs[i]))
			return false;
	for (size_t i = 0; i < sizeof(pins) / sizeof(pins[0]); ++i) {
		if (!GPIO_IS_VALID_GPIO(pins[i]))
			return false;
		for (size_t j = 0; j < i; ++j)
			if (pins[i] == pins[j])
				return false;
	}
	return true;
}

void app_main(void) {
	static app_t app;
	const esp_reset_reason_t reset_reason = esp_reset_reason();
	ESP_LOGI("boot", "Reset reason=%d%s", (int)reset_reason, reset_reason == ESP_RST_TASK_WDT ? " (Task WDT)" : reset_reason == ESP_RST_INT_WDT ? " (Interrupt WDT)" : reset_reason == ESP_RST_PANIC ? " (panic)" : "");
	if (!pins_valid()) {
		printf("Environmental Data Logger: invalid or overlapping GPIO configuration\n");
		return;
	}
	setenv("TZ", CONFIG_EDL_TIMEZONE, 1);
	tzset();
	app.events = xQueueCreate(16, sizeof(app_event_t));
	app.sensor_requests = xQueueCreate(1, sizeof(sensor_request_t));
	app.display_requests = xQueueCreate(1, sizeof(display_request_t));
	app.flash_requests = xQueueCreate(1, sizeof(flash_request_t));
	app.uart_controls = xQueueCreate(2, sizeof(uart_control_t));
	app.uart_output = xQueueCreate(16, sizeof(app_text_t));
	app.i2c_mutex = xSemaphoreCreateMutex();
	const logger_config_t logger_config = {.log_sender = {.context = &app, .send = diagnostic_sender}, .enable_logs = true, .log_level = LOGGER_LOG_LEVEL_LOG};
	TaskHandle_t tasks[5] = {0};
	const TaskFunction_t functions[] = {sensor_task, display_task, flash_task, uart_task, manager_task};
	const char *const names[] = {"sensor", "display", "flash_writer", "uart_commands", "manager"};
	const uint32_t stacks[] = {6144, 4096, 6144, 6144, 6144};
	bool ready = app.events && app.sensor_requests && app.display_requests && app.flash_requests && app.uart_controls && app.uart_output && app.i2c_mutex;
	if (ready)
		ready = logger_init(&app.logger, &logger_config) && logger_add_log_tag(&app.logger, "app");
	for (unsigned i = 0; ready && i < 5; ++i)
		ready = xTaskCreate(functions[i], names[i], stacks[i], &app, i == 4 ? 3 : 2, &tasks[i]) == pdPASS;
	if (!ready) {
		/* Workers have not crossed their start notification, so own no devices yet. */
		for (unsigned i = 0; i < 5; ++i)
			if (tasks[i])
				vTaskDelete(tasks[i]);
		if (app.logger.initialized)
			(void)logger_deinit(&app.logger, portMAX_DELAY);
		QueueHandle_t queues[] = {app.events, app.sensor_requests, app.display_requests, app.flash_requests, app.uart_controls, app.uart_output};
		for (unsigned i = 0; i < sizeof(queues) / sizeof(queues[0]); ++i)
			if (queues[i])
				vQueueDelete(queues[i]);
		if (app.i2c_mutex)
			vSemaphoreDelete(app.i2c_mutex);
		printf("Environmental Data Logger: cannot allocate task resources\n");
		return;
	}
	ESP_ERROR_CHECK(app_watchdog_init(&app.watchdog, tasks[4]));
	app_watchdog_begin(&app.watchdog, APP_WATCHDOG_UART, APP_WATCHDOG_UART_MS);
	for (unsigned i = 0; i < 5; ++i)
		xTaskNotifyGive(tasks[i]);
}
