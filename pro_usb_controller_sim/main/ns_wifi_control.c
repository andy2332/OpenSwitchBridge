#include "ns_wifi_control.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "driver/gpio.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "nvs.h"
#include "nvs_flash.h"

#include "ns_protocol.h"

static const char *TAG = "NS_WIFI_CTRL";

#define NS_SETUP_AP_SSID "OpenSwitchBridge-Setup"
#define NS_SETUP_AP_PASS "12345678"
#define NS_SETUP_AP_MAX_CONN 4

#define NS_WIFI_NAMESPACE "wifi_cfg"
#define NS_WIFI_KEY_SSID "ssid"
#define NS_WIFI_KEY_PASS "pass"

#define NS_PROVISION_TRIGGER_GPIO GPIO_NUM_35
#define NS_PROVISION_HOLD_US (5000000LL)
#define NS_PRESS_DEFAULT_MS 100
#define NS_HOLD_MIN_MS 20
#define NS_HOLD_MAX_MS 60000

typedef struct {
    const char *name;
    ns_button_id_t button;
} ns_button_name_map_t;

static const ns_button_name_map_t s_button_name_map[] = {
    {"NONE", NS_BUTTON_NONE},
    {"Y", NS_BUTTON_Y},
    {"X", NS_BUTTON_X},
    {"B", NS_BUTTON_B},
    {"A", NS_BUTTON_A},
    {"L", NS_BUTTON_L},
    {"R", NS_BUTTON_R},
    {"ZL", NS_BUTTON_ZL},
    {"ZR", NS_BUTTON_ZR},
    {"MINUS", NS_BUTTON_MINUS},
    {"PLUS", NS_BUTTON_PLUS},
    {"L_STICK", NS_BUTTON_L_STICK},
    {"R_STICK", NS_BUTTON_R_STICK},
    {"HOME", NS_BUTTON_HOME},
    {"CAPTURE", NS_BUTTON_CAPTURE},
    {"UP", NS_BUTTON_UP},
    {"DOWN", NS_BUTTON_DOWN},
    {"LEFT", NS_BUTTON_LEFT},
    {"RIGHT", NS_BUTTON_RIGHT},
};

static bool s_http_server_started;
static bool s_sta_connected;
static bool s_wifi_inited;
static bool s_wifi_creds_loaded;
static bool s_provision_mode;
static char s_sta_ssid[33];
static char s_sta_pass[65];
static char s_sta_ip[16];
static esp_event_handler_instance_t s_wifi_event_instance;
static esp_event_handler_instance_t s_ip_event_instance;

static bool s_provision_btn_pressed;
static bool s_provision_btn_triggered;
static int64_t s_provision_btn_press_start_us;
static bool s_button_auto_release_pending;
static int64_t s_button_auto_release_deadline_us;

static const char *s_setup_html =
    "<!doctype html><html><head><meta charset=\"utf-8\">"
    "<title>OpenSwitchBridge Wi-Fi Setup</title></head><body>"
    "<h2>OpenSwitchBridge Wi-Fi Setup</h2>"
    "<p>请输入要连接的路由器信息，提交后设备会尝试连接。</p>"
    "<form action=\"/provision\" method=\"get\">"
    "<label>SSID: <input name=\"ssid\" required></label><br><br>"
    "<label>Password: <input name=\"pass\" type=\"password\"></label><br><br>"
    "<button type=\"submit\">Connect</button>"
    "</form>"
    "<p>状态可访问: <a href=\"/health\">/health</a></p>"
    "</body></html>";

static const char *ns_button_name(ns_button_id_t button)
{
    for (size_t i = 0; i < sizeof(s_button_name_map) / sizeof(s_button_name_map[0]); i++) {
        if (s_button_name_map[i].button == button) {
            return s_button_name_map[i].name;
        }
    }
    return "UNKNOWN";
}

static bool ns_button_from_name(const char *name, ns_button_id_t *out_button)
{
    if (name == NULL || out_button == NULL) {
        return false;
    }

    for (size_t i = 0; i < sizeof(s_button_name_map) / sizeof(s_button_name_map[0]); i++) {
        if (strcasecmp(name, s_button_name_map[i].name) == 0) {
            *out_button = s_button_name_map[i].button;
            return true;
        }
    }
    return false;
}

