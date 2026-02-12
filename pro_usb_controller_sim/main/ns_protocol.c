#include "ns_protocol.h"

#include <string.h>

#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "ns_proto.h"
#include "tinyusb.h"

static const char *TAG = "NS_SIM";

static ns_state_t s_state;
static uint8_t s_last_subcmd_reply[64];
static size_t s_last_subcmd_reply_len;
static bool s_input_inited;
static bool s_auto_key_inited;
static bool s_auto_key_started;
static bool s_auto_key_trigger_prev;
static int64_t s_auto_key_last_switch_us;
static uint8_t s_auto_key_index;
static bool s_manual_button_override;
static ns_button_id_t s_manual_button;
static ns_combo_test_mode_t s_combo_test_mode;
static bool s_custom_input_override;
static ns_custom_input_t s_custom_input;
static uint16_t s_imu_phase;
static bool s_imu_log_pending;
static bool s_auto_imu_enabled;
static bool s_combo_seq_active;
static uint8_t s_combo_seq_step;
static int64_t s_combo_seq_last_switch_us;
static bool s_gpio_a_last;
static bool s_effective_a_last;
static bool s_a_log_inited;
static const uint8_t s_spi_rom_60[] = {
    0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
    0xff, 0xff, 0x03, 0xa0, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x02, 0xff, 0xff, 0xff, 0xff,
    0xf0, 0xff, 0x89, 0x00, 0xf0, 0x01, 0x00, 0x40, 0x00, 0x40, 0x00, 0x40, 0xf9, 0xff, 0x06, 0x00,
    0x09, 0x00, 0xe7, 0x3b, 0xe7, 0x3b, 0xe7, 0x3b, 0xff, 0xff, 0xff, 0xff, 0xff, 0xba, 0x15, 0x62,
    0x11, 0xb8, 0x7f, 0x29, 0x06, 0x5b, 0xff, 0xe7, 0x7e, 0x0e, 0x36, 0x56, 0x9e, 0x85, 0x60, 0xff,
    0x32, 0x32, 0x32, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
    0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
    0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
    0x50, 0xfd, 0x00, 0x00, 0xc6, 0x0f, 0x0f, 0x30, 0x61, 0x96, 0x30, 0xf3, 0xd4, 0x14, 0x54, 0x41,
    0x15, 0x54, 0xc7, 0x79, 0x9c, 0x33, 0x36, 0x63, 0x0f, 0x30, 0x61, 0x96, 0x30, 0xf3, 0xd4, 0x14,
    0x54, 0x41, 0x15, 0x54, 0xc7, 0x79, 0x9c, 0x33, 0x36, 0x63, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
};
static const uint8_t s_spi_rom_80[] = {
    0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
    0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
    0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xb2, 0xa1, 0xbe, 0xff, 0x3e, 0x00, 0xf0, 0x01, 0x00, 0x40,
    0x00, 0x40, 0x00, 0x40, 0xfe, 0xff, 0xfe, 0xff, 0x08, 0x00, 0xe7, 0x3b, 0xe7, 0x3b, 0xe7, 0x3b,
};

/* Most ESP32-S3 dev boards expose BOOT on GPIO0 (active low). */
#define NS_BOOT_BUTTON_GPIO GPIO_NUM_0
#define NS_AUTO_KEY_INTERVAL_US (2000000LL)
#define NS_STICK_MIN 0x0000
#define NS_STICK_MAX 0x0FFF
#define NS_STD_IMU_OFFSET 12
#define NS_STD_IMU_SAMPLE_BYTES 12
#define NS_STD_IMU_SAMPLE_COUNT 3
#define NS_COMBO_STEP_INTERVAL_US (250000LL)

typedef struct ns_auto_key_pattern_s {
    const char *name;
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
} ns_auto_key_pattern_t;

static ns_auto_key_pattern_t s_auto_key_pattern_current;

typedef struct {
    const char *name;
    ns_button_id_t button;
    uint16_t std_lx;
    uint16_t std_ly;
    uint16_t std_rx;
    uint16_t std_ry;
    bool enable_imu_test;
} ns_auto_test_item_t;

#define NS_TEST_ITEM_BTN(_name, _button) \
    { _name, _button, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_CENTER, false }

