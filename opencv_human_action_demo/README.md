# OpenCV Human Action Demo

一个独立的 OpenCV 示例工程，用于：

- 人体检测（默认人脸推导上半身，其次上半身，再回退全身）
- 绘制人体整体框架（简化骨架）
- 动作识别（站立 / 行走 / 上肢活动）

> 说明：该工程不依赖大型深度学习模型，默认使用 OpenCV HOG 检测和运动启发式规则，便于快速运行验证。
> 已支持可选 MediaPipe Pose 关键点绘制，用于更准确地对应手臂动作。

## 目录结构

```text
opencv_human_action_demo/
├── README.md
├── arm_pose_demo.py
├── requirements.txt
└── run.py
```

## 安装依赖

```bash
cd opencv_human_action_demo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> 兼容性提示：`mediapipe` 的 `Pose (mp.solutions.pose)` 在 Python 3.13 环境下常不可用。  
> 建议使用 Python 3.11 或 3.12 创建虚拟环境。

## Python 版本要求

- 推荐：`Python 3.11.x`（本项目已验证）
- 可选：`Python 3.12.x`
- 不建议：`Python 3.13.x`（常见 `mediapipe` 接口不完整问题）

快速检查当前版本：

```bash
python -V
```

建议固定创建方式：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 运行方式

### 1) 摄像头实时识别

```bash
python run.py --source 0
```

默认优先上半身识别，更适合笔记本近距离场景。
如需强制全身模式：

```bash
python run.py --source 0 --full-body
```

建议先用高分辨率 + 调试模式定位：

```bash
python run.py --source 0 --set-res 1280x720 --debug
```

如果框仍漂移，建议加跟踪调参：

```bash
python run.py --source 0 --set-res 1280x720 --debug --smooth-alpha 0.25 --detect-interval 8
```

### 2) 视频文件识别

```bash
python run.py --source demo.mp4
```

## 可调参数

- `--min-area`: 最小人体框面积（默认 12000）
- `--history`: 动作判断的历史帧数（默认 10）
- `--display-scale`: 显示缩放比例（默认 1.0）
- `--set-res`: 设置摄像头分辨率（如 `1280x720`）
- `--debug`: 打开调试日志与画面调试信息（fps/检测计数/框参数）
- `--smooth-alpha`: 检测框平滑系数（默认 `0.45`，越小越稳）
- `--detect-interval`: 跟踪时每 N 帧重新检测一次（默认 `6`）
- `--pose`: `auto/on/off`，是否使用 MediaPipe Pose 真实关键点（默认 `auto`）
- `--pose-min-visibility`: Pose 关键点可见性阈值（默认 `0.35`）

示例：

```bash
python run.py --source 0 --min-area 9000 --history 12 --display-scale 1.2
python run.py --source 0 --set-res 1280x720 --debug --smooth-alpha 0.35
python run.py --source 0 --set-res 1280x720 --debug --pose on
python run.py --source 0 --set-res 1280x720 --debug --pose on --pose-min-visibility 0.3
```

## 手臂识别专项 Demo（推荐）

如果你当前只能稳定识别人脸，但手臂识别效果差，建议直接运行基于 MediaPipe Pose 关键点的专项脚本：

```bash
python arm_pose_demo.py --source 0 --set-res 1280x720
```

该脚本会直接使用肩/肘/腕关键点，不再依赖“人脸推导上半身框”的近似方法；支持输出手臂状态：

- `arm_up`
- `arm_side`
- `arm_bent`
- `arm_down`

可调参数：

- `--min-visibility`：关键点可见性阈值，默认 `0.35`（手臂经常丢失可尝试降到 `0.25`）
- `--model-complexity`：Pose 模型复杂度 `0/1/2`（复杂度越高通常更准但更慢）
- `--backend`：`auto/solutions/tasks`（默认 `auto`）
- `--task-model`：`tasks` 后端模型路径（默认 `pose_landmarker_full.task`）；若文件不存在会自动下载
- 默认开启左右镜像显示（更接近自拍预览）；如需关闭可加 `--no-mirror`

如果你的 `mediapipe` 没有 `mp.solutions`（只包含 `tasks`），可这样运行：

```bash
python arm_pose_demo.py --backend tasks --task-model /path/to/pose_landmarker.task --source 0 --set-res 1280x720
```

### 运行脚本（推荐）

项目内提供了一键脚本：`run_arm_pose.sh`

默认行为（无参数）：

```bash
./run_arm_pose.sh
```

默认会执行：

```bash
python arm_pose_demo.py --backend tasks --task-model pose_landmarker_full.task --source 0 --set-res 1280x720
```

自定义参数（会覆盖默认值）：

```bash
./run_arm_pose.sh --backend tasks --task-model models/pose_landmarker_full.task --source 0 --set-res 1920x1080
```

常见原因（为什么“能识别人脸，不能识别手臂”）：

- 当前流程可能落在 `face_upper` 分支，只是根据人脸估算上半身框并画固定骨架，不是实时手臂关键点
- `--pose` 没生效或环境里 `mediapipe` 不可用，程序回退到了启发式模式
- 分辨率低、手臂出画、遮挡严重导致腕部关键点可见性太低

## 动作标签说明

- `standing`: 几乎不动
- `walking_or_running`: 下肢或整体移动明显
- `upper_body_active`: 上肢区域变化明显（如挥手）
- `moving`: 有动作但不满足以上强规则

按 `q` 退出。