static void ns_http_send_json(httpd_req_t *req, const char *json)
{
    httpd_resp_set_type(req, "application/json");
    httpd_resp_sendstr(req, json);
}

static void ns_button_release_now(void)
{
    ns_protocol_set_test_button(NS_BUTTON_NONE);
    s_button_auto_release_pending = false;
    s_button_auto_release_deadline_us = 0;
}

static void ns_button_press_for_ms(ns_button_id_t button, uint32_t hold_ms)
{
    if (button < NS_BUTTON_NONE || button > NS_BUTTON_RIGHT) {
        return;
    }

    ns_protocol_set_test_button(button);
    if (hold_ms == 0) {
        s_button_auto_release_pending = false;
        s_button_auto_release_deadline_us = 0;
    } else {
        s_button_auto_release_pending = true;
        s_button_auto_release_deadline_us = esp_timer_get_time() + (int64_t)hold_ms * 1000LL;
    }
}

static bool ns_parse_button_from_query(httpd_req_t *req, ns_button_id_t *out_button)
{
    char query[128] = {0};
    char name[32] = {0};
    char id[16] = {0};
    int query_len = httpd_req_get_url_query_len(req);

    if (out_button == NULL || query_len <= 0 || query_len >= (int)sizeof(query)) {
        return false;
    }

    if (httpd_req_get_url_query_str(req, query, sizeof(query)) != ESP_OK) {
        return false;
    }

    if (httpd_query_key_value(query, "name", name, sizeof(name)) == ESP_OK) {
        return ns_button_from_name(name, out_button);
    }

    if (httpd_query_key_value(query, "id", id, sizeof(id)) == ESP_OK) {
        char *end = NULL;
        long parsed_id = strtol(id, &end, 10);
        if (end != id && *end == '\0' && parsed_id >= NS_BUTTON_NONE && parsed_id <= NS_BUTTON_RIGHT) {
            *out_button = (ns_button_id_t)parsed_id;
            return true;
        }
    }

    return false;
}

static bool ns_wifi_save_credentials(const char *ssid, const char *pass)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NS_WIFI_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        return false;
    }

    err = nvs_set_str(handle, NS_WIFI_KEY_SSID, ssid);
    if (err == ESP_OK) {
        err = nvs_set_str(handle, NS_WIFI_KEY_PASS, pass);
    }
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    }
    nvs_close(handle);
    return err == ESP_OK;
}

static void ns_wifi_load_credentials(void)
{
    nvs_handle_t handle;
    size_t ssid_len = sizeof(s_sta_ssid);
    size_t pass_len = sizeof(s_sta_pass);

    s_wifi_creds_loaded = false;
    s_sta_ssid[0] = '\0';
    s_sta_pass[0] = '\0';

    if (nvs_open(NS_WIFI_NAMESPACE, NVS_READONLY, &handle) != ESP_OK) {
        return;
    }

    if (nvs_get_str(handle, NS_WIFI_KEY_SSID, s_sta_ssid, &ssid_len) == ESP_OK &&
        nvs_get_str(handle, NS_WIFI_KEY_PASS, s_sta_pass, &pass_len) == ESP_OK &&
        s_sta_ssid[0] != '\0') {
        s_wifi_creds_loaded = true;
    }

    nvs_close(handle);
}

static esp_err_t ns_wifi_set_sta_cfg(const char *ssid, const char *pass)
{
    wifi_config_t sta_cfg = {0};

    strncpy((char *)sta_cfg.sta.ssid, ssid, sizeof(sta_cfg.sta.ssid) - 1);
    strncpy((char *)sta_cfg.sta.password, pass, sizeof(sta_cfg.sta.password) - 1);
    sta_cfg.sta.threshold.authmode = WIFI_AUTH_OPEN;
    return esp_wifi_set_config(WIFI_IF_STA, &sta_cfg);
}