static const ns_auto_test_item_t s_auto_test_items[] = {
    NS_TEST_ITEM_BTN("b0:Y", NS_BUTTON_Y),
    NS_TEST_ITEM_BTN("b1:X", NS_BUTTON_X),
    NS_TEST_ITEM_BTN("b2:B", NS_BUTTON_B),
    NS_TEST_ITEM_BTN("b3:A", NS_BUTTON_A),
    NS_TEST_ITEM_BTN("b4:L", NS_BUTTON_L),
    NS_TEST_ITEM_BTN("b5:R", NS_BUTTON_R),
    NS_TEST_ITEM_BTN("b6:ZL", NS_BUTTON_ZL),
    NS_TEST_ITEM_BTN("b7:ZR", NS_BUTTON_ZR),
    NS_TEST_ITEM_BTN("b8:MINUS", NS_BUTTON_MINUS),
    NS_TEST_ITEM_BTN("b9:PLUS", NS_BUTTON_PLUS),
    NS_TEST_ITEM_BTN("b10:L_STICK", NS_BUTTON_L_STICK),
    NS_TEST_ITEM_BTN("b11:R_STICK", NS_BUTTON_R_STICK),
    NS_TEST_ITEM_BTN("b12:HOME", NS_BUTTON_HOME),
    NS_TEST_ITEM_BTN("b13:CAPTURE", NS_BUTTON_CAPTURE),
    NS_TEST_ITEM_BTN("b14:UP", NS_BUTTON_UP),
    NS_TEST_ITEM_BTN("b15:DOWN", NS_BUTTON_DOWN),
    NS_TEST_ITEM_BTN("b16:LEFT", NS_BUTTON_LEFT),
    NS_TEST_ITEM_BTN("b17:RIGHT", NS_BUTTON_RIGHT),
    {"L_X_MIN", NS_BUTTON_NONE, NS_STICK_MIN,    NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_CENTER, false},
    {"L_X_MAX", NS_BUTTON_NONE, NS_STICK_MAX,    NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_CENTER, false},
    {"L_Y_MIN", NS_BUTTON_NONE, NS_STICK_CENTER, NS_STICK_MIN,    NS_STICK_CENTER, NS_STICK_CENTER, false},
    {"L_Y_MAX", NS_BUTTON_NONE, NS_STICK_CENTER, NS_STICK_MAX,    NS_STICK_CENTER, NS_STICK_CENTER, false},
    {"R_X_MIN", NS_BUTTON_NONE, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_MIN,    NS_STICK_CENTER, false},
    {"R_X_MAX", NS_BUTTON_NONE, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_MAX,    NS_STICK_CENTER, false},
    {"R_Y_MIN", NS_BUTTON_NONE, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_MIN,    false},
    {"R_Y_MAX", NS_BUTTON_NONE, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_MAX,    false},
    {"TEST_ENABLE_IMU", NS_BUTTON_NONE, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_CENTER, true},
    {"TEST_CHORD_ABXY_DPAD", NS_BUTTON_NONE, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_CENTER, false},
    {"TEST_COMBO_SEQ", NS_BUTTON_NONE, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_CENTER, false},
};

static void ns_pattern_reset(ns_auto_key_pattern_t *pattern)
{
    memset(pattern, 0, sizeof(*pattern));
    pattern->std_lx = NS_STICK_CENTER;
    pattern->std_ly = NS_STICK_CENTER;
    pattern->std_rx = NS_STICK_CENTER;
    pattern->std_ry = NS_STICK_CENTER;
    pattern->simple_hat = 0x08;
}

static void ns_pattern_apply_button(ns_auto_key_pattern_t *pattern, ns_button_id_t button)
{
    switch (button) {
    case NS_BUTTON_Y:
        pattern->std_btn_right = 0x01;
        pattern->simple_btn_high = 0x01;
        break;
    case NS_BUTTON_X:
        pattern->std_btn_right = 0x02;
        pattern->simple_btn_high = 0x02;
        break;
    case NS_BUTTON_B:
        pattern->std_btn_right = 0x04;
        pattern->simple_btn_high = 0x04;
        break;
    case NS_BUTTON_A:
        pattern->std_btn_right = 0x08;
        pattern->simple_btn_high = 0x08;
        break;
    case NS_BUTTON_L:
        pattern->std_btn_left = 0x40;
        pattern->simple_btn_low = 0x40;
        break;
    case NS_BUTTON_R:
        pattern->std_btn_right = 0x40;
        pattern->simple_btn_high = 0x40;
        break;
    case NS_BUTTON_ZL:
        pattern->std_btn_left = 0x80;
        pattern->simple_btn_low = 0x80;
        break;
    case NS_BUTTON_ZR:
        pattern->std_btn_right = 0x80;
        pattern->simple_btn_high = 0x80;
        break;
    case NS_BUTTON_MINUS:
        pattern->std_btn_shared = 0x01;
        pattern->simple_btn_low = 0x01;
        break;
    case NS_BUTTON_PLUS:
        pattern->std_btn_shared = 0x02;
        pattern->simple_btn_low = 0x02;
        break;
    case NS_BUTTON_L_STICK:
        pattern->std_btn_shared = 0x08;
        pattern->simple_btn_low = 0x20;
        break;
    case NS_BUTTON_R_STICK:
        pattern->std_btn_shared = 0x04;
        pattern->simple_btn_high = 0x20;
        break;
    case NS_BUTTON_HOME:
        pattern->std_btn_shared = 0x10;
        pattern->simple_btn_low = 0x10;
        break;
    case NS_BUTTON_CAPTURE:
        pattern->std_btn_shared = 0x20;
        pattern->simple_btn_high = 0x10;
        break;
    case NS_BUTTON_UP:
        pattern->std_btn_left = 0x02;
        pattern->simple_hat = 0x00;
        break;
    case NS_BUTTON_DOWN:
        pattern->std_btn_left = 0x01;
        pattern->simple_hat = 0x04;
        break;
    case NS_BUTTON_LEFT:
        pattern->std_btn_left = 0x08;
        pattern->simple_hat = 0x06;
        break;
    case NS_BUTTON_RIGHT:
        pattern->std_btn_left = 0x04;
        pattern->simple_hat = 0x02;
        break;
    case NS_BUTTON_NONE:
    default:
        break;
    }
}

