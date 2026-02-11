#pragma once

#include <stddef.h>
#include <stdint.h>

#include "class/hid/hid_device.h"

typedef enum {
    NS_BUTTON_NONE = 0,
    NS_BUTTON_Y,
    NS_BUTTON_X,
    NS_BUTTON_B,
    NS_BUTTON_A,
    NS_BUTTON_L,
    NS_BUTTON_R,
    NS_BUTTON_ZL,
    NS_BUTTON_ZR,
    NS_BUTTON_MINUS,
    NS_BUTTON_PLUS,
    NS_BUTTON_L_STICK,
    NS_BUTTON_R_STICK,
    NS_BUTTON_HOME,
    NS_BUTTON_CAPTURE,
    NS_BUTTON_UP,
    NS_BUTTON_DOWN,
    NS_BUTTON_LEFT,
    NS_BUTTON_RIGHT,
} ns_button_id_t;

void ns_protocol_init(void);
void ns_protocol_periodic(void);
void ns_protocol_set_test_button(ns_button_id_t button);

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