static void ns_wifi_try_connect_sta(void)
{
    esp_err_t err;

    if (!s_wifi_creds_loaded || s_sta_ssid[0] == '\0') {
        ESP_LOGW(TAG, "Skip STA connect: credentials not ready");
        return;
    }

    ESP_LOGI(TAG, "STA connect flow start: ssid=%s pass_len=%u",
             s_sta_ssid, (unsigned)strlen(s_sta_pass));

    err = ns_wifi_set_sta_cfg(s_sta_ssid, s_sta_pass);
    if (err == ESP_ERR_WIFI_STATE) {
        ESP_LOGW(TAG, "STA busy when set config, restart Wi-Fi and retry");
        err = esp_wifi_stop();
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "esp_wifi_stop failed: %s", esp_err_to_name(err));
            return;
        }
        err = esp_wifi_start();
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "esp_wifi_start failed: %s", esp_err_to_name(err));
            return;
        }
        err = ns_wifi_set_sta_cfg(s_sta_ssid, s_sta_pass);
    }

    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_wifi_set_config(STA) failed: %s", esp_err_to_name(err));
        return;
    }

    err = esp_wifi_connect();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_wifi_connect failed: %s", esp_err_to_name(err));
        return;
    }

    ESP_LOGI(TAG, "Try connect router ssid=%s", s_sta_ssid);
}

static void ns_wifi_enter_provision_mode(const char *reason)
{
    wifi_config_t ap_cfg = {
        .ap = {
            .ssid = NS_SETUP_AP_SSID,
            .password = NS_SETUP_AP_PASS,
            .ssid_len = strlen(NS_SETUP_AP_SSID),
            .channel = 1,
            .max_connection = NS_SETUP_AP_MAX_CONN,
            .authmode = WIFI_AUTH_WPA2_PSK,
        },
    };
    esp_err_t err;

    if (!s_wifi_inited) {
        return;
    }

    s_provision_mode = true;
    err = esp_wifi_set_mode(WIFI_MODE_APSTA);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "enter provision mode failed(set_mode): %s", esp_err_to_name(err));
        return;
    }

    err = esp_wifi_set_config(WIFI_IF_AP, &ap_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "enter provision mode failed(set_ap): %s", esp_err_to_name(err));
        return;
    }

    ESP_LOGI(TAG, "Provision mode enabled (%s). Connect AP %s / %s",
             reason ? reason : "manual", NS_SETUP_AP_SSID, NS_SETUP_AP_PASS);
}

static void ns_wifi_enter_sta_mode(void)
{
    esp_err_t err;

    if (!s_wifi_inited || !s_wifi_creds_loaded || s_sta_ssid[0] == '\0') {
        return;
    }

    s_provision_mode = false;
    err = esp_wifi_set_mode(WIFI_MODE_STA);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "enter STA mode failed(set_mode): %s", esp_err_to_name(err));
        return;
    }

    ns_wifi_try_connect_sta();
}

static esp_err_t ns_health_get_handler(httpd_req_t *req)
{
    char response[320] = {0};
    snprintf(response, sizeof(response),
             "{\"ok\":true,\"service\":\"wifi-control\","
             "\"provision_mode\":%s,\"setup_ap\":\"%s\","
             "\"sta_connected\":%s,\"ip\":\"%s\",\"ssid\":\"%s\"}",
             s_provision_mode ? "true" : "false",
             NS_SETUP_AP_SSID,
             s_sta_connected ? "true" : "false",
             s_sta_connected ? s_sta_ip : "",
             s_wifi_creds_loaded ? s_sta_ssid : "");
    ns_http_send_json(req, response);
    return ESP_OK;
}

static esp_err_t ns_root_get_handler(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_sendstr(req, s_setup_html);
    return ESP_OK;
}

static esp_err_t ns_auto_get_handler(httpd_req_t *req)
{
    ns_button_release_now();
    ns_http_send_json(req, "{\"ok\":true,\"mode\":\"auto\"}");
    return ESP_OK;
}