static void ns_build_pattern_from_test_item(const ns_auto_test_item_t *item, ns_auto_key_pattern_t *pattern)
{
    ns_pattern_reset(pattern);
    pattern->name = item->name;
    pattern->std_lx = item->std_lx;
    pattern->std_ly = item->std_ly;
    pattern->std_rx = item->std_rx;
    pattern->std_ry = item->std_ry;
    ns_pattern_apply_button(pattern, item->button);
}

static void ns_build_pattern_from_custom_input(const ns_custom_input_t *input, ns_auto_key_pattern_t *pattern)
{
    if (input == NULL || pattern == NULL) {
        return;
    }

    ns_pattern_reset(pattern);
    pattern->name = "CUSTOM_INPUT";
    pattern->std_btn_right = input->std_btn_right;
    pattern->std_btn_shared = input->std_btn_shared;
    pattern->std_btn_left = input->std_btn_left;
    pattern->std_lx = input->std_lx;
    pattern->std_ly = input->std_ly;
    pattern->std_rx = input->std_rx;
    pattern->std_ry = input->std_ry;
    pattern->simple_btn_low = input->simple_btn_low;
    pattern->simple_btn_high = input->simple_btn_high;
    pattern->simple_hat = input->simple_hat;
}

static void ns_build_chord_pattern(ns_auto_key_pattern_t *pattern)
{
    ns_pattern_reset(pattern);
    pattern->name = "TEST_CHORD_ABXY_DPAD";
    pattern->std_btn_right = 0x0F;
    pattern->std_btn_left = 0x02; /* UP */
    pattern->simple_btn_high = 0x0F;
    pattern->simple_hat = 0x00; /* UP */
}

static void ns_build_combo_seq_pattern(ns_auto_key_pattern_t *pattern, int64_t now_us)
{
    static const ns_button_id_t s_combo_buttons[] = {
        NS_BUTTON_L, NS_BUTTON_R, NS_BUTTON_L, NS_BUTTON_R,
        NS_BUTTON_B, NS_BUTTON_A, NS_BUTTON_B, NS_BUTTON_A,
    };
    size_t combo_len = sizeof(s_combo_buttons) / sizeof(s_combo_buttons[0]);

    if (!s_combo_seq_active) {
        s_combo_seq_active = true;
        s_combo_seq_step = 0;
        s_combo_seq_last_switch_us = now_us;
    }

    while ((now_us - s_combo_seq_last_switch_us) >= NS_COMBO_STEP_INTERVAL_US) {
        s_combo_seq_last_switch_us += NS_COMBO_STEP_INTERVAL_US;
        s_combo_seq_step = (uint8_t)((s_combo_seq_step + 1U) % combo_len);
    }

    ns_pattern_reset(pattern);
    pattern->name = "TEST_COMBO_SEQ";
    ns_pattern_apply_button(pattern, s_combo_buttons[s_combo_seq_step]);
}

static void ns_input_init(void)
{
    if (s_input_inited) {
        return;
    }

    gpio_config_t io_conf = {
        .pin_bit_mask = 1ULL << NS_BOOT_BUTTON_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io_conf);
    s_input_inited = true;
}

static bool ns_button_a_pressed(void)
{
    bool gpio_pressed = (gpio_get_level(NS_BOOT_BUTTON_GPIO) == 0);
    bool effective_pressed = gpio_pressed;

    if (!s_a_log_inited) {
        s_gpio_a_last = gpio_pressed;
        s_effective_a_last = effective_pressed;
        s_a_log_inited = true;
    }

    if (gpio_pressed != s_gpio_a_last) {
        ESP_LOGI(TAG, "GPIO0 A key: %s", gpio_pressed ? "pressed" : "released");
        s_gpio_a_last = gpio_pressed;
    }

    if (effective_pressed != s_effective_a_last) {
        ESP_LOGI(TAG, "A output: %s", effective_pressed ? "pressed" : "released");
        s_effective_a_last = effective_pressed;
    }

    return effective_pressed;
}

