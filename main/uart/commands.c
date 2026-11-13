#include "commands.h"
#include "app_config.h"
#include "time/app_time.h"
#include <ctype.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>

static bool number(const char *text, uint32_t *value) {
	if (!text || !*text)
		return false;
	for (const char *p = text; *p; ++p)
		if (!isdigit((unsigned char)*p))
			return false;
	errno = 0;
	char *end;
	unsigned long long parsed = strtoull(text, &end, 10);
	if (errno || *end || parsed > UINT32_MAX)
		return false;
	*value = (uint32_t)parsed;
	return true;
}

bool command_parse(char *line, app_command_t *command) {
	char *save = NULL;
	char *tokens[4] = {0};
	unsigned count = 0;
	for (char *token = strtok_r(line, " \t", &save); token; token = strtok_r(NULL, " \t", &save)) {
		if (count == 4)
			return false;
		tokens[count++] = token;
	}
	if (!count)
		return false;
	*command = (app_command_t){0};
	if (count == 1) {
		if (!strcmp(tokens[0], "status"))
			command->kind = APP_STATUS;
		else if (!strcmp(tokens[0], "flush"))
			command->kind = APP_FLUSH;
		else if (!strcmp(tokens[0], "erase"))
			command->kind = APP_ERASE;
		else if (!strcmp(tokens[0], "help"))
			command->kind = APP_HELP;
		else if (!strcmp(tokens[0], "read")) {
			command->kind = APP_READ;
			command->first = UINT32_MAX;
			command->count = 16;
		} else
			return false;
		return true;
	}
	if (count == 2 && !strcmp(tokens[0], "log")) {
		if (!strcmp(tokens[1], "on"))
			command->kind = APP_LOG_ON;
		else if (!strcmp(tokens[1], "off"))
			command->kind = APP_LOG_OFF;
		else
			return false;
		return true;
	}
	if (count == 3 && !strcmp(tokens[0], "time") && !strcmp(tokens[1], "set")) {
		command->kind = APP_TIME_SET;
		return app_time_parse(tokens[2], &command->timestamp);
	}
	if (count == 3 && !strcmp(tokens[0], "read")) {
		command->kind = APP_READ;
		return number(tokens[1], &command->first) && command->first != UINT32_MAX && number(tokens[2], &command->count) && command->count > 0 && command->count <= APP_READ_MAX_RECORDS;
	}
	return false;
}