static esp_err_t ns_button_get_handler(httpd_req_t *req)
{
    ns_button_id_t button = NS_BUTTON_NONE;

    if (!ns_parse_button_from_query(req, &button)) {
        httpd_resp_set_status(req, "400 Bad Request");
        ns_http_send_json(req, "{\"ok\":false,\"error\":\"use name=<A|B|X|Y...> or id=<0..18>\"}");
        return ESP_OK;
    }

    ns_button_press_for_ms(button, 0);

    char response[96] = {0};
    snprintf(response, sizeof(response),
             "{\"ok\":true,\"mode\":\"manual\",\"button\":\"%s\",\"id\":%d}",
             ns_button_name(button), (int)button);
    ns_http_send_json(req, response);
    return ESP_OK;
}

static esp_err_t ns_press_get_handler(httpd_req_t *req)
{
    ns_button_id_t button = NS_BUTTON_NONE;

    if (!ns_parse_button_from_query(req, &button)) {
        httpd_resp_set_status(req, "400 Bad Request");
        ns_http_send_json(req, "{\"ok\":false,\"error\":\"use name=<A|B|X|Y...> or id=<0..18>\"}");
        return ESP_OK;
    }

    ns_button_press_for_ms(button, NS_PRESS_DEFAULT_MS);
    char response[128] = {0};
    snprintf(response, sizeof(response),
             "{\"ok\":true,\"mode\":\"press\",\"button\":\"%s\",\"id\":%d,\"ms\":%d}",
             ns_button_name(button), (int)button, NS_PRESS_DEFAULT_MS);
    ns_http_send_json(req, response);
    return ESP_OK;
}

static esp_err_t ns_hold_get_handler(httpd_req_t *req)
{
    char query[128] = {0};
    char ms_buf[16] = {0};
    ns_button_id_t button = NS_BUTTON_NONE;
    uint32_t hold_ms = NS_PRESS_DEFAULT_MS;

    if (!ns_parse_button_from_query(req, &button)) {
        httpd_resp_set_status(req, "400 Bad Request");
        ns_http_send_json(req, "{\"ok\":false,\"error\":\"use name=<A|B|X|Y...> or id=<0..18>\"}");
        return ESP_OK;
    }

    if (httpd_req_get_url_query_len(req) > 0 &&
        httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK &&
        httpd_query_key_value(query, "ms", ms_buf, sizeof(ms_buf)) == ESP_OK) {
        char *end = NULL;
        long parsed_ms = strtol(ms_buf, &end, 10);
        if (end != ms_buf && *end == '\0') {
            if (parsed_ms < NS_HOLD_MIN_MS) {
                parsed_ms = NS_HOLD_MIN_MS;
            } else if (parsed_ms > NS_HOLD_MAX_MS) {
                parsed_ms = NS_HOLD_MAX_MS;
            }
            hold_ms = (uint32_t)parsed_ms;
        }
    }

    ns_button_press_for_ms(button, hold_ms);
    char response[128] = {0};
    snprintf(response, sizeof(response),
             "{\"ok\":true,\"mode\":\"hold\",\"button\":\"%s\",\"id\":%d,\"ms\":%u}",
             ns_button_name(button), (int)button, (unsigned)hold_ms);
    ns_http_send_json(req, response);
    return ESP_OK;
}

static esp_err_t ns_release_get_handler(httpd_req_t *req)
{
    ns_button_release_now();
    ns_http_send_json(req, "{\"ok\":true,\"mode\":\"release\"}");
    return ESP_OK;
}

