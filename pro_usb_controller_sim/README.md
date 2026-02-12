# Pro USB Controller Simulator (Framework)

This project is an ESP-IDF framework for simulating a Nintendo Switch Pro Controller over USB HID.

## Scope

Current baseline implements:

- USB private command channel (`0x80` -> `0x81`)
- Subcommand channel (`0x01` -> `0x21`)
- Standard periodic input report (`0x30`, 60 Hz)
- Minimal subcommands:
- `0x02` device info
- `0x03` set input report mode
- `0x10` SPI flash read (calibration window stub)
- `0x30` player lights
- `0x40` IMU enable
- `0x48` vibration enable
- `BOOT` button (`GPIO0`, active-low) mapped to controller `A` key for quick testing
- Wi-Fi AP + HTTP control endpoint for button triggering

## Project Layout

- `main/ns_proto.h`: protocol constants and runtime state model
- `main/ns_descriptors.c`: USB device/config/report descriptors
- `main/ns_protocol.c`: command handlers, report builders, session state
- `main/main.c`: TinyUSB bootstrap + callback bridge

## Build

```bash
idf.py set-target esp32s3
idf.py build
idf.py -p <PORT> flash monitor
```

## Wi-Fi Control（自动重连 + 配网模式）

当前行为：

1. **首次无凭据**：自动进入配网模式（AP）
   - SSID: `OpenSwitchBridge-Setup`
   - Password: `12345678`
   - 配网页面: `http://192.168.4.1/`
2. **已配网成功**：保存路由器账号密码到 NVS，后续上电自动 STA 重连
3. **强制进配网**：`GPIO35` 长按 5 秒进入配网模式（默认上拉，接地为按下）

配网后串口日志出现 `Wi-Fi connected, IP: x.x.x.x`，即可通过该 IP 调用 HTTP 控制接口（端口 `80`）。

Endpoints:

- `GET /health`
- `GET /button?name=A` (manual button override; supports `A/B/X/Y/L/R/ZL/ZR/UP/DOWN/LEFT/RIGHT/...`)
- `GET /press?name=A` (press + auto release, default 100ms)
- `GET /hold?name=A&ms=500` (press and hold for specified duration, then auto release)
- `GET /release` (immediate release)
- `GET /button?id=4` (by enum id, `0..18`)
- `GET /auto` (exit manual override and return to GPIO0-triggered auto test flow)

Examples:

```bash
# 配网（首次/强制配网时，连接 AP 后执行）
curl "http://192.168.4.1/provision?ssid=YOUR_WIFI&pass=YOUR_PASS"

# 路由器下调用
curl "http://<ESP_IP>/health"
curl "http://<ESP_IP>/button?name=A"
curl "http://<ESP_IP>/press?name=B"
curl "http://<ESP_IP>/hold?name=HOME&ms=800"
curl "http://<ESP_IP>/release"
curl "http://<ESP_IP>/button?name=HOME"
curl "http://<ESP_IP>/auto"
```

Python API smoke test:

```bash
python3 test_http_api.py --host <ESP_IP> --port 80

# Stress test (random button hold)
python3 test_http_api.py --host <ESP_IP> --stress --loops 500 --interval 0.1
```

## Quick Switch Test

1. Flash firmware to an ESP32-S3 board with USB-OTG device support.
2. Connect board USB to Switch dock or Switch USB adapter.
3. In controller test screen on Switch, verify the controller appears.
4. Press board `BOOT` button and check `A` button activity on Switch.

## Next Extensions

1. Add `0x31` NFC/IR mode report path.
2. Add full SPI data model (factory/user calibration and colors).
3. Add real input source adapter (GPIO/UART/BLE bridge/scripted replay).
4. Improve feature report coverage beyond `0x02`.
