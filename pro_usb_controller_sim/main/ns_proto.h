#pragma once

#include <stdbool.h>
#include <stdint.h>

#define NS_VENDOR_ID                        0x057E
#define NS_PRODUCT_ID                       0x2009
#define NS_BCD_DEVICE                       0x0100

#define NS_REPORT_ID_OUTPUT_SUBCMD          0x01
#define NS_REPORT_ID_OUTPUT_RUMBLE_ONLY     0x10
#define NS_REPORT_ID_OUTPUT_USB_CMD         0x80

#define NS_REPORT_ID_FEATURE_LAST_SUBCMD    0x02

#define NS_REPORT_ID_SUBCMD_REPLY           0x21
#define NS_REPORT_ID_STD                    0x30
#define NS_REPORT_ID_USB_REPLY              0x81

#define NS_SUBCMD_REQ_DEV_INFO              0x02
#define NS_SUBCMD_SET_REPORT_MODE           0x03
#define NS_SUBCMD_SPI_FLASH_READ            0x10
#define NS_SUBCMD_SET_PLAYER_LIGHTS         0x30
#define NS_SUBCMD_ENABLE_IMU                0x40
#define NS_SUBCMD_ENABLE_VIBRATION          0x48

#define NS_USB_CMD_CONN_STATUS              0x01
#define NS_USB_CMD_HANDSHAKE                0x02
#define NS_USB_CMD_BAUDRATE_3M              0x03
#define NS_USB_CMD_NO_TIMEOUT               0x04
#define NS_USB_CMD_ENABLE_TIMEOUT           0x05
#define NS_USB_CMD_RESET                    0x06

#define NS_REPLY_DATA_MAX                   49
#define NS_STD_PAYLOAD_LEN                  63
#define NS_STD_PERIOD_MS                    15
#define NS_USB_REPLY_PAYLOAD_LEN            63
#define NS_STICK_CENTER                     0x0800

#define NS_CAL_ADDR_START                   0x603D
#define NS_CAL_ADDR_END                     0x604E

typedef struct {
    uint8_t timer;
    uint8_t report_mode;
    bool input_streaming;
    bool usb_handshaked;
    bool usb_baud_3m;
    bool usb_no_timeout;
    bool imu_enabled;
    bool vibration_enabled;
    uint8_t player_lights;
} ns_state_t;
