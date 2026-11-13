#pragma once
#include "sdkconfig.h"

/* Archive cadence; measurements and OLED refresh remain at 1 Hz. */
#define APP_LOG_INTERVAL_MINUTES 1U
#define APP_SAMPLE_PERIOD_MS 1000U
#define APP_FLASH_SECTOR_SIZE 4096U
#define APP_RECORD_SIZE 16U
#define APP_RECORDS_PER_SECTOR (APP_FLASH_SECTOR_SIZE / APP_RECORD_SIZE)
#define APP_PARTITION_LABEL "logdata"
#define APP_UART_PORT UART_NUM_1
#define APP_UART_BAUD 115200U
#define APP_UART_TEXT_SIZE 320U
#define APP_COMMAND_SIZE 96U
#define APP_UART_ACTIVE_MS 30000U
#define APP_READ_MAX_RECORDS 256U

/* Application deadlines precede the separate 5 s TWDT panic timeout. */
#define APP_WATCHDOG_SENSOR_MS 3000U
#define APP_WATCHDOG_DISPLAY_MS 3000U
#define APP_WATCHDOG_FLASH_MS 5000U
#define APP_WATCHDOG_UART_MS 3000U
#define APP_WATCHDOG_SLEEP_MS 3000U
/* Bound each sleep even if the sampling interval is increased later. */
#define APP_MAX_SLEEP_MS 1000U

_Static_assert(APP_LOG_INTERVAL_MINUTES > 0U, "Logging interval must be positive");
_Static_assert(APP_FLASH_SECTOR_SIZE % APP_RECORD_SIZE == 0U, "Records must fill a sector exactly");
_Static_assert(APP_MAX_SLEEP_MS < CONFIG_ESP_TASK_WDT_TIMEOUT_S * 1000U / 2U, "Light Sleep must leave time for TWDT supervision");
