# Nintendo Switch USB Device Simulation Protocol Summary (Current `pro_usb_controller_sim` Implementation)

This document is based on the current code in `pro_usb_controller_sim`, not a generic reverse-engineering summary.  
Focus: what the ESP32-S3 firmware currently does and how the USB protocol flow is implemented.

## 1. Scope and Goal

- Goal: enumerate ESP32-S3 as a Nintendo Switch Pro Controller-like USB HID device and complete basic wired handshake + button input on Switch.
- Current input source: `GPIO0` (active low) mapped to A button.
- Current protocol scope: minimal working subset (USB private commands, subcommands, SPI reads, mode switching, periodic state reports, basic ACK behavior).

## 2. USB Descriptor and HID Layout

Implementation: `pro_usb_controller_sim/main/ns_descriptors.c`

- VID/PID: `0x057E:0x2009` (Pro Controller)
- HID interface: single interface with IN+OUT interrupt endpoints
  - IN EP: `0x81`
  - OUT EP: `0x01`
  - Max packet size: 64
- String descriptors:
  - Manufacturer: `Nintendo Co., Ltd.`
  - Product: `Pro Controller`
- Report map includes key IDs:
  - Device -> Host: `0x21`, `0x30`, `0x81`
  - Host -> Device: `0x01`, `0x10`, `0x80`

Notes:
- Current implementation works with 64-byte HID reports (Report ID + 63-byte payload).
- `TUD_HID_INOUT_DESCRIPTOR` is enabled (important for host compatibility).

## 3. High-Level Runtime Flow

Implementation: `pro_usb_controller_sim/main/main.c`

1. `app_main()` starts and calls `ns_protocol_init()`.
2. TinyUSB device stack is installed (`tinyusb_driver_install`).
3. Main loop runs every `15ms`, calling `ns_protocol_periodic()`.
4. HID callbacks bridge to protocol layer:
   - `tud_hid_set_report_cb()` -> `ns_protocol_set_report()` (host-to-device)
   - `tud_hid_get_report_cb()` -> `ns_protocol_get_report()` (feature reads)

## 4. Protocol State Machine

Implementation: `pro_usb_controller_sim/main/ns_protocol.c`

Main state fields (`ns_state_t` in `ns_proto.h`):
- `report_mode` (default `0x30`)
- `input_streaming` (controlled by USB cmd `0x04/0x05`)
- `usb_handshaked`, `usb_baud_3m`, `usb_no_timeout`
- `imu_enabled`, `vibration_enabled`, `player_lights`

Periodic report gate:
- send only when `tud_mounted()==true`
- and `input_streaming==true`

## 5. Report IDs and Channels (Implemented)

### Host -> Device

- `0x80`: USB private command channel (handshake/control/stream state)
- `0x01`: subcommand channel (rumble + subcommand)
- `0x10`: rumble-only (accepted, currently no-op)

### Device -> Host

- `0x81`: USB private command reply
- `0x21`: subcommand reply
- `0x30`: standard state report
- `0x3F`: simplified state report (if report mode set to `0x3F`)

### Feature

- `Report ID 0x02`: returns cached image of latest subcommand reply

## 6. USB Private Commands (`0x80`) Behavior

Implementation: `ns_handle_usb_cmd()`

- `0x01` Connection Status
  - reply: `0x81 0x01` + `00 03 00 00 5e 00 53 5e`
- `0x02` Handshake
  - sets `usb_handshaked=true`
  - replies with empty payload
- `0x03` Baudrate 3M
  - sets `usb_baud_3m=true`
  - replies with empty payload
- `0x04` No Timeout
  - sets `usb_no_timeout=true`
  - sets `input_streaming=true` (start periodic input)
  - no immediate reply
- `0x05` Enable Timeout
  - clears `usb_no_timeout`
  - sets `input_streaming=false` (stop periodic input)
  - no immediate reply
- `0x06` Reset
  - calls `ns_protocol_init()`
  - replies with empty payload
- others
  - fallback empty reply

## 7. Subcommands (`0x01`) Behavior

Implementation: `ns_handle_subcmd()`

Common `0x21` reply payload format:
- Byte 0: timer
- Byte 1: status (currently fixed `0x81`)
- Byte 2..11: base input state (buttons/sticks)
- Byte 12: `ack_type`
- Byte 13: `subcmd_id`
- Byte 14..: subcommand data

Implemented subcommands:
- `0x02` Request Device Info
  - ACK `0x82`
  - fixed 12-byte device info payload
- `0x03` Set Report Mode
  - ACK `0x80`
  - updates `report_mode`
- `0x10` SPI Flash Read
  - ACK `0x90` on success, `0x00` on failure
  - data format: `addr(4)+len(1)+bytes...`
  - implemented banks: `0x60` and `0x80` only (static ROM tables)
- `0x21`
  - ACK `0xA0`
  - data: `01 00 ff 00 03 00 05 01`
- `0x30` Set Player Lights
  - ACK `0x80`
- `0x40` Enable IMU
  - ACK `0x80`
- `0x48` Enable Vibration
  - ACK `0x80`
- others
  - compatibility ACK `0x80` with empty data

## 8. Input Report Content (`0x30` / `0x3F`)

### `0x30` Standard Report

- period: `15ms` (`NS_STD_PERIOD_MS`)
- sticks: both centered (`0x0800`)
- A button: from `GPIO0` active-low (`0x08` bit)
- other buttons/IMU: fixed/minimal baseline values

### `0x3F` Simplified Report

- emitted only when report mode is `0x3F`
- includes A button state; other fields are neutral/fixed

## 9. Verified Handshake Sequence (from logs)

Typical observed sequence (can repeat):

1. USB mount (`tud_mounted: 0 -> 1`)
2. `usb cmd 0x02` (handshake)
3. `usb cmd 0x01` (status)
4. multiple `subcmd 0x02 / 0x10`
5. `usb cmd 0x03` (3M)
6. `usb cmd 0x04` (start streaming)
7. `subcmd 0x03` sets `report mode 0x30`
8. continuous `0x30` input reports

## 10. GPIO Button Mapping

- Pin: `GPIO0` (BOOT on many ESP32-S3 boards)
- Active low:
  - `GPIO0=0` -> A pressed
  - `GPIO0=1` -> A released
- State-change logs:
  - `GPIO0 A key: pressed/released`
  - `A output: pressed/released`

## 11. Relation to Original Reverse-Engineering Notes

- This file is implementation-focused and tracks current working firmware behavior.
- Original repo notes cover much broader paths (BT, NFC/IR, MCU, update flows) not fully implemented here.
- For minimal USB Pro simulation, practical path is now centered on:
  - `0x80` private USB commands
  - `0x01` subcommands
  - periodic `0x30` reports

## 12. Next Extension Targets

- Map more real inputs (buttons/sticks) into `0x30` payload.
- Expand SPI readable regions to reduce `0x10` NACKs.
- Add `0x31`/NFC/IR and richer IMU data paths.
