# OpenSwitchBridge (Open-Source Switch Control Interface)

> Keywords: Nintendo, Nintendo Switch, Switch Controller, Pro Controller, ESP32

## Project Goal

OpenSwitchBridge is an **open-source Nintendo Switch control interface** project.
It is designed to let external devices (such as PCs and phones) call and control Switch gameplay more easily, enabling more interaction possibilities.

## Vision

- Provide a unified, open, and extensible control interface
- Reduce integration cost for secondary development
- Support multiple input sources (software commands, sensors, motion input, etc.)

## Why ESP32

ESP32 is selected as the core platform because:

- Built-in Bluetooth capability for wireless control extensions
- Built-in Wi-Fi capability for LAN/remote control extensions
- Low cost, mature ecosystem, flexible deployment

## Current Status

- Completed: **USB Switch controller emulation (Pro Controller profile)**
- Verified: ESP32 works as a USB device and completes the basic controller communication flow with Switch

## Project Dependencies and Versions

Current project path: `OpenSwitchBridge/pro_usb_controller_sim`

- Target chip: `ESP32-S3`
- ESP-IDF version: `6.1.0` (see `pro_usb_controller_sim/dependencies.lock`)
- `espressif/esp_tinyusb`: `2.1.0`
- `espressif/tinyusb`: `0.19.0~2`

Dependency notes:

- `pro_usb_controller_sim/managed_components` already includes component sources
- In normal cases, this project can be built offline after upload (without pulling dependencies again)

## Build

Run in `pro_usb_controller_sim` directory:

```bash
source /path/to/esp-idf/export.sh
idf.py build
```

## TODO

- Add a demo:
  - Recognize human motion on PC side
  - Map different motions to different button triggers
  - Drive Switch interactions

## References

- `dekuNukem/Nintendo_Switch_Reverse_Engineering`  
  `https://github.com/dekuNukem/Nintendo_Switch_Reverse_Engineering`
- `omakoto/raspberry-switch-control`  
  `https://github.com/omakoto/raspberry-switch-control`
- `mzyy94/nscon`  
  `https://github.com/mzyy94/nscon`
- `joycon_reader` (inside `Nintendo_Switch_Reverse_Engineering`)  
  `https://github.com/dekuNukem/Nintendo_Switch_Reverse_Engineering/tree/master/joycon_reader`
- `joycon_spoofer` (inside `Nintendo_Switch_Reverse_Engineering`)  
  `https://github.com/dekuNukem/Nintendo_Switch_Reverse_Engineering/tree/master/joycon_spoofer`

## Notes

- Parts of this project were generated or organized with AI assistance.
- If you encounter any issues, please contact the author.
