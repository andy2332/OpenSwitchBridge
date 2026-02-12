idf_component_register(
    SRCS "main.c"
         "ns_descriptors.c"
         "ns_protocol.c"
         "ns_wifi_control.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_rmt esp_driver_gpio esp_event esp_http_server esp_netif esp_wifi nvs_flash
    PRIV_REQUIRES esp_timer
)