static const ns_auto_key_pattern_t *ns_get_auto_key_pattern(void)
{
    static const ns_auto_test_item_t s_manual_item = {
        "MANUAL_BUTTON", NS_BUTTON_NONE, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_CENTER, NS_STICK_CENTER, false
    };
    const ns_auto_test_item_t *item = NULL;
    bool trigger_pressed = ns_button_a_pressed();
    int64_t now = esp_timer_get_time();

    if (s_custom_input_override) {
        s_auto_imu_enabled = false;
        s_combo_seq_active = false;
        ns_build_pattern_from_custom_input(&s_custom_input, &s_auto_key_pattern_current);
        return &s_auto_key_pattern_current;
    }

    if (s_combo_test_mode == NS_COMBO_TEST_CHORD) {
        s_combo_seq_active = false;
        s_auto_imu_enabled = false;
        ns_build_chord_pattern(&s_auto_key_pattern_current);
        return &s_auto_key_pattern_current;
    }

    if (s_combo_test_mode == NS_COMBO_TEST_SEQUENCE) {
        s_auto_imu_enabled = false;
        ns_build_combo_seq_pattern(&s_auto_key_pattern_current, now);
        return &s_auto_key_pattern_current;
    }

    if (s_manual_button_override) {
        ns_auto_test_item_t manual_item = s_manual_item;
        manual_item.button = s_manual_button;
        s_auto_imu_enabled = false;
        s_combo_seq_active = false;
        ns_build_pattern_from_test_item(&manual_item, &s_auto_key_pattern_current);
        return &s_auto_key_pattern_current;
    }

    if (trigger_pressed && !s_auto_key_trigger_prev) {
        s_auto_key_index = 0;
        s_auto_key_last_switch_us = now;
        s_auto_key_started = true;
        s_auto_key_inited = true;
        s_imu_log_pending = true;
        ESP_LOGI(TAG, "auto key test start: %s", s_auto_test_items[s_auto_key_index].name);
    }
    s_auto_key_trigger_prev = trigger_pressed;

    if (!s_auto_key_started || !s_auto_key_inited) {
        return NULL;
    }

    while ((now - s_auto_key_last_switch_us) >= NS_AUTO_KEY_INTERVAL_US) {
        s_auto_key_last_switch_us += NS_AUTO_KEY_INTERVAL_US;
        s_auto_key_index = (uint8_t)((s_auto_key_index + 1U) %
                                     (sizeof(s_auto_test_items) / sizeof(s_auto_test_items[0])));
        s_imu_log_pending = true;
        ESP_LOGI(TAG, "auto key test switch -> %s", s_auto_test_items[s_auto_key_index].name);
    }

    item = &s_auto_test_items[s_auto_key_index];
    s_auto_imu_enabled = item->enable_imu_test;
    if (strcmp(item->name, "TEST_CHORD_ABXY_DPAD") == 0) {
        s_combo_seq_active = false;
        ns_build_chord_pattern(&s_auto_key_pattern_current);
    } else if (strcmp(item->name, "TEST_COMBO_SEQ") == 0) {
        ns_build_combo_seq_pattern(&s_auto_key_pattern_current, now);
    } else {
        s_combo_seq_active = false;
        ns_build_pattern_from_test_item(item, &s_auto_key_pattern_current);
    }
    return &s_auto_key_pattern_current;
}

static bool ns_hid_ready(void)
{
    return tud_mounted() && tud_hid_ready();
}

static void ns_pack_stick(uint8_t out3[3], uint16_t x, uint16_t y)
{
    out3[0] = x & 0xFF;
    out3[1] = ((x >> 8) & 0x0F) | ((y & 0x0F) << 4);
    out3[2] = (y >> 4) & 0xFF;
}

static uint16_t ns_stick_12_to_16(uint16_t axis12)
{
    return (uint16_t)(axis12 << 4);
}

static int16_t ns_triangle_wave(uint16_t phase, int16_t amplitude)
{
    uint16_t t = (uint16_t)(phase & 0x07FFU);
    int32_t value;

    if (t < 1024U) {
        value = (int32_t)t;
    } else {
        value = 2047 - (int32_t)t;
    }

    return (int16_t)(((value * 2 - 1023) * amplitude) / 1023);
}

