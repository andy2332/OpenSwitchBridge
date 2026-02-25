# 01 Keyboard Mapping Demo

将 PC 键盘按键实时映射为 OpenSwitchBridge 的 HTTP 输入，便于快速联调按键、组合键和长按行为。

## 文件

- `pc_keyboard_bridge.py`：键盘映射脚本（已从 `pro_usb_controller_sim/` 移动到本目录）
- `requirements.txt`：可选依赖（`pynput`，用于更好的 `--cli` 按下/松开监听）

## 依赖安装（可选）

```bash
python3 -m pip install -r examples/01_keyboard_mapping/requirements.txt
```

## 使用方式

在仓库根目录运行：

```bash
python3 examples/01_keyboard_mapping/pc_keyboard_bridge.py --host <ESP_IP> --port 80
# 无 tkinter 时可强制非 GUI 模式（默认使用按下/松开监听）
python3 examples/01_keyboard_mapping/pc_keyboard_bridge.py --host <ESP_IP> --port 80 --cli
# 仅在无法使用 pynput 时，才使用 toggle 终端模式
python3 examples/01_keyboard_mapping/pc_keyboard_bridge.py --host <ESP_IP> --port 80 --cli --cli-toggle
```

如果在 `examples/01_keyboard_mapping` 目录内运行：

```bash
python3 pc_keyboard_bridge.py --host <ESP_IP> --port 80
```

## 默认按键映射

先聚焦脚本窗口，再按键：

- `J/I/K/L` -> `Y/X/B/A`
- `Q/E` -> `L/R`
- `1/3` -> `ZL/ZR`
- `Backspace/Enter` -> `MINUS/PLUS`
- `Z/C` -> `L_STICK/R_STICK`
- `W/A/S/D` -> 左摇杆 `L_STICK` 上/左/下/右（`lx/ly`）
- `8/5/4/6` -> 右摇杆 `R_STICK` 上/下/左/右（`rx/ry`）
- `H/P` -> `HOME/CAPTURE`
- `Arrow keys` -> `UP/DOWN/LEFT/RIGHT`

## 模式说明

- GUI 模式：按下即发送按下，松开即发送释放
- `--cli`：优先使用 `pynput` 的按下/松开语义（按住=按下，松开=释放，`ESC` 退出）
- `--cli --cli-toggle`：终端 toggle 模式（按一次按下，再按一次松开）
- 对于摇杆方向键：支持同时按多个方向；相反方向同时按下会回到中位
