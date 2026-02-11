#pragma once

#include <stdint.h>

#include "tinyusb.h"

uint8_t const *ns_descriptors_report_map(void);
void ns_descriptors_fill_tusb_config(tinyusb_config_t *cfg);