static void ns_pack_i16le(uint8_t *dst, int16_t value)
{
    dst[0] = (uint8_t)(value & 0xFF);
    dst[1] = (uint8_t)(((uint16_t)value >> 8) & 0xFF);
}

static void ns_fill_imu_payload(uint8_t *payload, size_t len)
{
    size_t imu_total_len = NS_STD_IMU_OFFSET + NS_STD_IMU_SAMPLE_BYTES * NS_STD_IMU_SAMPLE_COUNT;
    if (!(s_state.imu_enabled || s_auto_imu_enabled) || len < imu_total_len) {
        return;
    }

    int16_t log_accel_x = 0;
    int16_t log_accel_y = 0;
    int16_t log_accel_z = 0;
    int16_t log_gyro_pitch = 0;
    int16_t log_gyro_roll = 0;
    int16_t log_gyro_yaw = 0;

    for (uint8_t sample = 0; sample < NS_STD_IMU_SAMPLE_COUNT; sample++) {
        uint8_t *imu = &payload[NS_STD_IMU_OFFSET + sample * NS_STD_IMU_SAMPLE_BYTES];
        uint16_t phase = (uint16_t)(s_imu_phase + (uint16_t)sample * 171U);

        int16_t accel_x = ns_triangle_wave(phase, 800);
        int16_t accel_y = ns_triangle_wave((uint16_t)(phase + 683U), 650);
        int16_t accel_z = (int16_t)(4096 + ns_triangle_wave((uint16_t)(phase + 341U), 220));

        int16_t gyro_pitch = ns_triangle_wave((uint16_t)(phase + 128U), 1200);
        int16_t gyro_roll = ns_triangle_wave((uint16_t)(phase + 512U), 900);
        int16_t gyro_yaw = ns_triangle_wave((uint16_t)(phase + 896U), 1050);

        ns_pack_i16le(&imu[0], accel_x);
        ns_pack_i16le(&imu[2], accel_y);
        ns_pack_i16le(&imu[4], accel_z);
        ns_pack_i16le(&imu[6], gyro_pitch);
        ns_pack_i16le(&imu[8], gyro_roll);
        ns_pack_i16le(&imu[10], gyro_yaw);

        if (sample == 0) {
            log_accel_x = accel_x;
            log_accel_y = accel_y;
            log_accel_z = accel_z;
            log_gyro_pitch = gyro_pitch;
            log_gyro_roll = gyro_roll;
            log_gyro_yaw = gyro_yaw;
        }
    }

    if (s_imu_log_pending) {
        ESP_LOGI(TAG, "imu test ax=%d ay=%d az=%d gx=%d gy=%d gz=%d",
                 log_accel_x, log_accel_y, log_accel_z,
                 log_gyro_pitch, log_gyro_roll, log_gyro_yaw);
        s_imu_log_pending = false;
    }

    s_imu_phase = (uint16_t)(s_imu_phase + 85U);
}

static void ns_send_report(uint8_t report_id, const uint8_t *payload, size_t len)
{
    if (!ns_hid_ready()) {
        return;
    }
    tud_hid_report(report_id, payload, len);
}

static void ns_fill_base_payload(uint8_t *payload, size_t len)
{
    const ns_auto_key_pattern_t *pattern = ns_get_auto_key_pattern();

    if (len < 12) {
        return;
    }

    payload[0] = s_state.timer++;
    /* Match known-working nscon behavior for USB status byte. */
    payload[1] = 0x81;

    /* Byte3: right-side buttons. */
    payload[2] = pattern ? pattern->std_btn_right : 0x00;
    payload[3] = pattern ? pattern->std_btn_shared : 0x00;
    payload[4] = pattern ? pattern->std_btn_left : 0x00;

    ns_pack_stick(&payload[5], pattern ? pattern->std_lx : NS_STICK_CENTER,
                  pattern ? pattern->std_ly : NS_STICK_CENTER);
    ns_pack_stick(&payload[8], pattern ? pattern->std_rx : NS_STICK_CENTER,
                  pattern ? pattern->std_ry : NS_STICK_CENTER);
    payload[11] = 0x00;
}

static void ns_save_last_subcmd_reply(const uint8_t *payload, size_t payload_len)
{
    size_t max_payload = sizeof(s_last_subcmd_reply) - 1;
    if (payload_len > max_payload) {
        payload_len = max_payload;
    }

    s_last_subcmd_reply[0] = NS_REPORT_ID_SUBCMD_REPLY;
    memcpy(&s_last_subcmd_reply[1], payload, payload_len);
    s_last_subcmd_reply_len = payload_len + 1;
}

