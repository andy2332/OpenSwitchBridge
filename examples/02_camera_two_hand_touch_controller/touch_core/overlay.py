from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import cv2
import numpy as np

from .features import PoseFeatures
from .models import ControllerState


def _txt(frame, text: str, row: int, color=(255, 255, 255)):
    cv2.putText(frame, text, (12, 24 + row * 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)


def _norm_to_px(frame, p: np.ndarray) -> tuple[int, int]:
    h, w = frame.shape[:2]
    return int(round(float(p[0]) * w)), int(round(float(p[1]) * h))


def _tpl_to_norm(tpl_xy, rect_center, rect_size, tpl_size) -> np.ndarray:
    x = (float(tpl_xy[0]) / max(float(tpl_size[0]), 1e-5)) * float(rect_size[0]) + (float(rect_center[0]) - float(rect_size[0]) * 0.5)
    y = (float(tpl_xy[1]) / max(float(tpl_size[1]), 1e-5)) * float(rect_size[1]) + (float(rect_center[1]) - float(rect_size[1]) * 0.5)
    return np.array([x, y], dtype=float)


def _blend_image_into_rect(frame, image, x1: int, y1: int, x2: int, y2: int, alpha: float) -> None:
    if image is None:
        return
    h, w = frame.shape[:2]
    if x1 >= x2 or y1 >= y2:
        return

    tx1 = max(0, x1)
    ty1 = max(0, y1)
    tx2 = min(w, x2)
    ty2 = min(h, y2)
    if tx1 >= tx2 or ty1 >= ty2:
        return

    target_w = x2 - x1
    target_h = y2 - y1
    resized = cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

    sx1 = tx1 - x1
    sy1 = ty1 - y1
    sx2 = sx1 + (tx2 - tx1)
    sy2 = sy1 + (ty2 - ty1)
    patch = resized[sy1:sy2, sx1:sx2]

    roi = frame[ty1:ty2, tx1:tx2]
    a = max(0.0, min(1.0, float(alpha)))
    blended = cv2.addWeighted(roi, 1.0 - a, patch, a, 0.0)
    frame[ty1:ty2, tx1:tx2] = blended


def _draw_controller_touch(frame, debug: Dict[str, Any], ui_image, ui_alpha: float) -> None:
    if not debug or not debug.get("enabled", False):
        return

    rect_center = np.array(debug.get("rect_center", [0.5, 0.5]), dtype=float)
    rect_size = np.array(debug.get("rect_size", [0.4, 0.35]), dtype=float)
    tpl_size = np.array(debug.get("template_size", [768.0, 674.0]), dtype=float)
    pressed = set(debug.get("pressed", []))

    tl = rect_center - rect_size * 0.5
    br = rect_center + rect_size * 0.5
    tl_px = _norm_to_px(frame, tl)
    br_px = _norm_to_px(frame, br)
    x1, y1 = min(tl_px[0], br_px[0]), min(tl_px[1], br_px[1])
    x2, y2 = max(tl_px[0], br_px[0]), max(tl_px[1], br_px[1])

    _blend_image_into_rect(frame, ui_image, x1, y1, x2, y2, ui_alpha)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (170, 200, 255), 2)

    buttons = debug.get("buttons", {})
    for name, spec in buttons.items():
        if len(spec) != 3:
            continue
        c_norm = _tpl_to_norm((spec[0], spec[1]), rect_center, rect_size, tpl_size)
        edge = _tpl_to_norm((spec[0] + spec[2], spec[1]), rect_center, rect_size, tpl_size)
        r_px = max(4, int(round(np.linalg.norm(np.array(_norm_to_px(frame, edge)) - np.array(_norm_to_px(frame, c_norm))))))
        color = (60, 220, 80) if name in pressed else (180, 180, 180)
        cv2.circle(frame, _norm_to_px(frame, c_norm), r_px, color, 2)
        cv2.putText(frame, name, (int(_norm_to_px(frame, c_norm)[0] - r_px), int(_norm_to_px(frame, c_norm)[1] - r_px - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)

    sticks = debug.get("sticks", {})
    for name in ["left", "right"]:
        spec = sticks.get(name)
        if not spec or len(spec) != 3:
            continue
        c_norm = _tpl_to_norm((spec[0], spec[1]), rect_center, rect_size, tpl_size)
        edge = _tpl_to_norm((spec[0] + spec[2], spec[1]), rect_center, rect_size, tpl_size)
        r_px = max(6, int(round(np.linalg.norm(np.array(_norm_to_px(frame, edge)) - np.array(_norm_to_px(frame, c_norm))))))
        cv2.circle(frame, _norm_to_px(frame, c_norm), r_px, (255, 220, 120), 2)

    lw_tpl = debug.get("left_wrist_tpl", [0.0, 0.0])
    rw_tpl = debug.get("right_wrist_tpl", [0.0, 0.0])
    lw_norm = _tpl_to_norm((lw_tpl[0], lw_tpl[1]), rect_center, rect_size, tpl_size)
    rw_norm = _tpl_to_norm((rw_tpl[0], rw_tpl[1]), rect_center, rect_size, tpl_size)
    cv2.circle(frame, _norm_to_px(frame, lw_norm), 6, (255, 80, 80), -1)
    cv2.circle(frame, _norm_to_px(frame, rw_norm), 6, (80, 80, 255), -1)
    cv2.putText(frame, "L", (int(_norm_to_px(frame, lw_norm)[0] + 8), int(_norm_to_px(frame, lw_norm)[1] + 4)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 80, 80), 1, cv2.LINE_AA)
    cv2.putText(frame, "R", (int(_norm_to_px(frame, rw_norm)[0] + 8), int(_norm_to_px(frame, rw_norm)[1] + 4)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (80, 80, 255), 1, cv2.LINE_AA)


def export_controller_debug_image(debug: Dict[str, Any] | None, ui_image, output_path: str | Path) -> bool:
    if not debug or not debug.get("enabled", False):
        return False

    tpl_size = np.array(debug.get("template_size", [768.0, 674.0]), dtype=float)
    canvas_w = max(1, int(round(float(tpl_size[0]))))
    canvas_h = max(1, int(round(float(tpl_size[1]))))

    if ui_image is not None:
        canvas = cv2.resize(ui_image, (canvas_w, canvas_h), interpolation=cv2.INTER_LINEAR)
    else:
        canvas = np.full((canvas_h, canvas_w, 3), 24, dtype=np.uint8)
        cv2.rectangle(canvas, (0, 0), (canvas_w - 1, canvas_h - 1), (80, 80, 80), 1)

    buttons = debug.get("buttons", {})
    pressed = set(debug.get("pressed", []))
    for name, spec in buttons.items():
        if len(spec) != 3:
            continue
        cx = int(round(float(spec[0])))
        cy = int(round(float(spec[1])))
        radius = max(3, int(round(float(spec[2]))))
        color = (60, 220, 80) if name in pressed else (180, 180, 180)
        cv2.circle(canvas, (cx, cy), radius, color, 2)
        cv2.putText(canvas, name, (cx + radius + 4, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

    sticks = debug.get("sticks", {})
    for name in ["left", "right"]:
        spec = sticks.get(name)
        if not spec or len(spec) != 3:
            continue
        cx = int(round(float(spec[0])))
        cy = int(round(float(spec[1])))
        radius = max(3, int(round(float(spec[2]))))
        cv2.circle(canvas, (cx, cy), radius, (255, 220, 120), 2)
        cv2.putText(canvas, f"{name}_stick", (cx + radius + 4, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 220, 120), 1, cv2.LINE_AA)

    lw_tpl = debug.get("left_wrist_tpl", [0.0, 0.0])
    rw_tpl = debug.get("right_wrist_tpl", [0.0, 0.0])
    lw_pt = (int(round(float(lw_tpl[0]))), int(round(float(lw_tpl[1]))))
    rw_pt = (int(round(float(rw_tpl[0]))), int(round(float(rw_tpl[1]))))
    cv2.circle(canvas, lw_pt, 7, (255, 80, 80), -1)
    cv2.circle(canvas, rw_pt, 7, (80, 80, 255), -1)
    cv2.putText(canvas, "L_wrist", (lw_pt[0] + 10, lw_pt[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 80, 80), 1, cv2.LINE_AA)
    cv2.putText(canvas, "R_wrist", (rw_pt[0] + 10, rw_pt[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 80, 255), 1, cv2.LINE_AA)
    cv2.putText(canvas, "green=pressed", (10, canvas_h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (60, 220, 80), 1, cv2.LINE_AA)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return bool(cv2.imwrite(str(output_path), canvas))


def export_controller_base_image(debug: Dict[str, Any] | None, ui_image, output_path: str | Path) -> bool:
    if not debug or not debug.get("enabled", False):
        return False

    tpl_size = np.array(debug.get("template_size", [768.0, 674.0]), dtype=float)
    canvas_w = max(1, int(round(float(tpl_size[0]))))
    canvas_h = max(1, int(round(float(tpl_size[1]))))

    if ui_image is not None:
        canvas = cv2.resize(ui_image, (canvas_w, canvas_h), interpolation=cv2.INTER_LINEAR)
    else:
        canvas = np.full((canvas_h, canvas_w, 3), 24, dtype=np.uint8)
        cv2.rectangle(canvas, (0, 0), (canvas_w - 1, canvas_h - 1), (80, 80, 80), 1)

    # Draw static trigger layout (buttons + sticks), without live wrist points.
    buttons = debug.get("buttons", {})
    for name, spec in buttons.items():
        if len(spec) != 3:
            continue
        cx = int(round(float(spec[0])))
        cy = int(round(float(spec[1])))
        radius = max(3, int(round(float(spec[2]))))
        color = (180, 180, 180)
        cv2.circle(canvas, (cx, cy), radius, color, 2)
        cv2.putText(canvas, name, (cx + radius + 4, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

    sticks = debug.get("sticks", {})
    for name in ["left", "right"]:
        spec = sticks.get(name)
        if not spec or len(spec) != 3:
            continue
        cx = int(round(float(spec[0])))
        cy = int(round(float(spec[1])))
        radius = max(3, int(round(float(spec[2]))))
        color = (255, 220, 120)
        cv2.circle(canvas, (cx, cy), radius, color, 2)
        cv2.putText(canvas, f"{name}_stick", (cx + radius + 4, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return bool(cv2.imwrite(str(output_path), canvas))


def draw_overlay(
    frame,
    features: PoseFeatures | None,
    state: ControllerState,
    cfg: Dict,
    debug_overlay: Dict[str, Any] | None = None,
    touch_ui_image=None,
):
    row = 0
    _txt(frame, "[q] quit [r] reload [p] save debug [+/-] controller size", row, (80, 220, 255))
    row += 1

    if features is not None and cfg["ui"].get("show_features", True):
        _txt(frame, f"torso_len: {features.torso_len:.4f}", row)
        row += 1
        _txt(frame, f"shoulder_center: ({features.shoulder_center[0]:.3f}, {features.shoulder_center[1]:.3f})", row)
        row += 1
        _txt(frame, f"hip_center: ({features.hip_center[0]:.3f}, {features.hip_center[1]:.3f})", row)
        row += 1

    lx, ly = state.left_stick
    rx, ry = state.right_stick
    _txt(frame, f"LStick: ({lx:+.2f}, {ly:+.2f})  RStick: ({rx:+.2f}, {ry:+.2f})", row, (180, 255, 160))
    row += 1

    pressed = [k for k, v in state.buttons.items() if v]
    _txt(frame, "Buttons: " + (", ".join(pressed) if pressed else "-"), row, (180, 255, 160))
    row += 1

    if cfg["ui"].get("show_debug", True):
        _txt(frame, "Actions:", row, (255, 200, 120))
        row += 1
        for name, conf in state.active_actions[:6]:
            _txt(frame, f"- {name}: {conf:.2f}", row, (255, 200, 120))
            row += 1

    if debug_overlay is not None:
        ui_alpha = float(cfg.get("controller_touch", {}).get("ui_alpha", 0.45))
        _draw_controller_touch(frame, debug_overlay, touch_ui_image, ui_alpha)
