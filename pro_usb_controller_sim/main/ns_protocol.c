#include "ns_protocol.h"

#include <string.h>

#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "freertos/FreeRTOS.h"
#include "ns_proto.h"
#include "tinyusb.h"

static const char *TAG = "NS_SIM";

static ns_state_t s_state;
static uint8_t s_last_subcmd_reply[64];
static size_t s_last_subcmd_reply_len;
static bool s_input_inited;
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

static void ns_send_report(uint8_t report_id, const uint8_t *payload, size_t len)
{
    if (!ns_hid_ready()) {
        return;
    }
    tud_hid_report(report_id, payload, len);
}

static void ns_fill_base_payload(uint8_t *payload, size_t len)
{
    if (len < 12) {
        return;
    }

    payload[0] = s_state.timer++;
    /* Match known-working nscon behavior for USB status byte. */
    payload[1] = 0x81;

    /* Byte3: right-side buttons. A is bit 0x08. */
    payload[2] = ns_button_a_pressed() ? 0x08 : 0x00;
    payload[3] = 0x00;
    payload[4] = 0x00;

    ns_pack_stick(&payload[5], NS_STICK_CENTER, NS_STICK_CENTER);
    ns_pack_stick(&payload[8], NS_STICK_CENTER, NS_STICK_CENTER);
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
    ns_send_report(NS_REPORT_ID_STD, payload, sizeof(payload));
}

static void ns_send_simple_hid_report(void)
{
    uint8_t payload[11] = {0};
    uint8_t a_pressed = ns_button_a_pressed() ? 0x08 : 0x00;

    /* 0x3F format: 2 bytes buttons + hat + 8 bytes stick/filler. */
    payload[0] = 0x00;
    payload[1] = a_pressed;
    payload[2] = 0x08; /* neutral hat */
    payload[3] = 0x40;
    payload[4] = 0x8A;
    payload[5] = 0x4F;
    payload[6] = 0x8A;
    payload[7] = 0xD0;
    payload[8] = 0x7E;
    payload[9] = 0xDF;
    payload[10] = 0x7F;
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
