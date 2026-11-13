#pragma once
#include "esp_err.h"
#include <stdbool.h>
#include <stdint.h>

typedef struct app_record_t {
	uint64_t timestamp;
	int16_t temperature;
	uint16_t humidity;
	uint32_t pressure;
} app_record_t;

typedef struct app_sample_t {
	app_record_t record;
	bool rtc_valid;
	bool climate_valid;
	bool archived;
} app_sample_t;

typedef enum app_command_kind_t { APP_STATUS, APP_LOG_ON, APP_LOG_OFF, APP_FLUSH, APP_ERASE, APP_READ, APP_TIME_SET, APP_HELP } app_command_kind_t;
typedef struct app_command_t {
	app_command_kind_t kind;
	uint64_t timestamp;
	uint32_t first;
	uint32_t count;
} app_command_t;

typedef struct app_storage_status_t {
	uint32_t size;
	uint32_t used_bytes;
	uint32_t records;
	uint32_t buffered;
	uint32_t invalid_records;
	esp_err_t error;
	bool last_valid;
	app_record_t last;
} app_storage_status_t;

typedef enum sensor_operation_t { SENSOR_SAMPLE, SENSOR_SET_TIME } sensor_operation_t;
typedef struct sensor_request_t {
	sensor_operation_t operation;
	uint64_t timestamp;
} sensor_request_t;
typedef enum flash_operation_t { FLASH_SCAN, FLASH_APPEND, FLASH_FLUSH, FLASH_ERASE, FLASH_READ } flash_operation_t;
typedef struct flash_request_t {
	flash_operation_t operation;
	app_record_t record;
	uint32_t first;
	uint32_t count;
} flash_request_t;

typedef struct display_request_t {
	app_sample_t sample;
	app_storage_status_t storage;
	bool logging;
} display_request_t;
typedef enum uart_control_t { UART_PREPARE_SLEEP, UART_RESUME_TIMER, UART_RESUME_INPUT } uart_control_t;
typedef enum app_event_kind_t { EVENT_SENSOR, EVENT_FLASH, EVENT_DISPLAY, EVENT_COMMAND, EVENT_UART_STARTED, EVENT_UART_PAUSED } app_event_kind_t;
typedef struct app_event_t {
	app_event_kind_t kind;
	bool success;
	union {
		struct {
			sensor_operation_t operation;
			app_sample_t sample;
		} sensor;
		struct {
			flash_operation_t operation;
			app_storage_status_t status;
		} flash;
		app_command_t command;
	} data;
} app_event_t;
