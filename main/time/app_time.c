#include "app_time.h"
#include <ctype.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#define EPOCH_2000 UINT64_C(946684800)
#define EPOCH_2100 UINT64_C(4102444800)

static unsigned month_days(unsigned year, unsigned month) {
	static const uint8_t days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
	return days[month - 1U] + (month == 2U && year % 4U == 0U);
}

bool app_time_from_rtc(const rts_ds1307_time_t *rtc, uint64_t *timestamp) {
	if (!rtc || !timestamp || !rtc->running || rtc->year < 2000 || rtc->year > 2099 || rtc->month < 1 || rtc->month > 12 || rtc->day < 1 || rtc->day > month_days(rtc->year, rtc->month) || rtc->hour > 23 || rtc->minute > 59 || rtc->second > 59)
		return false;
	uint64_t days = 0;
	for (unsigned year = 2000; year < rtc->year; ++year)
		days += year % 4U == 0U ? 366U : 365U;
	for (unsigned month = 1; month < rtc->month; ++month)
		days += month_days(rtc->year, month);
	days += rtc->day - 1U;
	*timestamp = EPOCH_2000 + days * 86400U + rtc->hour * 3600U + rtc->minute * 60U + rtc->second;
	return true;
}

bool app_time_to_rtc(uint64_t timestamp, rts_ds1307_time_t *rtc) {
	if (!rtc || timestamp < EPOCH_2000 || timestamp >= EPOCH_2100)
		return false;
	uint32_t days = (uint32_t)((timestamp - EPOCH_2000) / 86400U);
	unsigned year = 2000, month = 1;
	while (days >= (year % 4U == 0U ? 366U : 365U)) {
		days -= year % 4U == 0U ? 366U : 365U;
		++year;
	}
	while (days >= month_days(year, month)) {
		days -= month_days(year, month);
		++month;
	}
	*rtc = (rts_ds1307_time_t){.year = (uint16_t)year, .month = (uint8_t)month, .day = (uint8_t)(days + 1U), .weekday = (uint8_t)((timestamp / 86400U + 3U) % 7U + 1U), .hour = (uint8_t)(timestamp / 3600U % 24U), .minute = (uint8_t)(timestamp / 60U % 60U), .second = (uint8_t)(timestamp % 60U), .running = true};
	return true;
}

bool app_time_parse(const char *text, uint64_t *timestamp) {
	if (!text || strlen(text) != 20 || text[4] != '-' || text[7] != '-' || text[10] != 'T' || text[13] != ':' || text[16] != ':' || text[19] != 'Z')
		return false;
	for (unsigned i = 0; i < 19; ++i)
		if (i != 4 && i != 7 && i != 10 && i != 13 && i != 16 && !isdigit((unsigned char)text[i]))
			return false;
	unsigned y, m, d, h, min, s;
	if (sscanf(text, "%4u-%2u-%2uT%2u:%2u:%2uZ", &y, &m, &d, &h, &min, &s) != 6)
		return false;
	const rts_ds1307_time_t rtc = {.year = (uint16_t)y, .month = (uint8_t)m, .day = (uint8_t)d, .hour = (uint8_t)h, .minute = (uint8_t)min, .second = (uint8_t)s, .running = true};
	return app_time_from_rtc(&rtc, timestamp);
}

void app_time_format_uart(uint64_t timestamp, char *text, size_t capacity) {
	if (!capacity)
		return;
	text[0] = '\0';
	time_t seconds = (time_t)timestamp;
	struct tm fields;
	char date[20], offset[8];
	if (!localtime_r(&seconds, &fields) || !strftime(date, sizeof(date), "%H:%M:%S %d-%m-%Y", &fields) || !strftime(offset, sizeof(offset), "%z", &fields))
		return;
	if (strlen(offset) != 5 || (offset[0] != '+' && offset[0] != '-'))
		return;
	for (unsigned i = 1; i < 5; ++i)
		if (!isdigit((unsigned char)offset[i]))
			return;
	const unsigned hours = (unsigned)(offset[1] - '0') * 10U + (unsigned)(offset[2] - '0');
	const unsigned minutes = (unsigned)(offset[3] - '0') * 10U + (unsigned)(offset[4] - '0');
	const int length = minutes ? snprintf(text, capacity, "%s %c%u:%02u UTC", date, offset[0], hours, minutes) : snprintf(text, capacity, "%s %c%u UTC", date, offset[0], hours);
	if (length < 0 || (size_t)length >= capacity)
		text[0] = '\0';
}

void app_time_format(uint64_t timestamp, char *text, size_t capacity, bool local) {
	time_t seconds = (time_t)timestamp;
	struct tm fields;
	struct tm *result = local ? localtime_r(&seconds, &fields) : gmtime_r(&seconds, &fields);
	if (!result || strftime(text, capacity, local ? "%Y-%m-%d %H:%M:%S" : "%Y-%m-%dT%H:%M:%SZ", &fields) == 0) {
		if (capacity)
			text[0] = '\0';
	}
}
