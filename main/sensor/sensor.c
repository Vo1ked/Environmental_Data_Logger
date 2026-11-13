#include "app.h"
#include "app_build_time.h"
#include "time/app_time.h"
#include "volk_core/communication/spi_esp.h"
#include "volk_core/devices/climate_bme280.h"
#include "volk_core/timing/time_counter_esp.h"
#include <math.h>

typedef struct sensor_state_t {
	spi_t spi;
	spi_esp_context_t hardware;
	climate_bme280_t climate;
	rts_ds1307_t rtc;
	uint64_t retry_at;
	bool climate_cleanup_pending;
} sensor_state_t;

static uint8_t decimal(uint8_t bcd) { return (uint8_t)((bcd >> 4U) * 10U + (bcd & 15U)); }

/* get_time() reports both malformed registers and transport faults as IO_ERROR.
 * Inspect a successful raw read only on that recovery path, so a transient I/O
 * error cannot reset an otherwise running valid clock to an old build date. */
static bool rtc_registers_need_initialization(const uint8_t bytes[7]) {
	if (bytes[0] & 0x80U)
		return true;
	const uint8_t hour = bytes[2] & ((bytes[2] & 0x40U) ? 0x1fU : 0x3fU);
	const uint8_t bcd[] = {bytes[0], bytes[1], hour, bytes[4], bytes[5], bytes[6]};
	for (unsigned i = 0; i < sizeof(bcd); ++i)
		if ((bcd[i] & 15U) > 9U || (bcd[i] >> 4U) > 9U)
			return true;
	if ((bytes[2] & 0x80U) || bytes[3] < 1 || bytes[3] > 7)
		return true;
	rts_ds1307_time_t rtc = {.year = (uint16_t)(2000U + decimal(bytes[6])), .month = decimal(bytes[5]), .day = decimal(bytes[4]), .hour = decimal(hour), .minute = decimal(bytes[1]), .second = decimal(bytes[0]), .running = true};
	if (bytes[2] & 0x40U) {
		if (rtc.hour < 1 || rtc.hour > 12)
			return true;
		rtc.hour = (uint8_t)(rtc.hour % 12U + ((bytes[2] & 0x20U) ? 12U : 0U));
	}
	uint64_t timestamp;
	return !app_time_from_rtc(&rtc, &timestamp);
}

static bool rtc_ready(app_t *app, sensor_state_t *state) {
	if (!app_i2c_ready(app))
		return false;
	if (state->rtc.initialized)
		return true;
	const rts_ds1307_config_t config = {.bus = &app->i2c, .base_year = 2000};
	return rts_ds1307_init(&state->rtc, &config) == I2C_RESULT_OK;
}

static bool rtc_read(app_t *app, sensor_state_t *state, uint64_t *timestamp) {
	if (!rtc_ready(app, state))
		return false;
	rts_ds1307_time_t rtc = {0};
	i2c_result_t result = rts_ds1307_get_time(&state->rtc, &rtc);
	if (result == I2C_RESULT_OK && app_time_from_rtc(&rtc, timestamp))
		return true;
	if (result != I2C_RESULT_OK) {
		uint8_t address = 0, registers[7];
		if (result != I2C_RESULT_IO_ERROR || i2c_send_receive(&state->rtc.device, &address, 1, registers, sizeof(registers)) != I2C_RESULT_OK || !rtc_registers_need_initialization(registers))
			return false;
	}
	uint64_t initial = APP_BUILD_UNIX_TIME;
	if (CONFIG_EDL_INITIAL_UTC[0] && !app_time_parse(CONFIG_EDL_INITIAL_UTC, &initial))
		return false;
	if (!app_time_to_rtc(initial, &rtc) || rts_ds1307_set_time(&state->rtc, &rtc) != I2C_RESULT_OK)
		return false;
	logger_warning(&app->logger, "app", "RTC initialized from configured/build UTC (approximate); use time set for correction");
	return rts_ds1307_get_time(&state->rtc, &rtc) == I2C_RESULT_OK && app_time_from_rtc(&rtc, timestamp);
}