static esp_err_t ns_provision_get_handler(httpd_req_t *req)
{
    char query[192] = {0};
    char ssid[33] = {0};
    char pass[65] = {0};
    int query_len = httpd_req_get_url_query_len(req);

    if (query_len <= 0 || query_len >= (int)sizeof(query)) {
        httpd_resp_set_status(req, "400 Bad Request");
        ns_http_send_json(req, "{\"ok\":false,\"error\":\"missing query\"}");
        return ESP_OK;
    }

    if (httpd_req_get_url_query_str(req, query, sizeof(query)) != ESP_OK) {
        httpd_resp_set_status(req, "400 Bad Request");
        ns_http_send_json(req, "{\"ok\":false,\"error\":\"invalid query\"}");
        return ESP_OK;
    }

    if (httpd_query_key_value(query, "ssid", ssid, sizeof(ssid)) != ESP_OK || ssid[0] == '\0') {
        httpd_resp_set_status(req, "400 Bad Request");
        ns_http_send_json(req, "{\"ok\":false,\"error\":\"ssid is required\"}");
        return ESP_OK;
    }

    httpd_query_key_value(query, "pass", pass, sizeof(pass));

    if (!ns_wifi_save_credentials(ssid, pass)) {
        httpd_resp_set_status(req, "500 Internal Server Error");
        ns_http_send_json(req, "{\"ok\":false,\"error\":\"save credentials failed\"}");
        return ESP_OK;
    }

    strncpy(s_sta_ssid, ssid, sizeof(s_sta_ssid) - 1);
    strncpy(s_sta_pass, pass, sizeof(s_sta_pass) - 1);
    s_wifi_creds_loaded = true;
    s_sta_connected = false;
    s_sta_ip[0] = '\0';
    ESP_LOGI(TAG, "Provision received: ssid=%s pass_len=%u",
             s_sta_ssid, (unsigned)strlen(s_sta_pass));

    if (s_wifi_inited) {
        ns_wifi_enter_sta_mode();
    }

    ns_http_send_json(req, "{\"ok\":true,\"msg\":\"saved and switching to STA reconnect...\"}");
    return ESP_OK;
}

static void ns_http_server_start(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    httpd_handle_t server = NULL;

    httpd_uri_t root_uri = {
        .uri = "/",
        .method = HTTP_GET,
        .handler = ns_root_get_handler,
        .user_ctx = NULL,
    };
    httpd_uri_t health_uri = {
        .uri = "/health",
        .method = HTTP_GET,
        .handler = ns_health_get_handler,
        .user_ctx = NULL,
    };
    httpd_uri_t provision_uri = {
        .uri = "/provision",
        .method = HTTP_GET,
        .handler = ns_provision_get_handler,
        .user_ctx = NULL,
    };
    httpd_uri_t button_uri = {
        .uri = "/button",
        .method = HTTP_GET,
        .handler = ns_button_get_handler,
        .user_ctx = NULL,
    };
    httpd_uri_t press_uri = {
        .uri = "/press",
        .method = HTTP_GET,
        .handler = ns_press_get_handler,
        .user_ctx = NULL,
    };
    httpd_uri_t hold_uri = {
        .uri = "/hold",
        .method = HTTP_GET,
        .handler = ns_hold_get_handler,
        .user_ctx = NULL,
    };
    httpd_uri_t release_uri = {
        .uri = "/release",
        .method = HTTP_GET,
        .handler = ns_release_get_handler,
        .user_ctx = NULL,
    };
    httpd_uri_t auto_uri = {
        .uri = "/auto",
        .method = HTTP_GET,
        .handler = ns_auto_get_handler,
        .user_ctx = NULL,
    };

    if (s_http_server_started) {
        return;
    }

    ESP_ERROR_CHECK(httpd_start(&server, &config));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &root_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &health_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &provision_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &button_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &press_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &hold_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &release_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &auto_uri));
    s_http_server_started = true;
    ESP_LOGI(TAG, "HTTP control ready on port %d", config.server_port);
}

static void ns_wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    (void)arg;

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "WIFI_EVENT_STA_START");
        if (s_wifi_creds_loaded) {
            esp_wifi_connect();
        }
        return;
    }

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_CONNECTED) {
        wifi_event_sta_connected_t *event = (wifi_event_sta_connected_t *)event_data;
        ESP_LOGI(TAG, "WIFI_EVENT_STA_CONNECTED ssid=%.*s channel=%u authmode=%u",
                 event->ssid_len, (char *)event->ssid,
                 (unsigned)event->channel, (unsigned)event->authmode);
        return;
    }

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *event = (wifi_event_sta_disconnected_t *)event_data;
        s_sta_connected = false;
        s_sta_ip[0] = '\0';
        ESP_LOGW(TAG, "WIFI_EVENT_STA_DISCONNECTED reason=%u ssid=%.*s",
                 (unsigned)event->reason, event->ssid_len, (char *)event->ssid);
        if (s_wifi_creds_loaded) {
            esp_wifi_connect();
            ESP_LOGW(TAG, "Wi-Fi disconnected, retry...");
        }
        return;
    }

    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        s_sta_connected = true;
        snprintf(s_sta_ip, sizeof(s_sta_ip), IPSTR, IP2STR(&event->ip_info.ip));
        ESP_LOGI(TAG, "Wi-Fi connected, IP: %s", s_sta_ip);
        return;
    }
}