static void ns_send_usb_reply(uint8_t cmd, const uint8_t *data, size_t data_len)
{
    uint8_t payload[NS_USB_REPLY_PAYLOAD_LEN] = {0};

    if (data_len > (NS_USB_REPLY_PAYLOAD_LEN - 1U)) {
        data_len = NS_USB_REPLY_PAYLOAD_LEN - 1U;
    }

    payload[0] = cmd;
    if (data_len) {
        memcpy(&payload[1], data, data_len);
    }

    ESP_LOGI(TAG, "usb cmd reply 0x%02X len=%u", cmd, (unsigned)data_len);
    ns_send_report(NS_REPORT_ID_USB_REPLY, payload, sizeof(payload));
}

static void ns_send_subcmd_reply(uint8_t ack_type, uint8_t subcmd_id,
                                 const uint8_t *data, size_t data_len)
{
    uint8_t payload[NS_USB_REPLY_PAYLOAD_LEN] = {0};
    size_t max_len = NS_USB_REPLY_PAYLOAD_LEN - 14;

    if (data_len > max_len) {
        data_len = max_len;
    }

    ns_fill_base_payload(payload, sizeof(payload));
    payload[12] = ack_type;
    payload[13] = subcmd_id;
    if (data_len) {
        memcpy(&payload[14], data, data_len);
    }

    /* Keep a full-size report image for feature report 0x02 reads. */
    ns_save_last_subcmd_reply(payload, sizeof(payload));

    ESP_LOGI(TAG, "subcmd reply 0x%02X ack 0x%02X len=%u",
             subcmd_id, ack_type, (unsigned)data_len);
    ns_send_report(NS_REPORT_ID_SUBCMD_REPLY, payload, sizeof(payload));
}

static void ns_send_std_report(void)
{
    uint8_t payload[NS_STD_PAYLOAD_LEN] = {0};
    ns_fill_base_payload(payload, sizeof(payload));
    ns_fill_imu_payload(payload, sizeof(payload));
    ns_send_report(NS_REPORT_ID_STD, payload, sizeof(payload));
}

static void ns_send_simple_hid_report(void)
{
    uint8_t payload[11] = {0};
    const ns_auto_key_pattern_t *pattern = ns_get_auto_key_pattern();
    uint16_t lx16 = ns_stick_12_to_16(pattern ? pattern->std_lx : NS_STICK_CENTER);
    uint16_t ly16 = ns_stick_12_to_16(pattern ? pattern->std_ly : NS_STICK_CENTER);
    uint16_t rx16 = ns_stick_12_to_16(pattern ? pattern->std_rx : NS_STICK_CENTER);
    uint16_t ry16 = ns_stick_12_to_16(pattern ? pattern->std_ry : NS_STICK_CENTER);

    /* 0x3F format: 2 bytes buttons + hat + 8 bytes stick/filler. */
    payload[0] = pattern ? pattern->simple_btn_low : 0x00;
    payload[1] = pattern ? pattern->simple_btn_high : 0x00;
    payload[2] = pattern ? pattern->simple_hat : 0x08;
    payload[3] = (uint8_t)(lx16 & 0xFF);
    payload[4] = (uint8_t)((lx16 >> 8) & 0xFF);
    payload[5] = (uint8_t)(ly16 & 0xFF);
    payload[6] = (uint8_t)((ly16 >> 8) & 0xFF);
    payload[7] = (uint8_t)(rx16 & 0xFF);
    payload[8] = (uint8_t)((rx16 >> 8) & 0xFF);
    payload[9] = (uint8_t)(ry16 & 0xFF);
    payload[10] = (uint8_t)((ry16 >> 8) & 0xFF);
    ns_send_report(0x3F, payload, sizeof(payload));
}

static bool ns_spi_read_rom(uint32_t addr, uint8_t *out, uint8_t len)
{
    const uint8_t *base = NULL;
    size_t base_len = 0;
    uint8_t high = (uint8_t)((addr >> 8) & 0xFF);
    uint8_t off = (uint8_t)(addr & 0xFF);

    if (high == 0x60) {
        base = s_spi_rom_60;
        base_len = sizeof(s_spi_rom_60);
    } else if (high == 0x80) {
        base = s_spi_rom_80;
        base_len = sizeof(s_spi_rom_80);
    } else {
        return false;
    }

    if ((size_t)off + len > base_len) {
        return false;
    }

    memcpy(out, &base[off], len);
    return true;
}

