#pragma once
#include "app_config.h"
#include "app_types.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "volk_core/communication/i2c_esp.h"
#include "volk_core/system/logger.h"
#include "watchdog/watchdog.h"

typedef struct app_text_t {
	char text[APP_UART_TEXT_SIZE];
} app_text_t;
/* Queues transfer values. Device instances belong to their worker task. */
typedef struct app_t {
	QueueHandle_t events;
	QueueHandle_t sensor_requests;
	QueueHandle_t display_requests;
	QueueHandle_t flash_requests;
	QueueHandle_t uart_controls;
	QueueHandle_t uart_output;
	SemaphoreHandle_t i2c_mutex;
	i2c_t i2c;
	i2c_esp_context_t i2c_hardware;
	logger_t logger;
	app_watchdog_t watchdog;
} app_t;

uint64_t app_now_ms(void);
bool app_i2c_ready(app_t *app); /* Call with i2c_mutex held. */
void app_post(app_t *app, const app_event_t *event);
bool app_print(app_t *app, TickType_t timeout, const char *format, ...) __attribute__((format(printf, 3, 4)));
void sensor_task(void *argument);
void display_task(void *argument);
void flash_task(void *argument);
void uart_task(void *argument);
void manager_task(void *argument);
