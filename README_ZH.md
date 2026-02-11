# OpenSwitchBridge（Switch 控制接口开源项目说明，中文）

> 关键词：任天堂、Nintendo、任天堂 Switch、Nintendo Switch、Switch 手柄、Pro Controller

## 项目目标

本项目的目标是开源一个 **任天堂（Nintendo）Switch 控制接口**，让 PC、手机等设备可以更方便地调用和控制 Switch，给任天堂（Nintendo）游戏平台带来更多玩法可能性。

## 项目愿景

- 对外提供统一、开放、可扩展的控制接口
- 降低二次开发门槛，方便快速接入
- 支持更多输入来源（软件指令、传感器、动作识别等）

## 为什么选择 ESP32

选择 ESP32 作为核心平台，主要原因：

- 自带蓝牙能力，便于扩展蓝牙控制链路
- 自带 Wi-Fi 能力，便于扩展局域网/远程控制
- 成本低、开发生态成熟、部署灵活

## 当前进度

- 已完成：**USB 模拟 Switch 手柄（Pro Controller）**
- 已验证：ESP32 作为 USB 设备与 Switch 建立基础手柄通信流程

## 工程依赖与版本

当前工程目录：`OpenSwitchBridge/pro_usb_controller_sim`

- 目标芯片：`ESP32-S3`
- ESP-IDF 版本：`6.1.0`（见 `pro_usb_controller_sim/dependencies.lock`）
- `espressif/esp_tinyusb`：`2.1.0`
- `espressif/tinyusb`：`0.19.0~2`

依赖说明：

- `pro_usb_controller_sim/managed_components` 已包含组件源码
- 常规情况下上传本项目后可直接离线编译（不依赖二次拉取组件）

## 编译方式

在 `pro_usb_controller_sim` 目录执行：

```bash
source /path/to/esp-idf/export.sh
idf.py build
```

## 后续规划

- 增加蓝牙控制接口
- 增加 Wi-Fi 控制接口
- 统一上层控制协议，便于 PC/手机等端调用

## TODO

- 增加一个 demo：
  - 在 PC 侧识别人体动作
  - 将不同动作映射为不同按键触发
  - 驱动 Switch 进行交互

## 参考项目

- `dekuNukem/Nintendo_Switch_Reverse_Engineering`  
  `https://github.com/dekuNukem/Nintendo_Switch_Reverse_Engineering`
- `omakoto/raspberry-switch-control`  
  `https://github.com/omakoto/raspberry-switch-control`
- `mzyy94/nscon`  
  `https://github.com/mzyy94/nscon`
- `joycon_reader`（在 `Nintendo_Switch_Reverse_Engineering` 仓库内）  
  `https://github.com/dekuNukem/Nintendo_Switch_Reverse_Engineering/tree/master/joycon_reader`
- `joycon_spoofer`（在 `Nintendo_Switch_Reverse_Engineering` 仓库内）  
  `https://github.com/dekuNukem/Nintendo_Switch_Reverse_Engineering/tree/master/joycon_spoofer`

## 说明

- 本项目部分代码由 AI 参与生成与整理。
- 如有任何问题，请联系作者。