static void ns_handle_subcmd(const uint8_t *data, size_t len)
{
    if (len < 10) {
        return;
    }

    const uint8_t *subcmd_data = &data[10];
    size_t subcmd_len = len - 10;
    uint8_t subcmd_id = data[9];

    ESP_LOGI(TAG, "subcmd 0x%02X len=%u", subcmd_id, (unsigned)subcmd_len);

    switch (subcmd_id) {
    case NS_SUBCMD_REQ_DEV_INFO: {
        uint8_t dev_info[12] = {
            0x03, 0x48, 0x03, 0x02,
            0x5E, 0x53, 0x00, 0x5E, 0x00, 0x00,
            0x03, 0x01
        };

        ns_send_subcmd_reply(0x82, subcmd_id, dev_info, sizeof(dev_info));
        break;
    }
    case NS_SUBCMD_SET_REPORT_MODE:
        if (subcmd_len >= 1) {
            s_state.report_mode = subcmd_data[0];
            ESP_LOGI(TAG, "set report mode 0x%02X", s_state.report_mode);
        }
        ns_send_subcmd_reply(0x80, subcmd_id, NULL, 0);
        break;
    case NS_SUBCMD_SPI_FLASH_READ:
        if (subcmd_len >= 5) {
            uint8_t reply[5 + 30] = {0};
            uint32_t addr = (uint32_t)subcmd_data[0] |
                            ((uint32_t)subcmd_data[1] << 8) |
                            ((uint32_t)subcmd_data[2] << 16) |
                            ((uint32_t)subcmd_data[3] << 24);
            uint8_t read_len = subcmd_data[4];
            bool ok;

            if (read_len > 30) {
                read_len = 30;
            }

            reply[0] = (uint8_t)(addr & 0xFF);
            reply[1] = (uint8_t)((addr >> 8) & 0xFF);
            reply[2] = (uint8_t)((addr >> 16) & 0xFF);
            reply[3] = (uint8_t)((addr >> 24) & 0xFF);
            reply[4] = read_len;
            ok = ns_spi_read_rom(addr, &reply[5], read_len);
            if (ok) {
                ns_send_subcmd_reply(0x90, subcmd_id, reply, 5 + read_len);
            } else {
                ns_send_subcmd_reply(0x00, subcmd_id, NULL, 0);
            }
        } else {
            ns_send_subcmd_reply(0x80, subcmd_id, NULL, 0);
        }
        break;
    case 0x21: {
        uint8_t mcu_reply[8] = {0x01, 0x00, 0xff, 0x00, 0x03, 0x00, 0x05, 0x01};
        ns_send_subcmd_reply(0xA0, subcmd_id, mcu_reply, sizeof(mcu_reply));
        break;
    }
    case NS_SUBCMD_SET_PLAYER_LIGHTS:
        if (subcmd_len >= 1) {
            s_state.player_lights = subcmd_data[0];
        }
        ns_send_subcmd_reply(0x80, subcmd_id, NULL, 0);
        break;
    case NS_SUBCMD_ENABLE_IMU:
        if (subcmd_len >= 1) {
            s_state.imu_enabled = (subcmd_data[0] != 0);
            if (s_state.imu_enabled) {
                s_imu_log_pending = true;
            }
        }
        ns_send_subcmd_reply(0x80, subcmd_id, NULL, 0);
        break;
    case NS_SUBCMD_ENABLE_VIBRATION:
        if (subcmd_len >= 1) {
            s_state.vibration_enabled = (subcmd_data[0] != 0);
        }
        ns_send_subcmd_reply(0x80, subcmd_id, NULL, 0);
        break;
    default:
        /* Minimal compatibility path for unsupported subcommands. */
        ns_send_subcmd_reply(0x80, subcmd_id, NULL, 0);
        break;
    }
}

static void ns_handle_usb_cmd(const uint8_t *data, size_t len)
{
    if (len < 1) {
        return;
    }

    uint8_t cmd = data[0];

    ESP_LOGI(TAG, "usb cmd 0x%02X", cmd);

    switch (cmd) {
    case NS_USB_CMD_CONN_STATUS: {
        uint8_t status[8] = {0x00, 0x03, 0x00, 0x00, 0x5e, 0x00, 0x53, 0x5e};
        ns_send_usb_reply(cmd, status, sizeof(status));
        break;
    }
    case NS_USB_CMD_HANDSHAKE:
        s_state.usb_handshaked = true;
        ns_send_usb_reply(cmd, NULL, 0);
        break;
    case NS_USB_CMD_BAUDRATE_3M:
        s_state.usb_baud_3m = true;
        ns_send_usb_reply(cmd, NULL, 0);
        break;
    case NS_USB_CMD_NO_TIMEOUT:
        s_state.usb_no_timeout = true;
        s_state.input_streaming = true;
        /* nscon starts input stream after this command. */
        break;
    case NS_USB_CMD_ENABLE_TIMEOUT:
        s_state.usb_no_timeout = false;
        s_state.input_streaming = false;
        /* nscon stops input stream after this command. */
        break;
    case NS_USB_CMD_RESET:
        ns_protocol_init();
        ns_send_usb_reply(cmd, NULL, 0);
        break;
    default:
        ns_send_usb_reply(cmd, NULL, 0);
        break;
    }
}

