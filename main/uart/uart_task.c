#include "app.h"
#include "commands.h"
#include "driver/uart_wakeup.h"
#include "esp_sleep.h"
#include "volk_core/communication/uart_esp.h"
#include <stdio.h>
#include <string.h>

typedef struct uart_state_t {
	app_t *app;
	uart_t uart;
	uart_esp_context_t hardware;
	uart_setup_t configuration;
	uint8_t rx[128], tx[APP_UART_TEXT_SIZE];
	char line[APP_COMMAND_SIZE];
	size_t length;
	bool overflow;
	bool tx_busy;
	bool synchronize;
	uint64_t active_until;
	uint64_t tx_started;
	uint64_t retry_at;
} uart_state_t;

static void ready(uart_state_t *state) {
	state->active_until = app_now_ms() + APP_UART_ACTIVE_MS;
	(void)app_print(state->app, 0, "READY (30 s idle timeout). Type help.\r\n");
}

static void received(void *context, void *argument) {
	uart_state_t *state = context;
	const uint8_t *bytes = argument;
	if (app_now_ms() >= state->active_until) {
		state->synchronize = true;
		state->length = 0;
		state->overflow = false;
	}
	state->active_until = app_now_ms() + APP_UART_ACTIVE_MS;
	for (size_t i = 0; i < uart_get_received_size(&state->uart); ++i) {
		const uint8_t character = bytes[i];
		if (character == '\r')
			continue;
		if (state->synchronize) {
			if (character == '\n') {
				state->synchronize = false;
				ready(state);
			}
			continue;
		}
		if (character == '\n') {
			state->line[state->length] = '\0';
			if (state->overflow)
				(void)app_print(state->app, 0, "ERROR: line too long or invalid byte; discarded\r\n");
			else if (state->length == 0 || strspn(state->line, "U") == state->length)
				ready(state);
			else {
				app_event_t event = {.kind = EVENT_COMMAND};
				if (!command_parse(state->line, &event.data.command))
					(void)app_print(state->app, 0, "ERROR: invalid command; type help\r\n");
				else if (xQueueSend(state->app->events, &event, 0) != pdTRUE)
					(void)app_print(state->app, 0, "BUSY: command queue full; retry\r\n");
			}
			state->length = 0;
			state->overflow = false;
		} else if (!state->overflow && (character == 8 || character == 127)) {
			if (state->length)
				--state->length;
		} else if (!state->overflow) {
			if ((character < 32 && character != '\t') || character > 126 || state->length + 1 >= sizeof(state->line))
				state->overflow = true;
			else
				state->line[state->length++] = (char)character;
		}
	}
}

static void transmitted(void *context, void *argument) {
	(void)argument;
	((uart_state_t *)context)->tx_busy = false;
}

static bool initialize(uart_state_t *state) {
	if (state->uart.initialized && uart_deinit(&state->uart) != UART_RESULT_OK)
		return false;
	state->tx_busy = false;
	state->length = 0;
	state->overflow = false;
	state->synchronize = false;
	const bool initialized = uart_init(&state->uart, &state->configuration) == UART_RESULT_OK;
	/* Only the port owner configures sleep policy; all RX/TX stays in uart_t. */
	const uart_wakeup_cfg_t wake = {.wakeup_mode = UART_WK_MODE_ACTIVE_THRESH, .rx_edge_threshold = 3};
	const bool wake_ready = initialized && uart_wakeup_setup(APP_UART_PORT, &wake) == ESP_OK && esp_sleep_enable_uart_wakeup(APP_UART_PORT) == ESP_OK;
	const app_event_t started = {.kind = EVENT_UART_STARTED, .success = wake_ready};
	app_post(state->app, &started);
	if (initialized) {
		ready(state);
		if (!wake_ready)
			(void)app_print(state->app, 0, "ERROR: UART wakeup unavailable; Light Sleep disabled\r\n");
	}
	return initialized;
}

static void pump(uart_state_t *state) {
	if (!state->uart.initialized) {
		if (app_now_ms() >= state->retry_at) {
			state->retry_at = app_now_ms() + 5000;
			(void)initialize(state);
		}
		return;
	}
	uart_result_t result = uart_process(&state->uart);
	if (result == UART_RESULT_IO_ERROR || (state->tx_busy && app_now_ms() > state->tx_started + 2000)) {
		state->retry_at = app_now_ms() + 5000;
		(void)initialize(state);
		return;
	}
	if (result != UART_RESULT_OK && result != UART_RESULT_BUSY) {
		state->length = 0;
		state->overflow = false;
		state->synchronize = true;
		/* Reset the receive stream after an overflow; commands spanning it are invalid. */
		(void)uart_reset_receive(&state->uart);
		(void)app_print(state->app, 0, "RX ERROR: send UUU + LF, wait READY, then retry command\r\n");
	}
	if (!state->tx_busy) {
		app_text_t message;
		if (xQueueReceive(state->app->uart_output, &message, 0) == pdTRUE) {
			state->tx_busy = uart_send(&state->uart, message.text, strlen(message.text)) == UART_RESULT_OK;
			state->tx_started = app_now_ms();
		}
	}
}

void uart_task(void *argument) {
	app_t *app = argument;
	static uart_state_t state;
	state.app = app;
	ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
	state.configuration = (uart_setup_t){.adapter = uart_esp_create(&state.hardware, APP_UART_PORT, CONFIG_EDL_UART_TX_GPIO, CONFIG_EDL_UART_RX_GPIO, 2048), .baud_rate = APP_UART_BAUD, .rx_buffer = state.rx, .rx_buffer_capacity = sizeof(state.rx), .tx_buffer = state.tx, .tx_buffer_capacity = sizeof(state.tx), .callback_context = &state, .on_receive = received, .on_transmit = transmitted};
	if (!initialize(&state))
		printf("Environmental Data Logger: UART0 initialization failed; check menuconfig\n");
	for (;;) {
		pump(&state);
		app_watchdog_progress(&app->watchdog, APP_WATCHDOG_UART);
		uart_control_t control;
		if (xQueueReceive(app->uart_controls, &control, 0) == pdTRUE && control == UART_PREPARE_SLEEP) {
			app_event_t reply = {.kind = EVENT_UART_PAUSED};
			const uint64_t deadline = app_now_ms() + 1500;
			while (app_now_ms() >= state.active_until && (state.tx_busy || uxQueueMessagesWaiting(app->uart_output)) && app_now_ms() < deadline) {
				pump(&state);
				app_watchdog_progress(&app->watchdog, APP_WATCHDOG_UART);
				vTaskDelay(1);
			}
			reply.success = state.uart.initialized && app_now_ms() >= state.active_until && !state.tx_busy && !uxQueueMessagesWaiting(app->uart_output);
			app_post(app, &reply);
			if (reply.success) {
				/* All producers are quiescent. Manager resumes us on every exit,
				 * including a rejected sleep or a command arriving during handshake. */
				xQueueReceive(app->uart_controls, &control, portMAX_DELAY);
				state.length = 0;
				state.overflow = false;
				if (control == UART_RESUME_INPUT) {
					(void)uart_reset_receive(&state.uart);
					state.synchronize = false;
					ready(&state);
				}
			}
		}
		vTaskDelay(1);
	}
}
