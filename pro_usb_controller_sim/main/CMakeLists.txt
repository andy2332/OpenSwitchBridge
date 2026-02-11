idf_component_register(
    SRCS "main.c"
         "ns_descriptors.c"
         "ns_protocol.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_rmt
)
