# Camera Two-Hand Touch Controller

这是从 `pose_gesture_mvp` 迁移出来的独立项目，仅保留：
- 手柄图片 + 手部位置映射触发按键/摇杆
- `layouts` 配置加载
- 运行时按 `p` 保存调试图

## 目录结构

```text
02_camera_two_hand_touch_controller/
  app.py
  requirements.txt
  setup_venv.sh
  assets/controller_ui.jpg
  configs/default.yaml
  configs/runtime.yaml
  layouts/pro_controller.layout.yaml
  touch_core/
```

## 安装与运行

```bash
cd examples/02_camera_two_hand_touch_controller
bash setup_venv.sh
source .venv/bin/activate
python app.py
```

## 运行时按键

- `q`: 退出
- `r`: 重载 `configs/default.yaml + configs/runtime.yaml`
- `p`: 导出两张调试图到 `debug_outputs/`
  - `controller_base_*.png`：手柄图 + 固定触发位置
  - `controller_touch_render_*.png`：手柄图 + 触发位置 + 左右手腕映射点
- `+/-`: 调整 `controller_touch.global_scale`

## 配置说明

- 触发位布局文件：`layouts/pro_controller.layout.yaml`
- 通过 `configs/default.yaml` 的 `controller_touch.layout_file` 加载布局
- `runtime.yaml` 可用于临时覆盖配置
