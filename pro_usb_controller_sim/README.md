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