static bool climate_read(sensor_state_t *state, app_record_t *record) {
	if (app_now_ms() < state->retry_at)
		return false;
	if (state->climate_cleanup_pending) {
		state->climate_cleanup_pending = climate_bme280_deinit(&state->climate) != SPI_RESULT_OK;
		if (state->climate_cleanup_pending) {
			state->retry_at = app_now_ms() + 5000;
			return false;
		}
	}
	if (!state->spi.initialized) {
		spi_setup_t config = spi_default_configuration(spi_esp_create(&state->hardware, SPI2_HOST, CONFIG_EDL_MOSI_GPIO, CONFIG_EDL_MISO_GPIO, CONFIG_EDL_SCLK_GPIO));
		config.enable_logs = false;
		if (spi_init(&state->spi, &config) != SPI_RESULT_OK) {
			state->retry_at = app_now_ms() + 5000;
			return false;
		}
	}
	if (!state->climate.initialized) {
		const climate_bme280_config_t config = {.bus = &state->spi, .cs_pin = CONFIG_EDL_CS_GPIO, .clock_speed_hz = 1000000, .time_counter = time_counter_esp_create()};
		if (climate_bme280_init(&state->climate, &config) != SPI_RESULT_OK)
			goto failed;
	}
	const uint64_t deadline = app_now_ms() + 250;
	spi_result_t result;
	do {
		result = climate_bme280_start_measurement(&state->climate);
		if (result == SPI_RESULT_BUSY)
			vTaskDelay(1);
	} while (result == SPI_RESULT_BUSY && app_now_ms() < deadline);
	if (result != SPI_RESULT_OK)
		goto failed;
	climate_bme280_reading_t reading;
	do {
		result = climate_bme280_read(&state->climate, &reading);
		if (result == SPI_RESULT_BUSY)
			vTaskDelay(1);
	} while (result == SPI_RESULT_BUSY && app_now_ms() < deadline);
	if (result != SPI_RESULT_OK)
		goto failed;
	record->temperature = (int16_t)lroundf(reading.temperature_celsius * 100.0f);
	record->humidity = (uint16_t)lroundf(reading.humidity_percent * 100.0f);
	record->pressure = (uint32_t)lroundf(reading.pressure_hpa * 0.750061683f);
	return true;
failed:
	if (state->climate.initialized)
		state->climate_cleanup_pending = climate_bme280_deinit(&state->climate) != SPI_RESULT_OK;
	state->retry_at = app_now_ms() + 5000;
	return false;
}

void sensor_task(void *argument) {
	app_t *app = argument;
	static sensor_state_t state;
	ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
	sensor_request_t request;
	for (;;) {
		xQueueReceive(app->sensor_requests, &request, portMAX_DELAY);
		app_event_t reply = {.kind = EVENT_SENSOR};
		reply.data.sensor.operation = request.operation;
		if (request.operation == SENSOR_SAMPLE)
			reply.data.sensor.sample.climate_valid = climate_read(&state, &reply.data.sensor.sample.record);
		if (xSemaphoreTake(app->i2c_mutex, pdMS_TO_TICKS(250)) == pdTRUE) {
			if (request.operation == SENSOR_SET_TIME) {
				rts_ds1307_time_t rtc;
				reply.success = rtc_ready(app, &state) && app_time_to_rtc(request.timestamp, &rtc) && rts_ds1307_set_time(&state.rtc, &rtc) == I2C_RESULT_OK;
			} else {
				reply.data.sensor.sample.rtc_valid = rtc_read(app, &state, &reply.data.sensor.sample.record.timestamp);
				reply.success = reply.data.sensor.sample.rtc_valid && reply.data.sensor.sample.climate_valid;
			}
			xSemaphoreGive(app->i2c_mutex);
		}
		app_post(app, &reply);
	}
}
