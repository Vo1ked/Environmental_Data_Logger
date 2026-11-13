idf_component_register(
    SRCS
        "main.c"
        "time/app_time.c"
        "sensor/sensor.c"
        "display/display.c"
        "storage/record.c"
        "storage/flash_log.c"
        "uart/commands.c"
        "uart/uart_task.c"
        "manager/manager.c"
        "watchdog/watchdog.c"
    INCLUDE_DIRS "."
    REQUIRES
        climate_bme280 rts_ds1307 oled_SSD1306 i2c_esp spi_esp
        uart uart_esp logger time_counter esp_partition esp_hw_support
        esp_driver_gpio esp_driver_uart esp_system esp_timer
)

set(build_time_header "${CMAKE_CURRENT_BINARY_DIR}/app_build_time.h")
add_custom_target(edl_build_timestamp
    COMMAND "${CMAKE_COMMAND}" "-DOUTPUT_FILE=${build_time_header}"
        -P "${CMAKE_CURRENT_SOURCE_DIR}/time/write_build_time.cmake"
    BYPRODUCTS "${build_time_header}"
    VERBATIM
)
add_dependencies(${COMPONENT_LIB} edl_build_timestamp)
target_include_directories(${COMPONENT_LIB} PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
