#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "ns_descriptors.h"
#include "ns_proto.h"
#include "ns_protocol.h"
#include "ns_wifi_control.h"
#include "tinyusb.h"
#include "tinyusb_default_config.h"

static const char *TAG = "NS_SIM_MAIN";

uint8_t const *tud_hid_descriptor_report_cb(uint8_t instance)
{
    (void)instance;
    return ns_descriptors_report_map();
}

uint16_t tud_hid_get_report_cb(uint8_t instance,
                               uint8_t report_id,
                               hid_report_type_t report_type,
                               uint8_t *buffer,
                               uint16_t reqlen)
{
    return ns_protocol_get_report(instance, report_id, report_type, buffer, reqlen);
}

void tud_hid_set_report_cb(uint8_t instance,
                           uint8_t report_id,
                           hid_report_type_t report_type,
                           uint8_t const *buffer,
                           uint16_t bufsize)
{
    ns_protocol_set_report(instance, report_id, report_type, buffer, bufsize);
}

void app_main(void)
{
    tinyusb_config_t tusb_cfg = TINYUSB_DEFAULT_CONFIG();

    ns_protocol_init();
    ns_descriptors_fill_tusb_config(&tusb_cfg);
    ns_wifi_control_start();

    ESP_LOGI(TAG, "Nintendo Switch Pro USB simulator init");
    ESP_LOGI(TAG, "USB VID:PID = %04X:%04X", NS_VENDOR_ID, NS_PRODUCT_ID);
    ESP_ERROR_CHECK(tinyusb_driver_install(&tusb_cfg));
    ESP_LOGI(TAG, "Nintendo Switch Pro USB simulator ready");

    bool last_mounted = false;
    while (1) {
        bool mounted = tud_mounted();
        if (mounted != last_mounted) {
            ESP_LOGI(TAG, "tud_mounted changed: %d -> %d", (int)last_mounted, (int)mounted);
            last_mounted = mounted;
        }
        ns_wifi_control_periodic();
        ns_protocol_periodic();
        vTaskDelay(pdMS_TO_TICKS(NS_STD_PERIOD_MS));
    }
}