void ns_protocol_init(void)
{
    ns_input_init();

    s_state.timer = 0;
    s_state.report_mode = NS_REPORT_ID_STD;
    s_state.input_streaming = false;
    s_state.usb_handshaked = false;
    s_state.usb_baud_3m = false;
    s_state.usb_no_timeout = false;
    s_state.imu_enabled = false;
    s_state.vibration_enabled = false;
    s_state.player_lights = 0;
    s_auto_key_inited = false;
    s_auto_key_started = false;
    s_auto_key_trigger_prev = false;
    s_auto_key_last_switch_us = 0;
    s_auto_key_index = 0;
    s_manual_button_override = false;
    s_manual_button = NS_BUTTON_NONE;
    s_combo_test_mode = NS_COMBO_TEST_NONE;
    s_custom_input_override = false;
    memset(&s_custom_input, 0, sizeof(s_custom_input));
    s_imu_phase = 0;
    s_imu_log_pending = false;
    s_auto_imu_enabled = false;
    s_combo_seq_active = false;
    s_combo_seq_step = 0;
    s_combo_seq_last_switch_us = 0;
    s_a_log_inited = false;

    memset(s_last_subcmd_reply, 0, sizeof(s_last_subcmd_reply));
    s_last_subcmd_reply_len = 0;
}

void ns_protocol_periodic(void)
{
    if (!tud_mounted()) {
        return;
    }
    if (!s_state.input_streaming) {
        return;
    }

    if (s_state.report_mode == NS_REPORT_ID_STD) {
        ns_send_std_report();
    } else if (s_state.report_mode == 0x3F) {
        ns_send_simple_hid_report();
    }
}

void ns_protocol_set_test_button(ns_button_id_t button)
{
    if (button > NS_BUTTON_RIGHT) {
        return;
    }

    s_combo_test_mode = NS_COMBO_TEST_NONE;
    s_custom_input_override = false;
    s_manual_button = button;
    s_manual_button_override = (button != NS_BUTTON_NONE);
}

void ns_protocol_set_combo_test_mode(ns_combo_test_mode_t mode)
{
    if (mode > NS_COMBO_TEST_SEQUENCE) {
        return;
    }

    s_manual_button_override = false;
    s_manual_button = NS_BUTTON_NONE;
    s_custom_input_override = false;
    s_combo_test_mode = mode;
    if (mode != NS_COMBO_TEST_SEQUENCE) {
        s_combo_seq_active = false;
    }
}

void ns_protocol_set_custom_input(const ns_custom_input_t *input, bool enable)
{
    if (!enable || input == NULL) {
        s_custom_input_override = false;
        return;
    }

    s_manual_button_override = false;
    s_manual_button = NS_BUTTON_NONE;
    s_combo_test_mode = NS_COMBO_TEST_NONE;
    s_combo_seq_active = false;

    s_custom_input = *input;
    s_custom_input_override = true;
}

uint16_t ns_protocol_get_report(uint8_t instance,
                                uint8_t report_id,
                                hid_report_type_t report_type,
                                uint8_t *buffer,
                                uint16_t reqlen)
{
    (void)instance;

    if (buffer == NULL || reqlen == 0) {
        return 0;
    }

    if (report_type == HID_REPORT_TYPE_FEATURE &&
        report_id == NS_REPORT_ID_FEATURE_LAST_SUBCMD &&
        s_last_subcmd_reply_len > 0) {
        size_t copy_len = s_last_subcmd_reply_len;
        if (copy_len > reqlen) {
            copy_len = reqlen;
        }
        memcpy(buffer, s_last_subcmd_reply, copy_len);
        return (uint16_t)copy_len;
    }

    return 0;
}

void ns_protocol_set_report(uint8_t instance,
                            uint8_t report_id,
                            hid_report_type_t report_type,
                            uint8_t const *buffer,
                            uint16_t bufsize)
{
    (void)instance;
    (void)report_type;

    if (bufsize == 0 || buffer == NULL) {
        return;
    }

    const uint8_t *p = buffer;
    size_t len = bufsize;
    uint8_t rid = report_id;

    if (rid == 0 && len > 0) {
        rid = p[0];
        p++;
        len--;
    }

    if (rid == NS_REPORT_ID_OUTPUT_SUBCMD) {
        ns_handle_subcmd(p, len);
    } else if (rid == NS_REPORT_ID_OUTPUT_USB_CMD) {
        ns_handle_usb_cmd(p, len);
    } else if (rid == NS_REPORT_ID_OUTPUT_RUMBLE_ONLY) {
        /* Accepted but no-op in the framework baseline. */
    }
}
