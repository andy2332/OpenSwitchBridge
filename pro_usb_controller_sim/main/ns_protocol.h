#pragma once

#include <stddef.h>
#include <stdbool.h>
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

typedef enum {
    NS_COMBO_TEST_NONE = 0,
    NS_COMBO_TEST_CHORD,
    NS_COMBO_TEST_SEQUENCE,
} ns_combo_test_mode_t;

typedef struct {
    uint8_t std_btn_right;
    uint8_t std_btn_shared;
    uint8_t std_btn_left;
    uint16_t std_lx;
    uint16_t std_ly;
    uint16_t std_rx;
    uint16_t std_ry;
    uint8_t simple_btn_low;
    uint8_t simple_btn_high;
    uint8_t simple_hat;
} ns_custom_input_t;

void ns_protocol_init(void);
void ns_protocol_periodic(void);
void ns_protocol_set_test_button(ns_button_id_t button);
void ns_protocol_set_combo_test_mode(ns_combo_test_mode_t mode);
void ns_protocol_set_custom_input(const ns_custom_input_t *input, bool enable);

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