static void ns_provision_button_init(void)
{
    gpio_config_t io_conf = {
        .pin_bit_mask = 1ULL << NS_PROVISION_TRIGGER_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io_conf);
}

static void ns_wifi_init(void)
{
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    wifi_config_t ap_cfg = {
        .ap = {
            .ssid = NS_SETUP_AP_SSID,
            .password = NS_SETUP_AP_PASS,
            .ssid_len = strlen(NS_SETUP_AP_SSID),
            .channel = 1,
            .max_connection = NS_SETUP_AP_MAX_CONN,
            .authmode = WIFI_AUTH_WPA2_PSK,
        },
    };
    esp_err_t err;

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_ap();
    esp_netif_create_default_wifi_sta();

    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                        &ns_wifi_event_handler, NULL, &s_wifi_event_instance));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                        &ns_wifi_event_handler, NULL, &s_ip_event_instance));

    if (s_wifi_creds_loaded) {
        s_provision_mode = false;
        err = esp_wifi_set_mode(WIFI_MODE_STA);
        ESP_ERROR_CHECK(err);
        err = ns_wifi_set_sta_cfg(s_sta_ssid, s_sta_pass);
        ESP_ERROR_CHECK(err);
        ESP_LOGI(TAG, "Found saved Wi-Fi credentials. Boot in STA mode.");
    } else {
        s_provision_mode = true;
        err = esp_wifi_set_mode(WIFI_MODE_AP);
        ESP_ERROR_CHECK(err);
        err = esp_wifi_set_config(WIFI_IF_AP, &ap_cfg);
        ESP_ERROR_CHECK(err);
        ESP_LOGI(TAG, "No saved credentials. Boot in provisioning AP mode.");
    }

    ESP_ERROR_CHECK(esp_wifi_start());
    s_wifi_inited = true;

    if (s_provision_mode) {
        ESP_LOGI(TAG, "Provision AP: ssid=%s password=%s", NS_SETUP_AP_SSID, NS_SETUP_AP_PASS);
        ESP_LOGI(TAG, "Open http://192.168.4.1/ to configure router.");
    }
}

void ns_wifi_control_start(void)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    } else {
        ESP_ERROR_CHECK(ret);
    }

    s_http_server_started = false;
    s_sta_connected = false;
    s_wifi_inited = false;
    s_provision_mode = false;
    s_sta_ip[0] = '\0';
    s_provision_btn_pressed = false;
    s_provision_btn_triggered = false;
    s_provision_btn_press_start_us = 0;
    s_button_auto_release_pending = false;
    s_button_auto_release_deadline_us = 0;

    ns_wifi_load_credentials();
    ns_provision_button_init();
    ns_wifi_init();
    ns_http_server_start();
}

void ns_wifi_control_periodic(void)
{
    int level = gpio_get_level(NS_PROVISION_TRIGGER_GPIO);
    int64_t now = esp_timer_get_time();

    if (s_button_auto_release_pending && now >= s_button_auto_release_deadline_us) {
        ns_button_release_now();
    }

    if (level == 0) {
        if (!s_provision_btn_pressed) {
            s_provision_btn_pressed = true;
            s_provision_btn_press_start_us = now;
        } else if (!s_provision_btn_triggered &&
                   (now - s_provision_btn_press_start_us >= NS_PROVISION_HOLD_US)) {
            s_provision_btn_triggered = true;
            ns_wifi_enter_provision_mode("gpio35 long press");
        }
    } else {
        s_provision_btn_pressed = false;
        s_provision_btn_triggered = false;
        s_provision_btn_press_start_us = 0;
    }
}
