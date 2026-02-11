#pragma once

#include <stddef.h>
#include <stdint.h>

#include "class/hid/hid_device.h"

void ns_protocol_init(void);
void ns_protocol_periodic(void);

uint16_t ns_protocol_get_report(uint8_t instance,
                                uint8_t report_id,
                                hid_report_type_t report_type,
                                uint8_t *buffer,
                                uint16_t reqlen);

void ns_protocol_set_report(uint8_t instance,
                            uint8_t report_id,
                            hid_report_type_t report_type,
                            uint8_t const *buffer,
                            uint16_t bufsize);
