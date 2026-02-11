# Nintendo Switch USB 设备模拟协议整理（中文，当前 `pro_usb_controller_sim` 实现版）

本文基于当前工程代码（`pro_usb_controller_sim`）整理，不是泛化笔记。重点是“现在这份 ESP32-S3 程序到底做了什么、协议怎么走”。

## 1. 工程目标与边界

- 目标：把 ESP32-S3 枚举成 Nintendo Switch Pro Controller 风格 USB HID 设备，并在 Switch 上完成有线握手与基础按键输入。
- 当前输入源：`GPIO0`（低电平按下）映射为 A 键。
- 当前范围：最小可用协议子集（连接、握手、模式切换、SPI 读、基础状态上报、灯/IMU/振动开关 ACK）。

## 2. 设备描述符与 HID 架构

实现文件：`pro_usb_controller_sim/main/ns_descriptors.c`

- VID/PID：`0x057E:0x2009`（Pro Controller）
- HID 接口：1 个接口，IN+OUT 双中断端点
  - IN EP：`0x81`
  - OUT EP：`0x01`
  - MPS：64
- 字符串描述符：
  - Manufacturer：`Nintendo Co., Ltd.`
  - Product：`Pro Controller`
- Report Map 包含关键 Report ID：
  - Device -> Host：`0x21`、`0x30`、`0x81`
  - Host -> Device：`0x01`、`0x10`、`0x80`

关键点：
- 当前实现按 64 字节 HID 报告工作（Report ID + 63 字节 payload）。
- `TUD_HID_INOUT_DESCRIPTOR` 已启用，避免仅 IN 端点导致主机流程异常。

## 3. 程序主流程（代码级）

实现文件：`pro_usb_controller_sim/main/main.c`

1. `app_main()` 启动，调用 `ns_protocol_init()` 初始化协议状态。
2. 注册并安装 TinyUSB 设备栈（`tinyusb_driver_install`）。
3. 进入主循环，每 `15ms` 调用 `ns_protocol_periodic()`。
4. 通过回调联动协议层：
   - `tud_hid_set_report_cb()` -> `ns_protocol_set_report()`（处理主机下发）
   - `tud_hid_get_report_cb()` -> `ns_protocol_get_report()`（处理 Feature 读）

## 4. 协议层状态机

实现文件：`pro_usb_controller_sim/main/ns_protocol.c`

内部状态 `ns_state_t`（`ns_proto.h`）：
- `report_mode`：当前输入报告模式（默认 `0x30`）
- `input_streaming`：是否开始周期上报（由 USB cmd `0x04/0x05` 控制）
- `usb_handshaked`、`usb_baud_3m`、`usb_no_timeout`
- `imu_enabled`、`vibration_enabled`、`player_lights`

周期上报门控：
- 必须 `tud_mounted()==true`
- 且 `input_streaming==true`
- 才会发 `0x30` 或 `0x3F`

## 5. Report ID 与通道定义（当前实现）

### Host -> Device

- `0x80`：USB 私有命令通道（连接/握手/流控制）
- `0x01`：subcommand 通道（rumble + subcommand）
- `0x10`：rumble-only（当前 no-op 接受）

### Device -> Host

- `0x81`：USB 私有命令回复
- `0x21`：subcommand 回复
- `0x30`：标准状态上报
- `0x3F`：简化状态上报（当 report_mode=0x3F）

### Feature

- `Report ID 0x02`：返回“最近一次 subcommand 回复镜像”

## 6. `0x80` USB 私有命令（当前实现行为）

实现函数：`ns_handle_usb_cmd()`

- `0x01` Conn Status
  - 回复：`0x81 0x01` + `00 03 00 00 5e 00 53 5e`
- `0x02` Handshake
  - 置位 `usb_handshaked=true`
  - 回复空 payload
- `0x03` Baudrate 3M
  - 置位 `usb_baud_3m=true`
  - 回复空 payload
- `0x04` No Timeout
  - 置位 `usb_no_timeout=true`
  - `input_streaming=true`（开始周期输入）
  - 不立即回复（按已验证流程）
- `0x05` Enable Timeout
  - 清 `usb_no_timeout`
  - `input_streaming=false`（停止周期输入）
  - 不立即回复
- `0x06` Reset
  - 调 `ns_protocol_init()`
  - 回复空 payload
- 其他命令
  - 统一回空 payload 回复

## 7. `0x01` Subcommand（当前实现行为）

实现函数：`ns_handle_subcmd()`

通用 `0x21` 回复格式（payload 区）：
- Byte 0: timer
- Byte 1: status（当前固定 `0x81`）
- Byte 2..11: 按键/摇杆等基础状态
- Byte 12: `ack_type`
- Byte 13: `subcmd_id`
- Byte 14..: data

当前支持项：
- `0x02` Request Device Info
  - ACK：`0x82`
  - 固定返回 12 字节设备信息
- `0x03` Set Report Mode
  - ACK：`0x80`
  - 保存 `report_mode`
- `0x10` SPI Flash Read
  - ACK：成功 `0x90`，失败 `0x00`
  - data：`addr(4)+len(1)+bytes...`
  - 目前只实现 bank `0x60` / `0x80`（静态 ROM 表）
- `0x21`
  - ACK：`0xA0`
  - data：`01 00 ff 00 03 00 05 01`
- `0x30` Set Player Lights
  - ACK：`0x80`
- `0x40` Enable IMU
  - ACK：`0x80`
- `0x48` Enable Vibration
  - ACK：`0x80`
- 其他 subcommand
  - 兼容 ACK：`0x80` + 空数据

## 8. 输入报告内容（`0x30` / `0x3F`）

### `0x30` 标准报告

- 周期：`15ms`（`NS_STD_PERIOD_MS`）
- 摇杆：左右均固定中值 `0x0800`
- A 键：来自 `GPIO0`（低电平=按下，位 `0x08`）
- 其余按键/IMU：当前固定值或未动态更新

### `0x3F` 简化报告

- 当 report mode 被设置为 `0x3F` 时发送
- 保留 A 键位，其他字段为固定中立值

## 9. 当前已验证握手时序（从日志归纳）

典型顺序（可能重复）：

1. 枚举成功，`tud_mounted: 0 -> 1`
2. `usb cmd 0x02`（握手）
3. `usb cmd 0x01`（状态查询）
4. 多次 `subcmd 0x02 / 0x10`
5. `usb cmd 0x03`（3M）
6. `usb cmd 0x04`（开始流）
7. `subcmd 0x03` 设置 `report mode 0x30`
8. 持续 `0x30` 输入上报

## 10. GPIO 按键映射

- 引脚：`GPIO0`（多数 ESP32-S3 开发板 BOOT 键）
- 电平：Active Low
  - `GPIO0=0` -> A Pressed
  - `GPIO0=1` -> A Released
- 日志（状态变化时打印）：
  - `GPIO0 A key: pressed/released`
  - `A output: pressed/released`

## 11. 与原始逆向笔记的关系

- 本文档是“实现落地版”，以当前可跑代码为准。
- 原始仓库笔记覆盖更广（蓝牙、NFC/IR、MCU、升级链路），当前工程未完整实现这些分支。
- 对最小 USB Pro 模拟来说，关键路径已收敛在 `0x80` 控制 + `0x01` 子命令 + `0x30` 周期上报。

## 12. 后续扩展建议

- 把 `0x30` 报告中的更多按键/摇杆改为真实输入源（而非固定中值）。
- 扩展更多 SPI 地址段，减少 `0x10` 的 NACK 触发。
- 增加 `0x31`、NFC/IR、更完整 IMU 数据路径。
